"""Analytics utilities — shared helpers for returns computation and data extraction."""

from typing import NamedTuple

import numpy as np
import pandas as pd


class OHLCVArrays(NamedTuple):
    """Arrays extracted from a bars DataFrame."""
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray


def log_returns(closes: np.ndarray, period: int = 1) -> np.ndarray:
    """Compute log returns from a close price array.

    Args:
        closes: Array of close prices (float).
        period: Return period (1 = bar-to-bar).

    Returns:
        Array of log returns, filtered for finite values.
    """
    if len(closes) < period + 1:
        return np.array([])
    returns = np.diff(np.log(closes[::period]))
    return returns[np.isfinite(returns)]


def bars_to_arrays(bars_df: pd.DataFrame) -> OHLCVArrays:
    """Extract OHLCV columns from a DataFrame as float arrays.

    Args:
        bars_df: DataFrame with columns [open, high, low, close, volume].

    Returns:
        OHLCVArrays named tuple.
    """
    return OHLCVArrays(
        opens=bars_df["open"].values.astype(float),
        highs=bars_df["high"].values.astype(float),
        lows=bars_df["low"].values.astype(float),
        closes=bars_df["close"].values.astype(float),
        volumes=bars_df["volume"].values.astype(float),
    )
