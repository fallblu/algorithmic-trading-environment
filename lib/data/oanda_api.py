"""OANDA REST API client — fetch candle data."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from models.bar import Bar

log = logging.getLogger(__name__)

BASE_URL = "https://api-fxpractice.oanda.com/v3"

# OANDA uses underscore-separated symbols
SYMBOL_MAP = {
    "EUR/USD": "EUR_USD",
    "GBP/USD": "GBP_USD",
    "USD/JPY": "USD_JPY",
    "AUD/USD": "AUD_USD",
    "USD/CAD": "USD_CAD",
    "NZD/USD": "NZD_USD",
    "USD/CHF": "USD_CHF",
    "EUR/GBP": "EUR_GBP",
    "EUR/JPY": "EUR_JPY",
    "GBP/JPY": "GBP_JPY",
}

GRANULARITY_MAP = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "4h": "H4",
    "1d": "D",
    "1w": "W",
}


def resolve_symbol(symbol: str) -> str:
    """Convert normalized symbol to OANDA API format."""
    return SYMBOL_MAP.get(symbol, symbol.replace("/", "_"))


def fetch_candles(
    symbol: str,
    timeframe: str = "1h",
    api_key: str = "",
    account_id: str = "",
    since: datetime | None = None,
    count: int = 5000,
) -> list[Bar]:
    """Fetch candle data from OANDA REST API.

    Returns up to `count` candles (max 5000 per call).
    """
    instrument = resolve_symbol(symbol)
    granularity = GRANULARITY_MAP.get(timeframe, "H1")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    params: dict = {
        "granularity": granularity,
        "count": min(count, 5000),
        "price": "M",  # Mid prices
    }
    if since is not None:
        params["from"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        params.pop("count", None)

    url = f"{BASE_URL}/instruments/{instrument}/candles"

    with httpx.Client(timeout=30) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    bars: list[Bar] = []
    for candle in data.get("candles", []):
        if not candle.get("complete", True):
            continue
        mid = candle["mid"]
        ts = datetime.fromisoformat(candle["time"].replace("Z", "+00:00"))
        bars.append(Bar(
            symbol=symbol,
            timestamp=ts,
            open=float(mid["o"]),
            high=float(mid["h"]),
            low=float(mid["l"]),
            close=float(mid["c"]),
            volume=float(candle.get("volume", 0)),
        ))

    return bars


def backfill_candles(
    symbol: str,
    timeframe: str = "1h",
    api_key: str = "",
    account_id: str = "",
    start: datetime | None = None,
    end: datetime | None = None,
    rate_limit_sleep: float = 0.5,
) -> list[Bar]:
    """Backfill candle data with pagination."""
    all_bars: list[Bar] = []
    since = start

    while True:
        batch = fetch_candles(symbol, timeframe, api_key, account_id, since)
        if not batch:
            break

        if end is not None:
            batch = [b for b in batch if b.timestamp <= end]

        all_bars.extend(batch)
        log.info("Fetched %d candles for %s (total: %d)", len(batch), symbol, len(all_bars))

        if len(batch) < 4900:
            break

        since = batch[-1].timestamp
        time.sleep(rate_limit_sleep)

    # Deduplicate
    seen: set[datetime] = set()
    unique: list[Bar] = []
    for bar in all_bars:
        if bar.timestamp not in seen:
            seen.add(bar.timestamp)
            unique.append(bar)

    return sorted(unique, key=lambda b: b.timestamp)
