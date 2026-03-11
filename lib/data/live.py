"""LiveFeed — real-time Kraken market data via WebSocket v2."""

import asyncio
import json
import logging
import queue
import threading
from datetime import datetime, timezone
from decimal import Decimal

from data.feed import DataFeed
from data.kraken_api import TIMEFRAME_MINUTES, fetch_ohlcv
from models.bar import Bar
from models.instrument import Instrument

log = logging.getLogger(__name__)

WS_PUBLIC_URL = "wss://ws.kraken.com/v2"


class LiveFeed(DataFeed):
    """Real-time market data from Kraken WebSocket v2.

    Architecture:
        - subscribe() starts a background daemon thread running an asyncio
          event loop with the WebSocket connection.
        - The WS thread receives OHLC candle updates and places completed
          bars into a thread-safe queue.
        - next_bar() reads from that queue (non-blocking).
        - shutdown() cleanly stops the WS thread.
    """

    def __init__(self, reconnect_delay: float = 5.0, max_reconnect_delay: float = 60.0):
        self._bar_queue: queue.Queue[Bar] = queue.Queue(maxsize=1000)
        self._shutdown_event = threading.Event()
        self._ws_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._subscriptions: list[tuple[Instrument, str]] = []
        self._connected = threading.Event()
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        # Track candle state for completion detection
        self._last_candle: dict[str, dict] = {}
        self._last_interval_begin: dict[str, str] = {}

    def subscribe(self, instrument: Instrument, timeframe: str) -> None:
        """Subscribe to OHLC bars for an instrument.

        Starts the WebSocket background thread on first subscription.
        """
        if timeframe not in TIMEFRAME_MINUTES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        self._subscriptions.append((instrument, timeframe))

        if self._ws_thread is None:
            self._ws_thread = threading.Thread(
                target=self._run_ws_loop,
                name="LiveFeed-WS",
                daemon=True,
            )
            self._ws_thread.start()
            if not self._connected.wait(timeout=10.0):
                log.warning("WebSocket connection not confirmed within 10s")
        else:
            # Thread already running — send subscription on existing connection
            if self._loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._send_subscribe(instrument, timeframe), self._loop
                )

    def subscribe_all(self, instruments: list[Instrument], timeframe: str) -> None:
        """Batch-subscribe to multiple instruments.

        Kraken WS v2 accepts a list of symbols in a single subscribe message,
        so we batch them for efficiency.
        """
        if timeframe not in TIMEFRAME_MINUTES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        for instrument in instruments:
            self._subscriptions.append((instrument, timeframe))

        if self._ws_thread is None:
            self._ws_thread = threading.Thread(
                target=self._run_ws_loop,
                name="LiveFeed-WS",
                daemon=True,
            )
            self._ws_thread.start()
            if not self._connected.wait(timeout=10.0):
                log.warning("WebSocket connection not confirmed within 10s")
        else:
            if self._loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._send_subscribe_batch(instruments, timeframe), self._loop
                )

    def next_bar(self) -> Bar | None:
        """Get the next completed bar from the WebSocket stream.

        Returns None if no bar is available (non-blocking).
        """
        try:
            return self._bar_queue.get_nowait()
        except queue.Empty:
            return None

    def historical_bars(
        self,
        instrument: Instrument,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        """Fetch historical bars via Kraken REST API.

        Delegates to the existing REST client for indicator warmup.
        """
        return fetch_ohlcv(
            symbol=instrument.symbol,
            timeframe=timeframe,
            since=start,
            limit=None,
        )

    def shutdown(self) -> None:
        """Cleanly shut down the WebSocket thread."""
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
                pass  # Loop already closed
        if self._ws_thread is not None:
            self._ws_thread.join(timeout=5.0)
            self._ws_thread = None
        log.info("LiveFeed shut down")

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @property
    def queue_size(self) -> int:
        return self._bar_queue.qsize()

    # --- Background thread internals ---

    def _run_ws_loop(self) -> None:
        """Entry point for the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._ws_manager())
        except Exception:
            if not self._shutdown_event.is_set():
                log.exception("WebSocket event loop crashed")
        finally:
            self._loop.close()
            self._connected.clear()

    async def _ws_manager(self) -> None:
        """Manage the WebSocket connection with reconnection logic."""
        import websockets

        delay = self._reconnect_delay
        while not self._shutdown_event.is_set():
            try:
                async with websockets.connect(
                    WS_PUBLIC_URL,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._connected.set()
                    delay = self._reconnect_delay
                    log.info("WebSocket connected to %s", WS_PUBLIC_URL)

                    # Send all subscriptions
                    for instrument, timeframe in self._subscriptions:
                        await self._send_subscribe(instrument, timeframe)

                    # Read messages
                    async for raw_msg in ws:
                        if self._shutdown_event.is_set():
                            break
                        self._handle_message(raw_msg)

            except Exception as e:
                self._connected.clear()
                if self._shutdown_event.is_set():
                    break
                log.warning(
                    "WebSocket disconnected (%s). Reconnecting in %.1fs...",
                    e, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)

    async def _send_subscribe(self, instrument: Instrument, timeframe: str) -> None:
        """Send an OHLC subscription message."""
        interval = TIMEFRAME_MINUTES[timeframe]
        msg = {
            "method": "subscribe",
            "params": {
                "channel": "ohlc",
                "symbol": [instrument.symbol],
                "interval": interval,
            },
        }
        if self._ws is not None:
            await self._ws.send(json.dumps(msg))
            log.info("Subscribed to ohlc %s interval=%d", instrument.symbol, interval)

    async def _send_subscribe_batch(self, instruments: list[Instrument], timeframe: str) -> None:
        """Send a single OHLC subscription for multiple symbols."""
        interval = TIMEFRAME_MINUTES[timeframe]
        symbols = [inst.symbol for inst in instruments]
        msg = {
            "method": "subscribe",
            "params": {
                "channel": "ohlc",
                "symbol": symbols,
                "interval": interval,
            },
        }
        if self._ws is not None:
            await self._ws.send(json.dumps(msg))
            log.info("Subscribed to ohlc %s interval=%d", symbols, interval)

    def _handle_message(self, raw_msg: str) -> None:
        """Parse a WebSocket message and enqueue completed bars."""
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            log.warning("Invalid JSON from WebSocket: %s", raw_msg[:200])
            return

        if msg.get("channel") != "ohlc":
            return
        if msg.get("type") not in ("update", "snapshot"):
            return

        for candle in msg.get("data", []):
            self._process_candle(candle, msg.get("type"))

    def _process_candle(self, candle: dict, msg_type: str) -> None:
        """Process a single candle update.

        Kraken WS v2 sends ongoing updates for the in-progress candle.
        When interval_begin changes, the previously cached candle is
        complete. We enqueue it as a finished Bar.
        """
        symbol = candle.get("symbol", "")
        interval_begin = candle.get("interval_begin", "")
        key = symbol

        if msg_type == "snapshot":
            self._last_candle[key] = candle
            self._last_interval_begin[key] = interval_begin
            return

        prev_begin = self._last_interval_begin.get(key)
        prev_candle = self._last_candle.get(key)

        if prev_begin is not None and interval_begin != prev_begin and prev_candle is not None:
            # Previous candle is now complete
            bar = self._candle_to_bar(prev_candle)
            if bar is not None:
                try:
                    self._bar_queue.put_nowait(bar)
                except queue.Full:
                    log.warning("Bar queue full — dropping oldest bar for %s", symbol)
                    try:
                        self._bar_queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._bar_queue.put_nowait(bar)

        # Update cache with current candle
        self._last_candle[key] = candle
        self._last_interval_begin[key] = interval_begin

    def _candle_to_bar(self, candle: dict) -> Bar | None:
        """Convert a Kraken WS v2 candle dict to a Bar model."""
        try:
            ts_str = candle.get("interval_begin", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

            return Bar(
                instrument_symbol=candle["symbol"],
                timestamp=ts,
                open=Decimal(str(candle["open"])),
                high=Decimal(str(candle["high"])),
                low=Decimal(str(candle["low"])),
                close=Decimal(str(candle["close"])),
                volume=Decimal(str(candle["volume"])),
                trades=int(candle.get("trades", 0)),
                vwap=Decimal(str(candle["vwap"])) if candle.get("vwap") else None,
            )
        except (KeyError, ValueError, TypeError) as e:
            log.warning("Failed to parse candle: %s — %s", e, candle)
            return None
