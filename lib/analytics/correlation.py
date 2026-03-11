"""Correlation analysis — cross-asset and rolling correlation."""

import logging

import numpy as np
import pandas as pd

from analytics.utils import log_returns

log = logging.getLogger(__name__)


def correlation_matrix(symbol_bars_dict: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Cross-asset return correlation matrix.

    Args:
        symbol_bars_dict: Dict of symbol -> DataFrame with 'close' column.

    Returns:
        DataFrame correlation matrix.
    """
    returns_dict = {}
    for symbol, df in symbol_bars_dict.items():
        closes = df["close"].values.astype(float)
        rets = log_returns(closes)
        if len(rets) > 0:
            returns_dict[symbol] = pd.Series(rets)

    if not returns_dict:
        log.debug("No valid return series for correlation matrix")
        return pd.DataFrame()

    returns_df = pd.DataFrame(returns_dict)
    return returns_df.corr()


def rolling_correlation(
    bars_a: pd.DataFrame,
    bars_b: pd.DataFrame,
    window: int = 30,
) -> np.ndarray:
    """Time-varying correlation between two assets.

    Uses vectorized pandas rolling correlation for performance.

    Args:
        bars_a, bars_b: DataFrames with 'close' column.
        window: Rolling window size.

    Returns:
        Array of rolling correlations.
    """
    closes_a = bars_a["close"].values.astype(float)
    closes_b = bars_b["close"].values.astype(float)

    n = min(len(closes_a), len(closes_b))
    if n < window + 1:
        log.debug("Insufficient data (%d bars) for rolling correlation window %d", n, window)
        return np.array([])

    returns_a = pd.Series(np.diff(np.log(closes_a[:n])))
    returns_b = pd.Series(np.diff(np.log(closes_b[:n])))

    # Vectorized rolling correlation (replaces explicit loop)
    result = returns_a.rolling(window).corr(returns_b).dropna().values

    # Replace NaN with 0.0
    result = np.where(np.isfinite(result), result, 0.0)

    return result
