"""Technical scanning — indicator computation, signal detection, and pattern recognition."""

import logging

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
from analytics.utils import bars_to_arrays

log = logging.getLogger(__name__)


def scan_indicators(bars_df: pd.DataFrame, indicators: list[str] | None = None) -> pd.DataFrame:
    """Compute a batch of technical indicators over a bar series.

    Args:
        bars_df: DataFrame with columns [open, high, low, close, volume].
        indicators: List of indicator names to compute. None = all.

    Returns:
        DataFrame with indicator columns aligned to bar timestamps.
    """
    ohlcv = bars_to_arrays(bars_df)
    n = len(ohlcv.closes)

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
            result[ind] = _align(sma(ohlcv.closes, p), n)
        elif ind.startswith("ema_"):
            p = int(ind.split("_")[1])
            result[ind] = _align(ema(ohlcv.closes, p), n)
        elif ind.startswith("rsi"):
            p = int(ind.split("_")[1]) if "_" in ind else 14
            result[ind] = _align(rsi(ohlcv.closes, p), n)
        elif ind == "macd":
            macd_line, signal_line, hist = macd(ohlcv.closes)
            result["macd_line"] = _align(macd_line, n)
            result["macd_signal"] = _align(signal_line, n)
            result["macd_histogram"] = _align(hist, n)
        elif ind == "bollinger":
            upper, middle, lower = bollinger_bands(ohlcv.closes)
            result["bb_upper"] = _align(upper, n)
            result["bb_middle"] = _align(middle, n)
            result["bb_lower"] = _align(lower, n)
        elif ind.startswith("atr"):
            p = int(ind.split("_")[1]) if "_" in ind else 14
            result[ind] = _align(atr(ohlcv.highs, ohlcv.lows, ohlcv.closes, p), n)
        elif ind == "stochastic":
            k, d = stochastic(ohlcv.highs, ohlcv.lows, ohlcv.closes)
            result["stoch_k"] = _align(k, n)
            result["stoch_d"] = _align(d, n)
        elif ind == "obv":
            result["obv"] = obv(ohlcv.closes, ohlcv.volumes)

    log.debug("Computed %d indicators over %d bars", len(indicators), n)
    return result


def scan_signals(bars_df: pd.DataFrame, signal_configs: list[dict]) -> list[dict]:
    """Detect buy/sell signal events from indicator combinations.

    Args:
        bars_df: DataFrame with [open, high, low, close, volume].
        signal_configs: List of signal definitions, e.g.:
            [{"type": "crossover", "fast": "ema_10", "slow": "sma_30"}]

    Returns:
        List of signal events: [{index, signal, strength, ...}]
    """
    indicators_needed = set()
    for cfg in signal_configs:
        if cfg["type"] == "crossover":
            indicators_needed.add(cfg["fast"])
            indicators_needed.add(cfg["slow"])

    ind_df = scan_indicators(bars_df, list(indicators_needed))
    signals = []

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

    log.debug("Detected %d signals from %d configs", len(signals), len(signal_configs))
    return signals


def scan_patterns(bars_df: pd.DataFrame) -> list[dict]:
    """Detect candlestick patterns (doji, hammer, engulfing).

    Args:
        bars_df: DataFrame with [open, high, low, close].

    Returns:
        List of pattern events.
    """
    ohlcv = bars_to_arrays(bars_df)
    patterns = []

    for i in range(len(ohlcv.opens)):
        body = abs(ohlcv.closes[i] - ohlcv.opens[i])
        full_range = ohlcv.highs[i] - ohlcv.lows[i]
        if full_range == 0:
            continue

        body_ratio = body / full_range

        # Doji: very small body relative to range
        if body_ratio < 0.1:
            patterns.append({"index": i, "pattern": "doji", "strength": 1 - body_ratio})

        # Hammer and engulfing patterns require previous bar
        if i > 0:
            upper_shadow = ohlcv.highs[i] - max(ohlcv.opens[i], ohlcv.closes[i])
            lower_shadow = min(ohlcv.opens[i], ohlcv.closes[i]) - ohlcv.lows[i]

            if lower_shadow > 2 * body and upper_shadow < body and body_ratio > 0.1:
                patterns.append({"index": i, "pattern": "hammer", "strength": lower_shadow / full_range})

            # Bullish engulfing
            if (ohlcv.closes[i - 1] < ohlcv.opens[i - 1] and
                ohlcv.closes[i] > ohlcv.opens[i] and
                ohlcv.opens[i] <= ohlcv.closes[i - 1] and
                ohlcv.closes[i] >= ohlcv.opens[i - 1]):
                patterns.append({"index": i, "pattern": "bullish_engulfing", "strength": body / full_range})

            # Bearish engulfing
            if (ohlcv.closes[i - 1] > ohlcv.opens[i - 1] and
                ohlcv.closes[i] < ohlcv.opens[i] and
                ohlcv.opens[i] >= ohlcv.closes[i - 1] and
                ohlcv.closes[i] <= ohlcv.opens[i - 1]):
                patterns.append({"index": i, "pattern": "bearish_engulfing", "strength": body / full_range})

    log.debug("Detected %d candlestick patterns", len(patterns))
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
    ohlcv = bars_to_arrays(bars_df)

    if len(ohlcv.closes) < 5:
        return []

    if method == "clustering":
        from scipy.cluster.vq import kmeans

        prices = np.concatenate([ohlcv.highs, ohlcv.lows, ohlcv.closes])
        prices = prices[np.isfinite(prices)]

        if len(prices) < n_levels:
            return sorted(prices.tolist())

        centroids, _ = kmeans(prices, n_levels)
        return sorted(centroids.tolist())

    elif method == "pivot":
        levels = []
        for i in range(1, len(ohlcv.highs) - 1):
            pivot = (ohlcv.highs[i] + ohlcv.lows[i] + ohlcv.closes[i]) / 3
            levels.append(pivot)
        levels.sort()
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
            log.debug("No data for %s/%s/%s, skipping", exchange, symbol, timeframe)
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

    log.info("Universe scan complete: %d/%d symbols had signals", len(results), len(symbols))
    return results
