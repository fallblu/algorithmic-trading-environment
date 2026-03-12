"""OANDA streaming price feed — real-time tick data via HTTP streaming."""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from decimal import Decimal

from constants import normalize_symbol, denormalize_symbol
from models.bar import Bar

log = logging.getLogger(__name__)


class OandaStream:
    """Connects to OANDA streaming API for real-time price ticks.

    Aggregates ticks into OHLCV bars at the configured timeframe.
    Optionally records raw tick data to Parquet.
    """

    def __init__(
        self,
        instruments: list[str],
        timeframe: str = "1m",
        record_ticks: bool = False,
    ):
        self._instruments = instruments
        self._timeframe = timeframe
        self._record_ticks = record_ticks
        self._running = False
        self._thread: threading.Thread | None = None
        self._bar_callbacks: list = []
        self._tick_callbacks: list = []

        # Current bar state per instrument
        self._current_bars: dict[str, dict] = {}
        self._bar_start_times: dict[str, datetime] = {}

        self._timeframe_seconds = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400,
        }.get(timeframe, 60)

    def on_bar(self, callback) -> None:
        """Register a callback for completed bars."""
        self._bar_callbacks.append(callback)

    def on_tick(self, callback) -> None:
        """Register a callback for raw ticks."""
        self._tick_callbacks.append(callback)

    def start(self) -> None:
        """Start streaming in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._stream_loop, name="OandaStream", daemon=True
        )
        self._thread.start()
        log.info("OANDA stream started for %s", self._instruments)

    def stop(self) -> None:
        """Stop streaming."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("OANDA stream stopped")

    def _stream_loop(self) -> None:
        """Main streaming loop with reconnection."""
        import httpx

        environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
        if environment == "live":
            stream_url = "https://stream-fxtrade.oanda.com"
        else:
            stream_url = "https://stream-fxpractice.oanda.com"

        token = os.environ.get("OANDA_API_TOKEN", "")
        account_id = os.environ.get("OANDA_ACCOUNT_ID", "")

        oanda_instruments = ",".join(normalize_symbol(s) for s in self._instruments)
        url = f"{stream_url}/v3/accounts/{account_id}/pricing/stream"

        delay = 1.0
        while self._running:
            try:
                with httpx.stream(
                    "GET", url,
                    params={"instruments": oanda_instruments},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=httpx.Timeout(30.0, read=None),
                ) as response:
                    delay = 1.0  # Reset on successful connect
                    for line in response.iter_lines():
                        if not self._running:
                            break
                        if line:
                            self._process_message(line)

            except Exception as e:
                if not self._running:
                    break
                log.warning("OANDA stream error (%s). Reconnecting in %.1fs...", e, delay)
                import time
                time.sleep(delay)
                delay = min(delay * 2, 60.0)

    def _process_message(self, line: str) -> None:
        """Parse a streaming JSON message."""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type")

        if msg_type == "HEARTBEAT":
            return

        if msg_type == "PRICE":
            self._process_tick(msg)

    def _process_tick(self, msg: dict) -> None:
        """Process a price tick and aggregate into bars."""
        oanda_instrument = msg.get("instrument", "")
        our_symbol = denormalize_symbol(oanda_instrument)

        bids = msg.get("bids", [])
        asks = msg.get("asks", [])
        if not bids or not asks:
            return

        bid = Decimal(bids[0]["price"])
        ask = Decimal(asks[0]["price"])
        mid = (bid + ask) / 2
        spread = ask - bid

        ts = datetime.fromisoformat(msg["time"].replace("Z", "+00:00"))

        tick = {
            "timestamp": ts,
            "symbol": our_symbol,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": spread,
        }

        # Notify tick callbacks
        for cb in self._tick_callbacks:
            try:
                cb(tick)
            except Exception:
                log.exception("Error in tick callback")

        # Aggregate into bar
        self._aggregate_tick(our_symbol, mid, ts)

    def _aggregate_tick(self, symbol: str, price: Decimal, timestamp: datetime) -> None:
        """Aggregate a tick into the current bar."""
        bar_start = self._bar_start_times.get(symbol)

        # Determine bar boundary
        epoch_seconds = int(timestamp.timestamp())
        bar_epoch = epoch_seconds - (epoch_seconds % self._timeframe_seconds)
        bar_boundary = datetime.fromtimestamp(bar_epoch, tz=timezone.utc)

        if bar_start is not None and bar_boundary > bar_start:
            # New bar period — complete the previous bar
            current = self._current_bars.get(symbol)
            if current:
                bar = Bar(
                    instrument_symbol=symbol,
                    timestamp=bar_start,
                    open=current["open"],
                    high=current["high"],
                    low=current["low"],
                    close=current["close"],
                    volume=Decimal(str(current["ticks"])),
                )
                for cb in self._bar_callbacks:
                    try:
                        cb(bar)
                    except Exception:
                        log.exception("Error in bar callback")

        if bar_start is None or bar_boundary > bar_start:
            # Start new bar
            self._current_bars[symbol] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "ticks": 1,
            }
            self._bar_start_times[symbol] = bar_boundary
        else:
            # Update current bar
            current = self._current_bars[symbol]
            current["high"] = max(current["high"], price)
            current["low"] = min(current["low"], price)
            current["close"] = price
            current["ticks"] += 1
