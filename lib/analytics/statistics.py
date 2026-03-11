"""Statistical analysis — return distributions, volatility, autocorrelation, tail risk."""

import logging
from math import sqrt

import numpy as np
import pandas as pd

from analytics.utils import log_returns

log = logging.getLogger(__name__)


def return_distribution(bars_df: pd.DataFrame, period: int = 1) -> dict:
    """Compute return series statistics, fit distributions, test for normality.

    Args:
        bars_df: DataFrame with 'close' column.
        period: Return period (1 = bar-to-bar).

    Returns:
        Dict with mean, std, skewness, kurtosis, jarque_bera p-value.
    """
    from scipy import stats

    closes = bars_df["close"].values.astype(float)
    returns = log_returns(closes, period)

    if len(returns) < 4:
        log.debug("Insufficient returns (%d) for distribution analysis", len(returns))
        return {"mean": 0.0, "std": 0.0, "skewness": 0.0, "kurtosis": 0.0, "jb_pvalue": 1.0}

    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns))
    jb_stat, jb_pvalue = stats.jarque_bera(returns)

    return {
        "mean": mean,
        "std": std,
        "skewness": skew,
        "kurtosis": kurt,
        "jb_statistic": float(jb_stat),
        "jb_pvalue": float(jb_pvalue),
        "n_returns": len(returns),
    }


def volatility_analysis(bars_df: pd.DataFrame) -> dict:
    """Compute realized volatility and rolling vol at multiple windows.

    Args:
        bars_df: DataFrame with 'close' column.

    Returns:
        Dict with realized_vol, rolling vols at various windows, vol_of_vol.
    """
    closes = bars_df["close"].values.astype(float)
    returns = log_returns(closes)

    if len(returns) < 2:
        log.debug("Insufficient returns for volatility analysis")
        return {"realized_vol": 0.0, "rolling_vols": {}, "vol_of_vol": 0.0}

    realized_vol = float(np.std(returns, ddof=1) * sqrt(252))

    rolling_vols = {}
    for window in [5, 10, 21, 63]:
        if len(returns) >= window:
            roll = pd.Series(returns).rolling(window).std() * sqrt(252)
            rolling_vols[f"vol_{window}"] = roll.dropna().tolist()

    # Vol-of-vol
    vol_of_vol = 0.0
    if "vol_21" in rolling_vols and len(rolling_vols["vol_21"]) > 5:
        vol_of_vol = float(np.std(rolling_vols["vol_21"], ddof=1))

    return {
        "realized_vol": realized_vol,
        "rolling_vols": rolling_vols,
        "vol_of_vol": vol_of_vol,
    }


def autocorrelation_analysis(bars_df: pd.DataFrame, max_lag: int = 20) -> dict:
    """ACF/PACF of returns and squared returns.

    Args:
        bars_df: DataFrame with 'close' column.
        max_lag: Maximum lag.

    Returns:
        Dict with acf, pacf for returns and squared returns.
    """
    closes = bars_df["close"].values.astype(float)
    returns = log_returns(closes)

    if len(returns) < max_lag + 1:
        log.debug("Insufficient returns (%d) for autocorrelation at lag %d", len(returns), max_lag)
        return {"acf_returns": [], "acf_squared": []}

    # ACF
    mean = np.mean(returns)
    var = np.var(returns)
    acf = []
    for lag in range(1, max_lag + 1):
        if var == 0:
            acf.append(0.0)
        else:
            cov = np.mean((returns[lag:] - mean) * (returns[:-lag] - mean))
            acf.append(float(cov / var))

    # ACF of squared returns (volatility clustering)
    sq_returns = returns ** 2
    sq_mean = np.mean(sq_returns)
    sq_var = np.var(sq_returns)
    acf_sq = []
    for lag in range(1, max_lag + 1):
        if sq_var == 0:
            acf_sq.append(0.0)
        else:
            cov = np.mean((sq_returns[lag:] - sq_mean) * (sq_returns[:-lag] - sq_mean))
            acf_sq.append(float(cov / sq_var))

    return {
        "acf_returns": acf,
        "acf_squared": acf_sq,
    }


def tail_risk_analysis(bars_df: pd.DataFrame) -> dict:
    """VaR, CVaR at multiple confidence levels.

    Args:
        bars_df: DataFrame with 'close' column.

    Returns:
        Dict with VaR and CVaR at 95% and 99% confidence.
    """
    closes = bars_df["close"].values.astype(float)
    returns = log_returns(closes)

    if len(returns) < 5:
        log.debug("Insufficient returns for tail risk analysis")
        return {"var_95": 0.0, "cvar_95": 0.0, "var_99": 0.0, "cvar_99": 0.0}

    sorted_returns = np.sort(returns)

    var_95 = float(np.percentile(sorted_returns, 5))
    var_99 = float(np.percentile(sorted_returns, 1))

    cvar_95 = float(np.mean(sorted_returns[sorted_returns <= var_95])) if any(sorted_returns <= var_95) else var_95
    cvar_99 = float(np.mean(sorted_returns[sorted_returns <= var_99])) if any(sorted_returns <= var_99) else var_99

    return {
        "var_95": var_95,
        "cvar_95": cvar_95,
        "var_99": var_99,
        "cvar_99": cvar_99,
    }
