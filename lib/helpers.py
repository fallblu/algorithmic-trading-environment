"""Shared helpers for processes and workflows."""

from pathlib import Path


def parse_symbols(symbols: str) -> list[str]:
    """Parse comma-separated symbol string into a list."""
    return [s.strip() for s in symbols.split(",")]


def market_data_dir(env_path) -> Path:
    """Standard market data directory for the environment."""
    return Path(env_path) / ".persistra" / "market_data"


def make_store(env_path):
    """Create a MarketDataStore at the standard location."""
    from data.store import MarketDataStore
    return MarketDataStore(market_data_dir(env_path))


def require_data(env_path, exchange: str, symbols: list[str], timeframe: str):
    """Raise RuntimeError if market data is missing for any symbol."""
    store = make_store(env_path)
    missing = [s for s in symbols if not store.has_data(exchange, s, timeframe)]
    if missing:
        syms = ",".join(missing)
        raise RuntimeError(
            f"Missing market data for {missing} ({timeframe} on {exchange}). "
            f"Run: persistra process run data_ingestor "
            f"-p symbols={syms} -p timeframe={timeframe} -p exchange={exchange}"
        )


from constants import TIMEFRAME_PERIODS_PER_YEAR, periods_per_year  # noqa: F401
