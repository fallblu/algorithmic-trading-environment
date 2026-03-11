"""Data ingestor process — fetches and stores OHLCV market data."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from persistra import process

log = logging.getLogger(__name__)


@process("job")
def run(
    env,
    symbols: str = "BTC/USD",
    timeframe: str = "1h",
    backfill_days: int = 365,
    exchange: str = "kraken",
):
    """Fetch OHLCV bars from an exchange and store in Parquet.

    Accepts comma-separated symbols (e.g. "BTC/USD,ETH/USD").
    Supports exchanges: kraken, oanda.
    """
    from data.store import MarketDataStore
    from helpers import parse_symbols, market_data_dir

    data_dir = market_data_dir(env.path)
    store = MarketDataStore(data_dir)

    symbol_list = parse_symbols(symbols)

    # Select the correct backfill function based on exchange
    if exchange == "kraken":
        from data.kraken_api import backfill_ohlcv
        backfill_fn = backfill_ohlcv
    elif exchange == "oanda":
        from data.oanda_api import backfill_candles
        backfill_fn = backfill_candles
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")

    for symbol in symbol_list:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=backfill_days)

        # Check existing data
        date_range = store.get_date_range(exchange, symbol, timeframe)
        if date_range is not None:
            existing_start, existing_end = date_range
            log.info(
                "Existing data for %s %s: %s to %s",
                symbol, timeframe, existing_start, existing_end,
            )
            start = existing_end
            log.info("Fetching new data from %s to %s", start, end)
        else:
            log.info("No existing data. Backfilling %d days of %s %s",
                     backfill_days, symbol, timeframe)

        bars = backfill_fn(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
        )

        if bars:
            store.write_bars(bars, exchange=exchange, timeframe=timeframe)
            log.info("Stored %d bars for %s %s", len(bars), symbol, timeframe)

            ns = env.state.ns("data")
            ns.set("last_update", datetime.now(timezone.utc).isoformat())
            ns.set(f"{symbol.replace('/', '_')}_{timeframe}_bars", len(bars))
        else:
            log.info("No new bars fetched for %s %s", symbol, timeframe)
