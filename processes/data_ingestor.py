"""Data ingestor — fetch OHLCV data from exchanges and store as Parquet."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from persistra import process

log = logging.getLogger(__name__)


@process("job", description="Fetch and store OHLCV market data")
def run(
    env,
    symbols: str = "BTC/USD",
    exchange: str = "kraken",
    timeframe: str = "1h",
    backfill_days: str = "365",
    api_key: str = "",
    account_id: str = "",
) -> None:
    from data.store import MarketDataStore

    store = MarketDataStore(Path(env.path) / ".persistra" / "market_data")
    symbol_list = [s.strip() for s in symbols.split(",")]
    days = int(backfill_days)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    for symbol in symbol_list:
        log.info("Fetching %s %s from %s (%d days)", symbol, timeframe, exchange, days)

        if exchange == "kraken":
            from data.kraken_api import backfill_ohlcv
            bars = backfill_ohlcv(symbol, timeframe, start, end)
        elif exchange == "oanda":
            from data.oanda_api import backfill_candles
            bars = backfill_candles(symbol, timeframe, api_key, account_id, start, end)
        else:
            log.error("Unknown exchange: %s", exchange)
            continue

        if bars:
            count = store.write_bars(bars, exchange, timeframe)
            log.info("Stored %d bars for %s/%s/%s", count, exchange, symbol, timeframe)
        else:
            log.warning("No bars returned for %s from %s", symbol, exchange)
