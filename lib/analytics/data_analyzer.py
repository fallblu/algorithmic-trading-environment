"""Data analyzer — statistical analysis and technical scanning on stored market data."""

import logging
from math import sqrt

import numpy as np
import pandas as pd

from analytics.indicators import (
    atr,
    bollinger_bands,
    ema,
    macd,
    obv,
    rsi,
    sma,
    stochastic,
)

log = logging.getLogger(__name__)


# ── Statistical Analysis ────────────────────────────────────────────


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
    if len(closes) < period + 2:
        return {"mean": 0.0, "std": 0.0, "skewness": 0.0, "kurtosis": 0.0, "jb_pvalue": 1.0}

    returns = np.diff(np.log(closes[::period]))
    returns = returns[np.isfinite(returns)]

    if len(returns) < 4:
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
    if len(closes) < 3:
        return {"realized_vol": 0.0, "rolling_vols": {}, "vol_of_vol": 0.0}

    returns = np.diff(np.log(closes))
    returns = returns[np.isfinite(returns)]

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
        if len(closes) > 1:
            returns_dict[symbol] = pd.Series(np.diff(np.log(closes)))

    if not returns_dict:
        return pd.DataFrame()

    returns_df = pd.DataFrame(returns_dict)
    return returns_df.corr()


def rolling_correlation(
    bars_a: pd.DataFrame,
    bars_b: pd.DataFrame,
    window: int = 30,
) -> np.ndarray:
    """Time-varying correlation between two assets.

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
        return np.array([])

    returns_a = np.diff(np.log(closes_a[:n]))
    returns_b = np.diff(np.log(closes_b[:n]))

    result = np.empty(len(returns_a) - window + 1)
    for i in range(len(result)):
        ra = returns_a[i : i + window]
        rb = returns_b[i : i + window]
        corr = np.corrcoef(ra, rb)[0, 1]
        result[i] = corr if np.isfinite(corr) else 0.0

    return result


def regime_detection(bars_df: pd.DataFrame, n_regimes: int = 2) -> dict:
    """Hidden Markov Model regime detection.

    Args:
        bars_df: DataFrame with 'close' column.
        n_regimes: Number of regimes (states).

    Returns:
        Dict with regime labels, transition matrix, per-regime statistics.
    """
    from hmmlearn.hmm import GaussianHMM

    closes = bars_df["close"].values.astype(float)
    if len(closes) < 20:
        return {"regimes": [], "transition_matrix": [], "regime_stats": {}}

    returns = np.diff(np.log(closes))
    returns = returns[np.isfinite(returns)]

    if len(returns) < 20:
        return {"regimes": [], "transition_matrix": [], "regime_stats": {}}

    X = returns.reshape(-1, 1)
    model = GaussianHMM(n_components=n_regimes, covariance_type="full", n_iter=100)
    model.fit(X)
    labels = model.predict(X)

    # Per-regime statistics
    regime_stats = {}
    for r in range(n_regimes):
        mask = labels == r
        r_returns = returns[mask]
        if len(r_returns) > 0:
            regime_stats[f"regime_{r}"] = {
                "mean": float(np.mean(r_returns)),
                "std": float(np.std(r_returns, ddof=1)) if len(r_returns) > 1 else 0.0,
                "count": int(np.sum(mask)),
                "fraction": float(np.mean(mask)),
            }

    return {
        "regimes": labels.tolist(),
        "transition_matrix": model.transmat_.tolist(),
        "regime_stats": regime_stats,
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
    if len(closes) < max_lag + 2:
        return {"acf_returns": [], "acf_squared": []}

    returns = np.diff(np.log(closes))
    returns = returns[np.isfinite(returns)]

    if len(returns) < max_lag + 1:
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
    if len(closes) < 3:
        return {"var_95": 0.0, "cvar_95": 0.0, "var_99": 0.0, "cvar_99": 0.0}

    returns = np.diff(np.log(closes))
    returns = returns[np.isfinite(returns)]

    if len(returns) < 5:
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


# ── Technical Scanning ──────────────────────────────────────────────


def scan_indicators(bars_df: pd.DataFrame, indicators: list[str] | None = None) -> pd.DataFrame:
    """Compute a batch of technical indicators over a bar series.

    Args:
        bars_df: DataFrame with columns [open, high, low, close, volume].
        indicators: List of indicator names to compute. None = all.

    Returns:
        DataFrame with indicator columns aligned to bar timestamps.
    """
    closes = bars_df["close"].values.astype(float)
    highs = bars_df["high"].values.astype(float)
    lows = bars_df["low"].values.astype(float)
    volumes = bars_df["volume"].values.astype(float)
    n = len(closes)

    if indicators is None:
        indicators = [
            "sma_10", "sma_30", "ema_10", "ema_30",
            "rsi_14", "macd", "bollinger", "atr_14",
            "stochastic", "obv",
        ]

    result = pd.DataFrame(index=bars_df.index if hasattr(bars_df, 'index') else range(n))

    def _align(arr, n_total):
        """Right-align a shorter array to the total length, padding NaN on left."""
        padded = np.full(n_total, np.nan)
        if len(arr) > 0:
            padded[n_total - len(arr):] = arr
        return padded

    for ind in indicators:
        if ind.startswith("sma_"):
            p = int(ind.split("_")[1])
            result[ind] = _align(sma(closes, p), n)
        elif ind.startswith("ema_"):
            p = int(ind.split("_")[1])
            result[ind] = _align(ema(closes, p), n)
        elif ind.startswith("rsi"):
            p = int(ind.split("_")[1]) if "_" in ind else 14
            result[ind] = _align(rsi(closes, p), n)
        elif ind == "macd":
            macd_line, signal_line, hist = macd(closes)
            result["macd_line"] = _align(macd_line, n)
            result["macd_signal"] = _align(signal_line, n)
            result["macd_histogram"] = _align(hist, n)
        elif ind == "bollinger":
            upper, middle, lower = bollinger_bands(closes)
            result["bb_upper"] = _align(upper, n)
            result["bb_middle"] = _align(middle, n)
            result["bb_lower"] = _align(lower, n)
        elif ind.startswith("atr"):
            p = int(ind.split("_")[1]) if "_" in ind else 14
            result[ind] = _align(atr(highs, lows, closes, p), n)
        elif ind == "stochastic":
            k, d = stochastic(highs, lows, closes)
            result["stoch_k"] = _align(k, n)
            result["stoch_d"] = _align(d, n)
        elif ind == "obv":
            result["obv"] = obv(closes, volumes)

    return result


def scan_signals(bars_df: pd.DataFrame, signal_configs: list[dict]) -> list[dict]:
    """Detect buy/sell signal events from indicator combinations.

    Args:
        bars_df: DataFrame with [open, high, low, close, volume].
        signal_configs: List of signal definitions, e.g.:
            [{"type": "crossover", "fast": "ema_10", "slow": "sma_30"}]

    Returns:
        List of signal events: [{timestamp, signal, strength, ...}]
    """
    indicators_needed = set()
    for cfg in signal_configs:
        if cfg["type"] == "crossover":
            indicators_needed.add(cfg["fast"])
            indicators_needed.add(cfg["slow"])

    ind_df = scan_indicators(bars_df, list(indicators_needed))
    signals = []

    timestamps = bars_df.index if hasattr(bars_df, 'index') else range(len(bars_df))

    for cfg in signal_configs:
        if cfg["type"] == "crossover":
            fast_name = cfg["fast"]
            slow_name = cfg["slow"]
            if fast_name not in ind_df.columns or slow_name not in ind_df.columns:
                continue

            fast_vals = ind_df[fast_name].values
            slow_vals = ind_df[slow_name].values

            for i in range(1, len(fast_vals)):
                if np.isnan(fast_vals[i]) or np.isnan(slow_vals[i]):
                    continue
                if np.isnan(fast_vals[i - 1]) or np.isnan(slow_vals[i - 1]):
                    continue

                prev_above = fast_vals[i - 1] > slow_vals[i - 1]
                curr_above = fast_vals[i] > slow_vals[i]

                if curr_above and not prev_above:
                    signals.append({
                        "index": i,
                        "signal": "BUY",
                        "type": "crossover",
                        "strength": abs(fast_vals[i] - slow_vals[i]),
                        "fast": fast_name,
                        "slow": slow_name,
                    })
                elif not curr_above and prev_above:
                    signals.append({
                        "index": i,
                        "signal": "SELL",
                        "type": "crossover",
                        "strength": abs(fast_vals[i] - slow_vals[i]),
                        "fast": fast_name,
                        "slow": slow_name,
                    })

    return signals


def scan_patterns(bars_df: pd.DataFrame) -> list[dict]:
    """Detect candlestick patterns (doji, hammer, engulfing).

    Args:
        bars_df: DataFrame with [open, high, low, close].

    Returns:
        List of pattern events.
    """
    opens = bars_df["open"].values.astype(float)
    highs = bars_df["high"].values.astype(float)
    lows = bars_df["low"].values.astype(float)
    closes = bars_df["close"].values.astype(float)

    patterns = []

    for i in range(len(opens)):
        body = abs(closes[i] - opens[i])
        full_range = highs[i] - lows[i]
        if full_range == 0:
            continue

        body_ratio = body / full_range

        # Doji: very small body relative to range
        if body_ratio < 0.1:
            patterns.append({"index": i, "pattern": "doji", "strength": 1 - body_ratio})

        # Hammer: small body at top, long lower shadow
        if i > 0:
            upper_shadow = highs[i] - max(opens[i], closes[i])
            lower_shadow = min(opens[i], closes[i]) - lows[i]

            if lower_shadow > 2 * body and upper_shadow < body and body_ratio > 0.1:
                patterns.append({"index": i, "pattern": "hammer", "strength": lower_shadow / full_range})

            # Bullish engulfing
            if (closes[i - 1] < opens[i - 1] and  # prev bearish
                closes[i] > opens[i] and  # curr bullish
                opens[i] <= closes[i - 1] and
                closes[i] >= opens[i - 1]):
                patterns.append({"index": i, "pattern": "bullish_engulfing", "strength": body / full_range})

            # Bearish engulfing
            if (closes[i - 1] > opens[i - 1] and  # prev bullish
                closes[i] < opens[i] and  # curr bearish
                opens[i] >= closes[i - 1] and
                closes[i] <= opens[i - 1]):
                patterns.append({"index": i, "pattern": "bearish_engulfing", "strength": body / full_range})

    return patterns


def support_resistance(
    bars_df: pd.DataFrame,
    method: str = "clustering",
    n_levels: int = 5,
) -> list[float]:
    """Identify support/resistance levels.

    Args:
        bars_df: DataFrame with [high, low, close].
        method: 'clustering' (k-means) or 'pivot'.
        n_levels: Number of levels to identify.

    Returns:
        Sorted list of S/R price levels.
    """
    highs = bars_df["high"].values.astype(float)
    lows = bars_df["low"].values.astype(float)
    closes = bars_df["close"].values.astype(float)

    if len(closes) < 5:
        return []

    if method == "clustering":
        from scipy.cluster.vq import kmeans

        prices = np.concatenate([highs, lows, closes])
        prices = prices[np.isfinite(prices)]

        if len(prices) < n_levels:
            return sorted(prices.tolist())

        centroids, _ = kmeans(prices, n_levels)
        return sorted(centroids.tolist())

    elif method == "pivot":
        # Pivot point method
        levels = []
        for i in range(1, len(highs) - 1):
            pivot = (highs[i] + lows[i] + closes[i]) / 3
            levels.append(pivot)
        levels.sort()
        # Sample n_levels evenly
        if len(levels) <= n_levels:
            return levels
        step = len(levels) // n_levels
        return [levels[i * step] for i in range(n_levels)]

    return []


def scan_universe(
    store,
    exchange: str,
    symbols: list[str],
    timeframe: str,
    scan_config: list[dict],
) -> dict[str, list[dict]]:
    """Run scans across multiple symbols, return ranked results.

    Args:
        store: MarketDataStore instance.
        exchange: Exchange name.
        symbols: List of symbols to scan.
        timeframe: Bar timeframe.
        scan_config: Signal configurations for scan_signals().

    Returns:
        Dict of symbol -> list of signal events.
    """
    results = {}
    for symbol in symbols:
        bars = store.read_bars(exchange, symbol, timeframe)
        if not bars:
            continue

        bars_df = pd.DataFrame([{
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": float(b.volume),
        } for b in bars])

        signals = scan_signals(bars_df, scan_config)
        if signals:
            results[symbol] = signals

    return results
