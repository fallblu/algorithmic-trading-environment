"""LiveFuturesFeed — real-time Kraken Futures market data via WebSocket."""

import asyncio
import json
import logging
import queue
import threading
from datetime import datetime, timezone
from decimal import Decimal

from data.feed import DataFeed
from data.kraken_futures_api import SYMBOL_TO_KRAKEN_FUTURES, TIMEFRAME_RESOLUTION, fetch_ohlcv_futures
from models.bar import Bar, FundingRate
from models.instrument import Instrument

log = logging.getLogger(__name__)

WS_FUTURES_URL = "wss://futures.kraken.com/ws/v1"


class LiveFuturesFeed(DataFeed):
    """Real-time market data from Kraken Futures WebSocket.

    Subscribes to candle and ticker channels. Completed bars and
    funding rate updates are queued for consumption.
    """

    def __init__(self, reconnect_delay: float = 5.0, max_reconnect_delay: float = 60.0):
        self._bar_queue: queue.Queue[Bar] = queue.Queue(maxsize=1000)
        self._funding_queue: queue.Queue[FundingRate] = queue.Queue(maxsize=100)
        self._shutdown_event = threading.Event()
        self._ws_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._subscriptions: list[tuple[Instrument, str]] = []
        self._connected = threading.Event()
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._last_candle: dict[str, dict] = {}
        self._last_interval_begin: dict[str, str] = {}

    def subscribe(self, instrument: Instrument, timeframe: str) -> None:
        if timeframe not in TIMEFRAME_RESOLUTION:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        self._subscriptions.append((instrument, timeframe))

        if self._ws_thread is None:
            self._ws_thread = threading.Thread(
                target=self._run_ws_loop, name="LiveFuturesFeed-WS", daemon=True
            )
            self._ws_thread.start()
            if not self._connected.wait(timeout=10.0):
                log.warning("Futures WebSocket connection not confirmed within 10s")
        else:
            if self._loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._send_subscribe(instrument, timeframe), self._loop
                )

    def next_bar(self) -> Bar | None:
        try:
            return self._bar_queue.get_nowait()
        except queue.Empty:
            return None

    def next_funding_rate(self) -> FundingRate | None:
        try:
            return self._funding_queue.get_nowait()
        except queue.Empty:
            return None

    def historical_bars(self, instrument, timeframe, start, end) -> list[Bar]:
        return fetch_ohlcv_futures(
            symbol=instrument.symbol, timeframe=timeframe, since=start, limit=None
        )

    def shutdown(self) -> None:
        self._shutdown_event.set()
        if self._loop is not None and not self._loop.is_closed():
            async def _close():
                if self._ws is not None:
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
            try:
                future = asyncio.run_coroutine_threadsafe(_close(), self._loop)
                future.result(timeout=3.0)
            except Exception:
                pass
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass
        if self._ws_thread is not None:
            self._ws_thread.join(timeout=5.0)
            self._ws_thread = None
        log.info("LiveFuturesFeed shut down")

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def _run_ws_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._ws_manager())
        except Exception:
            if not self._shutdown_event.is_set():
                log.exception("Futures WebSocket event loop crashed")
        finally:
            self._loop.close()
            self._connected.clear()

    async def _ws_manager(self) -> None:
        import websockets

        delay = self._reconnect_delay
        while not self._shutdown_event.is_set():
            try:
                async with websockets.connect(
                    WS_FUTURES_URL, ping_interval=30, ping_timeout=10, close_timeout=5
                ) as ws:
                    self._ws = ws
                    self._connected.set()
                    delay = self._reconnect_delay
                    log.info("Futures WebSocket connected to %s", WS_FUTURES_URL)

                    for instrument, timeframe in self._subscriptions:
                        await self._send_subscribe(instrument, timeframe)

                    async for raw_msg in ws:
                        if self._shutdown_event.is_set():
                            break
                        self._handle_message(raw_msg)

            except Exception as e:
                self._connected.clear()
                if self._shutdown_event.is_set():
                    break
                log.warning("Futures WS disconnected (%s). Reconnecting in %.1fs...", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)

    async def _send_subscribe(self, instrument: Instrument, timeframe: str) -> None:
        kraken_sym = SYMBOL_TO_KRAKEN_FUTURES.get(instrument.symbol, instrument.symbol)
        resolution = TIMEFRAME_RESOLUTION[timeframe]

        # Subscribe to candle feed
        candle_msg = {
            "event": "subscribe",
            "feed": f"candles_trade_{resolution}",
            "product_ids": [kraken_sym],
        }
        if self._ws is not None:
            await self._ws.send(json.dumps(candle_msg))

        # Subscribe to ticker for funding rate
        ticker_msg = {
            "event": "subscribe",
            "feed": "ticker",
            "product_ids": [kraken_sym],
        }
        if self._ws is not None:
            await self._ws.send(json.dumps(ticker_msg))
            log.info("Subscribed to futures %s candle+ticker", kraken_sym)

    def _handle_message(self, raw_msg: str) -> None:
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            return

        feed = msg.get("feed", "")

        if "candles_trade" in feed:
            candles = msg.get("candles", [])
            for candle in candles:
                self._process_candle(candle)
        elif feed == "ticker":
            self._process_ticker(msg)

    def _process_candle(self, candle: dict) -> None:
        symbol = candle.get("symbol", "")
        interval_begin = str(candle.get("time", ""))
        key = symbol

        prev_begin = self._last_interval_begin.get(key)
        prev_candle = self._last_candle.get(key)

        if prev_begin is not None and interval_begin != prev_begin and prev_candle is not None:
            bar = self._candle_to_bar(prev_candle)
            if bar is not None:
                try:
                    self._bar_queue.put_nowait(bar)
                except queue.Full:
                    try:
                        self._bar_queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._bar_queue.put_nowait(bar)

        self._last_candle[key] = candle
        self._last_interval_begin[key] = interval_begin

    def _candle_to_bar(self, candle: dict) -> Bar | None:
        try:
            kraken_sym = candle.get("symbol", "")
            from data.kraken_futures_api import KRAKEN_TO_SYMBOL_FUTURES
            our_symbol = KRAKEN_TO_SYMBOL_FUTURES.get(kraken_sym, kraken_sym)

            ts = datetime.fromtimestamp(candle["time"] / 1000, tz=timezone.utc)

            return Bar(
                instrument_symbol=our_symbol,
                timestamp=ts,
                open=Decimal(str(candle["open"])),
                high=Decimal(str(candle["high"])),
                low=Decimal(str(candle["low"])),
                close=Decimal(str(candle["close"])),
                volume=Decimal(str(candle.get("volume", 0))),
            )
        except (KeyError, ValueError, TypeError) as e:
            log.warning("Failed to parse futures candle: %s", e)
            return None

    def _process_ticker(self, msg: dict) -> None:
        try:
            kraken_sym = msg.get("product_id", "")
            from data.kraken_futures_api import KRAKEN_TO_SYMBOL_FUTURES
            our_symbol = KRAKEN_TO_SYMBOL_FUTURES.get(kraken_sym, kraken_sym)

            funding_rate = msg.get("fundingRate")
            next_funding = msg.get("nextFundingRateTime")
            if funding_rate is not None and next_funding is not None:
                fr = FundingRate(
                    instrument_symbol=our_symbol,
                    timestamp=datetime.now(timezone.utc),
                    rate=Decimal(str(funding_rate)),
                    next_funding_time=datetime.fromtimestamp(
                        next_funding / 1000, tz=timezone.utc
                    ),
                )
                try:
                    self._funding_queue.put_nowait(fr)
                except queue.Full:
                    try:
                        self._funding_queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._funding_queue.put_nowait(fr)
        except (KeyError, ValueError, TypeError) as e:
            log.warning("Failed to parse futures ticker: %s", e)
