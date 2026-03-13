"""Kraken REST API client — fetch OHLCV candle data."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

from models.bar import Bar

log = logging.getLogger(__name__)

BASE_URL = "https://api.kraken.com/0/public"

# Kraken uses non-standard symbol names for the API
SYMBOL_MAP = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
    "SOL/USD": "SOLUSD",
    "XRP/USD": "XRPUSD",
    "ADA/USD": "ADAUSD",
    "DOT/USD": "DOTUSD",
    "DOGE/USD": "DOGEUSD",
    "AVAX/USD": "AVAXUSD",
    "MATIC/USD": "MATICUSD",
    "LINK/USD": "LINKUSD",
}

TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}


def resolve_symbol(symbol: str) -> str:
    """Convert normalized symbol to Kraken API format."""
    return SYMBOL_MAP.get(symbol, symbol.replace("/", ""))


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    since: datetime | None = None,
) -> list[Bar]:
    """Fetch OHLCV candles from Kraken REST API.

    Returns at most 720 bars per call (Kraken's limit).
    """
    pair = resolve_symbol(symbol)
    interval = TIMEFRAME_MINUTES.get(timeframe, 60)

    params: dict = {"pair": pair, "interval": interval}
    if since is not None:
        params["since"] = int(since.timestamp())

    resp = requests.get(f"{BASE_URL}/OHLC", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("error"):
        raise RuntimeError(f"Kraken API error: {data['error']}")

    result_key = next(k for k in data["result"] if k != "last")
    raw_bars = data["result"][result_key]

    bars: list[Bar] = []
    for row in raw_bars:
        # Kraken format: [time, open, high, low, close, vwap, volume, count]
        ts = datetime.fromtimestamp(row[0], tz=timezone.utc)
        bars.append(Bar(
            symbol=symbol,
            timestamp=ts,
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[6]),
        ))

    return bars


def backfill_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    start: datetime | None = None,
    end: datetime | None = None,
    rate_limit_sleep: float = 1.0,
) -> list[Bar]:
    """Backfill OHLCV data with pagination. Returns all bars in date range."""
    all_bars: list[Bar] = []
    since = start

    while True:
        batch = fetch_ohlcv(symbol, timeframe, since)
        if not batch:
            break

        # Filter by end date
        if end is not None:
            batch = [b for b in batch if b.timestamp <= end]

        all_bars.extend(batch)
        log.info("Fetched %d bars for %s (total: %d)", len(batch), symbol, len(all_bars))

        if len(batch) < 700:  # Less than Kraken's max = no more data
            break

        # Move since to last bar's timestamp
        since = batch[-1].timestamp

        time.sleep(rate_limit_sleep)

    # Deduplicate by timestamp
    seen: set[datetime] = set()
    unique: list[Bar] = []
    for bar in all_bars:
        if bar.timestamp not in seen:
            seen.add(bar.timestamp)
            unique.append(bar)

    return sorted(unique, key=lambda b: b.timestamp)
