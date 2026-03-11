"""Kraken Futures REST client for OHLCV and funding rate data."""

import time
from datetime import datetime, timezone
from decimal import Decimal

import requests

from models.bar import Bar, FundingRate

BASE_URL = "https://futures.kraken.com"

# Symbol mapping: our format -> Kraken Futures format
SYMBOL_TO_KRAKEN_FUTURES = {
    "BTC-PERP": "PF_XBTUSD",
    "ETH-PERP": "PF_ETHUSD",
    "SOL-PERP": "PF_SOLUSD",
    "XRP-PERP": "PF_XRPUSD",
    "DOGE-PERP": "PF_DOGEUSD",
    "ADA-PERP": "PF_ADAUSD",
    "AVAX-PERP": "PF_AVAXUSD",
    "DOT-PERP": "PF_DOTUSD",
    "LINK-PERP": "PF_LINKUSD",
}

KRAKEN_TO_SYMBOL_FUTURES = {v: k for k, v in SYMBOL_TO_KRAKEN_FUTURES.items()}

# Timeframe mapping to Kraken Futures chart resolution
TIMEFRAME_RESOLUTION = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}


class KrakenFuturesAPIError(Exception):
    pass


def fetch_ohlcv_futures(
    symbol: str,
    timeframe: str = "1h",
    since: datetime | None = None,
    limit: int | None = None,
) -> list[Bar]:
    """Fetch OHLCV candle data from Kraken Futures.

    Uses /api/charts/v1/trade/{symbol}/{resolution} endpoint.
    """
    kraken_symbol = SYMBOL_TO_KRAKEN_FUTURES.get(symbol, symbol)
    resolution = TIMEFRAME_RESOLUTION.get(timeframe)
    if resolution is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    url = f"{BASE_URL}/api/charts/v1/trade/{kraken_symbol}/{resolution}"
    params = {}
    if since is not None:
        params["from"] = int(since.timestamp())

    resp = requests.get(url, params=params, timeout=30)

    retry_after = resp.headers.get("Retry-After")
    if resp.status_code == 429 and retry_after:
        time.sleep(int(retry_after))
        resp = requests.get(url, params=params, timeout=30)

    resp.raise_for_status()
    data = resp.json()

    candles = data.get("candles", [])
    bars = []
    for candle in candles:
        ts = datetime.fromtimestamp(candle["time"] / 1000, tz=timezone.utc)
        bars.append(Bar(
            instrument_symbol=symbol,
            timestamp=ts,
            open=Decimal(str(candle["open"])),
            high=Decimal(str(candle["high"])),
            low=Decimal(str(candle["low"])),
            close=Decimal(str(candle["close"])),
            volume=Decimal(str(candle.get("volume", 0))),
        ))

    bars.sort(key=lambda b: b.timestamp)
    if limit is not None:
        bars = bars[:limit]
    return bars


def backfill_ohlcv_futures(
    symbol: str,
    timeframe: str = "1h",
    start: datetime | None = None,
    end: datetime | None = None,
    rate_limit_sleep: float = 1.0,
) -> list[Bar]:
    """Paginated historical backfill for Kraken Futures OHLCV."""
    if end is None:
        end = datetime.now(timezone.utc)

    all_bars: list[Bar] = []
    since = start

    while True:
        batch = fetch_ohlcv_futures(symbol, timeframe, since=since)
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


def fetch_funding_rate(symbol: str) -> FundingRate | None:
    """Fetch current funding rate from Kraken Futures tickers endpoint."""
    kraken_symbol = SYMBOL_TO_KRAKEN_FUTURES.get(symbol, symbol)
    url = f"{BASE_URL}/derivatives/api/v3/tickers"

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("result") != "success":
        raise KrakenFuturesAPIError(f"Kraken Futures API error: {data}")

    for ticker in data.get("tickers", []):
        if ticker.get("symbol") == kraken_symbol:
            rate = Decimal(str(ticker.get("fundingRate", 0)))
            next_time = datetime.fromtimestamp(
                ticker.get("nextFundingRateTime", 0) / 1000,
                tz=timezone.utc,
            )
            return FundingRate(
                instrument_symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                rate=rate,
                next_funding_time=next_time,
            )

    return None


def fetch_instruments() -> list[dict]:
    """Fetch available perpetual contracts from Kraken Futures."""
    url = f"{BASE_URL}/derivatives/api/v3/instruments"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("result") != "success":
        raise KrakenFuturesAPIError(f"Kraken Futures API error: {data}")

    instruments = []
    for inst in data.get("instruments", []):
        if inst.get("type") == "flexible_futures":
            our_symbol = KRAKEN_TO_SYMBOL_FUTURES.get(inst["symbol"], inst["symbol"])
            instruments.append({
                "symbol": our_symbol,
                "kraken_symbol": inst["symbol"],
                "type": inst.get("type"),
                "tick_size": inst.get("tickSize"),
                "max_leverage": inst.get("maxLeverage", 50),
            })

    return instruments
