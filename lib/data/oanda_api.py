"""OANDA v20 REST client for forex OHLCV data."""

import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import requests

from constants import OANDA_GRANULARITY_MAP as GRANULARITY_MAP, normalize_symbol, denormalize_symbol
from exceptions import OandaAPIError
from models.bar import Bar

log = logging.getLogger(__name__)


def _get_base_url() -> str:
    """Get OANDA API base URL based on environment."""
    environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
    if environment == "live":
        return "https://api-fxtrade.oanda.com"
    return "https://api-fxpractice.oanda.com"


def _get_headers() -> dict:
    """Get OANDA authorization headers."""
    token = os.environ.get("OANDA_API_TOKEN")
    if not token:
        raise OandaAPIError("OANDA_API_TOKEN environment variable must be set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _get_account_id() -> str:
    """Get OANDA account ID."""
    account_id = os.environ.get("OANDA_ACCOUNT_ID")
    if not account_id:
        raise OandaAPIError("OANDA_ACCOUNT_ID environment variable must be set")
    return account_id


def fetch_candles(
    symbol: str,
    timeframe: str = "1h",
    since: datetime | None = None,
    limit: int | None = None,
    count: int = 5000,
) -> list[Bar]:
    """Fetch OHLCV candles from OANDA v20 REST API.

    Args:
        symbol: Our symbol format, e.g. "EUR/USD"
        timeframe: One of "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"
        since: Fetch candles starting from this time (UTC)
        limit: Max bars to return
        count: Number of candles per request (max 5000)

    Returns:
        List of Bar objects sorted by timestamp ascending.
    """
    oanda_instrument = normalize_symbol(symbol)
    granularity = GRANULARITY_MAP.get(timeframe)
    if granularity is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    base_url = _get_base_url()
    headers = _get_headers()

    params: dict = {
        "granularity": granularity,
        "price": "M",  # Mid prices
        "count": str(min(count, 5000)),
    }
    if since is not None:
        params["from"] = since.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")

    url = f"{base_url}/v3/instruments/{oanda_instrument}/candles"
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    candles = data.get("candles", [])
    bars = []
    for candle in candles:
        if not candle.get("complete", True):
            continue  # Skip incomplete candles

        mid = candle.get("mid", {})
        ts = datetime.fromisoformat(candle["time"].replace("Z", "+00:00"))

        bars.append(Bar(
            instrument_symbol=symbol,
            timestamp=ts,
            open=Decimal(mid["o"]),
            high=Decimal(mid["h"]),
            low=Decimal(mid["l"]),
            close=Decimal(mid["c"]),
            volume=Decimal(str(candle.get("volume", 0))),
        ))

    bars.sort(key=lambda b: b.timestamp)
    if limit is not None:
        bars = bars[:limit]
    return bars


def backfill_candles(
    symbol: str,
    timeframe: str = "1h",
    start: datetime | None = None,
    end: datetime | None = None,
    rate_limit_sleep: float = 0.5,
) -> list[Bar]:
    """Paginated historical backfill for OANDA candles."""
    if end is None:
        end = datetime.now(timezone.utc)

    all_bars: list[Bar] = []
    since = start

    while True:
        batch = fetch_candles(symbol, timeframe, since=since)
        if not batch:
            break

        for bar in batch:
            if end is not None and bar.timestamp > end:
                continue
            all_bars.append(bar)

        last_ts = batch[-1].timestamp
        if since is not None and last_ts <= since:
            break
        if end is not None and last_ts >= end:
            break

        since = last_ts
        time.sleep(rate_limit_sleep)

    # Deduplicate
    seen = set()
    unique = []
    for bar in all_bars:
        if bar.timestamp not in seen:
            seen.add(bar.timestamp)
            unique.append(bar)

    unique.sort(key=lambda b: b.timestamp)
    return unique


def fetch_instruments() -> list[dict]:
    """Fetch available forex pairs from OANDA."""
    base_url = _get_base_url()
    headers = _get_headers()
    account_id = _get_account_id()

    url = f"{base_url}/v3/accounts/{account_id}/instruments"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    instruments = []
    for inst in data.get("instruments", []):
        instruments.append({
            "symbol": denormalize_symbol(inst["name"]),
            "oanda_name": inst["name"],
            "type": inst.get("type"),
            "pip_location": inst.get("pipLocation"),
            "display_precision": inst.get("displayPrecision"),
        })

    return instruments


def fetch_pricing(symbols: list[str]) -> dict[str, dict]:
    """Fetch current bid/ask from OANDA pricing endpoint."""
    base_url = _get_base_url()
    headers = _get_headers()
    account_id = _get_account_id()

    oanda_instruments = ",".join(normalize_symbol(s) for s in symbols)
    url = f"{base_url}/v3/accounts/{account_id}/pricing"
    params = {"instruments": oanda_instruments}

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    result = {}
    for price in data.get("prices", []):
        our_symbol = denormalize_symbol(price["instrument"])
        bids = price.get("bids", [])
        asks = price.get("asks", [])
        bid = Decimal(bids[0]["price"]) if bids else Decimal("0")
        ask = Decimal(asks[0]["price"]) if asks else Decimal("0")
        result[our_symbol] = {
            "bid": bid,
            "ask": ask,
            "mid": (bid + ask) / 2,
            "spread": ask - bid,
        }

    return result
