"""Shared constants — timeframe mappings, execution modes, and other project-wide values."""

from enum import Enum


class ExecutionMode(Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


# Timeframe to minutes mapping (used for warmup calculations, API calls, etc.)
TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}


# Annualization factors for performance metrics
TIMEFRAME_PERIODS_PER_YEAR: dict[str, float] = {
    "1m": 525960,
    "5m": 105192,
    "15m": 35064,
    "30m": 17532,
    "1h": 8766,
    "4h": 2191.5,
    "1d": 365.25,
    "1w": 52.18,
}


# OANDA granularity mapping (our format -> OANDA API format)
OANDA_GRANULARITY_MAP: dict[str, str] = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "4h": "H4",
    "1d": "D",
    "1w": "W",
}


def timeframe_to_minutes(timeframe: str) -> int:
    """Get the number of minutes in a timeframe.

    Raises:
        ValueError: If the timeframe is not recognized.
    """
    minutes = TIMEFRAME_MINUTES.get(timeframe)
    if minutes is None:
        raise ValueError(
            f"Unsupported timeframe: {timeframe!r}. "
            f"Available: {list(TIMEFRAME_MINUTES.keys())}"
        )
    return minutes


def periods_per_year(timeframe: str) -> float:
    """Return annualization factor for the given bar timeframe."""
    return TIMEFRAME_PERIODS_PER_YEAR.get(timeframe, 8766)


def normalize_symbol(symbol: str) -> str:
    """Convert 'EUR/USD' to 'EUR_USD' for filesystem-safe paths."""
    return symbol.replace("/", "_")


def denormalize_symbol(symbol: str) -> str:
    """Convert 'EUR_USD' back to 'EUR/USD'."""
    return symbol.replace("_", "/")
