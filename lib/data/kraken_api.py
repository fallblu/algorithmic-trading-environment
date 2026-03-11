"""Kraken REST client for OHLCV data backfill."""

import time
from datetime import datetime, timezone
from decimal import Decimal

import requests

from models.bar import Bar

# Kraken OHLC interval mapping (minutes)
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

# Kraken uses different pair names than our symbol format
SYMBOL_TO_KRAKEN = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
    "SOL/USD": "SOLUSD",
    "XRP/USD": "XRPUSD",
}

BASE_URL = "https://api.kraken.com/0/public"


class KrakenAPIError(Exception):
    pass


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    since: datetime | None = None,
    limit: int | None = None,
) -> list[Bar]:
    """Fetch OHLCV bars from Kraken REST API.

    Args:
        symbol: Our symbol format, e.g. "BTC/USD"
        timeframe: One of "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"
        since: Fetch bars starting from this time (UTC)
        limit: Max bars to return (Kraken returns up to 720 per request)

    Returns:
        List of Bar objects sorted by timestamp ascending.
    """
    kraken_pair = SYMBOL_TO_KRAKEN.get(symbol, symbol.replace("/", ""))
    interval = TIMEFRAME_MINUTES.get(timeframe)
    if interval is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    params: dict = {"pair": kraken_pair, "interval": interval}
    if since is not None:
        params["since"] = int(since.timestamp())

    resp = requests.get(f"{BASE_URL}/OHLC", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("error"):
        raise KrakenAPIError(f"Kraken API error: {data['error']}")

    result = data.get("result", {})
    # Result keys are the Kraken pair name; find the right one (not "last")
    bars_data = None
    for key, value in result.items():
        if key != "last" and isinstance(value, list):
            bars_data = value
            break

    if bars_data is None:
        return []

    bars = []
    for entry in bars_data:
        # Kraken OHLC format: [time, open, high, low, close, vwap, volume, count]
        ts = datetime.fromtimestamp(entry[0], tz=timezone.utc)
        bars.append(Bar(
            instrument_symbol=symbol,
            timestamp=ts,
            open=Decimal(entry[1]),
            high=Decimal(entry[2]),
            low=Decimal(entry[3]),
            close=Decimal(entry[4]),
            volume=Decimal(entry[6]),
            trades=int(entry[7]),
            vwap=Decimal(entry[5]) if entry[5] != "0.00000" else None,
        ))

    bars.sort(key=lambda b: b.timestamp)
    if limit is not None:
        bars = bars[:limit]
    return bars


def backfill_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    start: datetime | None = None,
    end: datetime | None = None,
    rate_limit_sleep: float = 1.0,
) -> list[Bar]:
    """Backfill historical OHLCV data by paginating through Kraken API.

    Args:
        symbol: Our symbol format, e.g. "BTC/USD"
        timeframe: Bar timeframe
        start: Start of backfill range (UTC)
        end: End of backfill range (UTC). Defaults to now.

    Returns:
        All bars in the requested range, deduplicated and sorted.
    """
    if end is None:
        end = datetime.now(timezone.utc)

    all_bars: list[Bar] = []
    since = start

    while True:
        batch = fetch_ohlcv(symbol, timeframe, since=since)
        if not batch:
            break

        # Filter to requested range
        for bar in batch:
            if end is not None and bar.timestamp > end:
                continue
            all_bars.append(bar)

        # Kraken returns bars from `since` onward; advance past last bar
        last_ts = batch[-1].timestamp
        if since is not None and last_ts <= since:
            break  # No progress, we've exhausted available data
        if end is not None and last_ts >= end:
            break

        since = last_ts
        time.sleep(rate_limit_sleep)

    # Deduplicate by timestamp
    seen = set()
    unique_bars = []
    for bar in all_bars:
        if bar.timestamp not in seen:
            seen.add(bar.timestamp)
            unique_bars.append(bar)

    unique_bars.sort(key=lambda b: b.timestamp)
    return unique_bars
