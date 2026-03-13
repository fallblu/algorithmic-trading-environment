"""Kraken WebSocket v2 — real-time OHLC candle feed with auto-reconnect."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable

import websockets

from models.bar import Bar

log = logging.getLogger(__name__)

WS_URL = "wss://ws.kraken.com/v2"

TIMEFRAME_INTERVAL = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


class KrakenWebSocket:
    """Kraken WebSocket v2 client for real-time OHLC candles.

    Features:
    - Auto-reconnect with exponential backoff
    - Connection status tracking
    - Callback-based bar delivery
    """

    def __init__(
        self,
        symbols: list[str],
        timeframe: str = "1m",
        on_bar: Callable[[Bar], None] | None = None,
        on_status_change: Callable[[str], None] | None = None,
        max_retries: int = 20,
    ) -> None:
        self._symbols = symbols
        self._timeframe = timeframe
        self._interval = TIMEFRAME_INTERVAL.get(timeframe, 1)
        self._on_bar = on_bar
        self._on_status_change = on_status_change
        self._max_retries = max_retries
        self._backoff_schedule = [1, 2, 4, 8, 16, 32, 60]
        self._retry_count = 0
        self._status = "disconnected"
        self._running = False
        self._ws = None

    @property
    def connection_status(self) -> str:
        return self._status

    def _set_status(self, status: str) -> None:
        self._status = status
        if self._on_status_change:
            self._on_status_change(status)

    async def connect(self) -> None:
        """Connect and start receiving bars. Reconnects on failure."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except (websockets.exceptions.ConnectionClosed, OSError, Exception) as e:
                if not self._running:
                    break
                self._retry_count += 1
                if self._retry_count > self._max_retries:
                    log.error("Max retries (%d) reached, giving up", self._max_retries)
                    self._set_status("disconnected")
                    break

                backoff_idx = min(self._retry_count - 1, len(self._backoff_schedule) - 1)
                delay = self._backoff_schedule[backoff_idx]
                log.warning(
                    "WebSocket disconnected (%s), reconnecting in %ds (attempt %d/%d)",
                    e, delay, self._retry_count, self._max_retries,
                )
                self._set_status("reconnecting")
                await asyncio.sleep(delay)

    async def _connect_and_listen(self) -> None:
        """Establish connection, subscribe, and process messages."""
        async with websockets.connect(WS_URL) as ws:
            self._ws = ws
            self._set_status("connected")
            self._retry_count = 0
            log.info("Connected to Kraken WebSocket v2")

            # Subscribe to OHLC channel
            subscribe_msg = {
                "method": "subscribe",
                "params": {
                    "channel": "ohlc",
                    "symbol": [s.replace("/", "") for s in self._symbols],
                    "interval": self._interval,
                },
            }
            await ws.send(json.dumps(subscribe_msg))

            async for raw_msg in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw_msg)
                    self._process_message(msg)
                except json.JSONDecodeError:
                    log.warning("Invalid JSON from WebSocket: %s", raw_msg[:200])

    def _process_message(self, msg: dict) -> None:
        """Process a WebSocket message, emitting Bar via callback."""
        if msg.get("channel") != "ohlc":
            return

        for item in msg.get("data", []):
            try:
                # Map Kraken symbol back to normalized form
                raw_symbol = item.get("symbol", "")
                symbol = self._normalize_symbol(raw_symbol)
                ts = datetime.fromisoformat(item["timestamp"]).astimezone(timezone.utc)

                bar = Bar(
                    symbol=symbol,
                    timestamp=ts,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item.get("volume", 0)),
                )

                if self._on_bar:
                    self._on_bar(bar)
            except (KeyError, ValueError) as e:
                log.warning("Failed to parse OHLC message: %s", e)

    def _normalize_symbol(self, raw: str) -> str:
        """Convert Kraken symbol back to normalized form (e.g., XBTUSD -> BTC/USD)."""
        reverse_map = {
            "XBT/USD": "BTC/USD",
            "XBTUSD": "BTC/USD",
        }
        if raw in reverse_map:
            return reverse_map[raw]
        # Try to add a slash before USD/EUR/GBP/JPY
        for quote in ("USD", "EUR", "GBP", "JPY"):
            if raw.endswith(quote):
                base = raw[: -len(quote)]
                return f"{base}/{quote}"
        return raw

    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        self._running = False
        if self._ws:
            await self._ws.close()
        self._set_status("disconnected")
