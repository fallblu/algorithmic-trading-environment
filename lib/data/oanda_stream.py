"""OANDA streaming API — real-time price quote feed with auto-reconnect."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable

import httpx

from models.bar import Bar

log = logging.getLogger(__name__)

STREAM_URL = "https://stream-fxpractice.oanda.com/v3"


class OandaStream:
    """OANDA streaming API client for real-time price quotes.

    OANDA streams individual price ticks. This client aggregates them
    into OHLCV bars at the configured interval.

    Features:
    - Auto-reconnect with exponential backoff
    - Connection status tracking
    - Tick-to-bar aggregation
    """

    def __init__(
        self,
        symbols: list[str],
        api_key: str,
        account_id: str,
        timeframe: str = "1m",
        on_bar: Callable[[Bar], None] | None = None,
        on_status_change: Callable[[str], None] | None = None,
        max_retries: int = 20,
    ) -> None:
        self._symbols = symbols
        self._api_key = api_key
        self._account_id = account_id
        self._timeframe = timeframe
        self._on_bar = on_bar
        self._on_status_change = on_status_change
        self._max_retries = max_retries
        self._backoff_schedule = [1, 2, 4, 8, 16, 32, 60]
        self._retry_count = 0
        self._status = "disconnected"
        self._running = False

        # Bar aggregation state per symbol
        self._current_bars: dict[str, dict] = {}
        self._interval_seconds = self._parse_interval(timeframe)

    @property
    def connection_status(self) -> str:
        return self._status

    def _set_status(self, status: str) -> None:
        self._status = status
        if self._on_status_change:
            self._on_status_change(status)

    def _parse_interval(self, tf: str) -> int:
        mapping = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
        return mapping.get(tf, 60)

    async def connect(self) -> None:
        """Connect and start receiving prices. Reconnects on failure."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_stream()
            except (httpx.HTTPError, OSError, Exception) as e:
                if not self._running:
                    break
                self._retry_count += 1
                if self._retry_count > self._max_retries:
                    log.error("Max retries (%d) reached", self._max_retries)
                    self._set_status("disconnected")
                    break

                backoff_idx = min(self._retry_count - 1, len(self._backoff_schedule) - 1)
                delay = self._backoff_schedule[backoff_idx]
                log.warning(
                    "OANDA stream disconnected (%s), reconnecting in %ds (attempt %d/%d)",
                    e, delay, self._retry_count, self._max_retries,
                )
                self._set_status("reconnecting")
                await asyncio.sleep(delay)

    async def _connect_and_stream(self) -> None:
        """Establish streaming connection and process price updates."""
        instruments = ",".join(s.replace("/", "_") for s in self._symbols)
        url = f"{STREAM_URL}/accounts/{self._account_id}/pricing/stream"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        params = {"instruments": instruments}

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url, headers=headers, params=params) as resp:
                resp.raise_for_status()
                self._set_status("connected")
                self._retry_count = 0
                log.info("Connected to OANDA price stream")

                async for line in resp.aiter_lines():
                    if not self._running:
                        break
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        self._process_tick(data)
                    except json.JSONDecodeError:
                        continue

    def _process_tick(self, data: dict) -> None:
        """Process a price tick and aggregate into bars."""
        if data.get("type") != "PRICE":
            return

        instrument = data.get("instrument", "").replace("_", "/")
        if instrument not in self._symbols:
            return

        try:
            # Use mid price (average of bid and ask)
            bids = data.get("bids", [{}])
            asks = data.get("asks", [{}])
            bid = float(bids[0].get("price", 0))
            ask = float(asks[0].get("price", 0))
            mid = (bid + ask) / 2
            ts = datetime.fromisoformat(data["time"].replace("Z", "+00:00"))
        except (KeyError, ValueError, IndexError):
            return

        # Determine which bar interval this tick belongs to
        epoch = int(ts.timestamp())
        bar_epoch = epoch - (epoch % self._interval_seconds)

        current = self._current_bars.get(instrument)

        if current is None or current["epoch"] != bar_epoch:
            # Emit previous bar if exists
            if current is not None:
                self._emit_bar(instrument, current)

            # Start new bar
            self._current_bars[instrument] = {
                "epoch": bar_epoch,
                "open": mid,
                "high": mid,
                "low": mid,
                "close": mid,
                "volume": 0.0,
                "timestamp": datetime.fromtimestamp(bar_epoch, tz=timezone.utc),
            }
        else:
            current["high"] = max(current["high"], mid)
            current["low"] = min(current["low"], mid)
            current["close"] = mid
            current["volume"] += 1  # Tick count as volume proxy

    def _emit_bar(self, symbol: str, bar_data: dict) -> None:
        bar = Bar(
            symbol=symbol,
            timestamp=bar_data["timestamp"],
            open=bar_data["open"],
            high=bar_data["high"],
            low=bar_data["low"],
            close=bar_data["close"],
            volume=bar_data["volume"],
        )
        if self._on_bar:
            self._on_bar(bar)

    async def disconnect(self) -> None:
        self._running = False
        # Emit any remaining bars
        for symbol, bar_data in self._current_bars.items():
            self._emit_bar(symbol, bar_data)
        self._current_bars.clear()
        self._set_status("disconnected")
