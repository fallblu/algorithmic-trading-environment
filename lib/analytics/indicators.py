"""Pure indicator computation functions — stateless, NumPy-based."""

import numpy as np


def sma(values: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average.

    Returns array of length max(0, len(values) - period + 1).
    """
    if len(values) < period or period < 1:
        return np.array([])
    cumsum = np.cumsum(values)
    cumsum = np.insert(cumsum, 0, 0)
    return (cumsum[period:] - cumsum[:-period]) / period


def ema(values: np.ndarray, period: int, alpha: float | None = None) -> np.ndarray:
    """Exponential Moving Average.

    First value is SMA of the first `period` elements.
    Subsequent values follow: alpha * x + (1 - alpha) * prev_ema.
    """
    if len(values) < period or period < 1:
        return np.array([])

    if alpha is None:
        alpha = 2.0 / (period + 1)

    result = np.empty(len(values) - period + 1)
    result[0] = np.mean(values[:period])

    for i in range(1, len(result)):
        result[i] = alpha * values[period - 1 + i] + (1 - alpha) * result[i - 1]

    return result


def wma(values: np.ndarray, period: int) -> np.ndarray:
    """Weighted Moving Average.

    Weights: [1, 2, ..., period]. Weight sum = period * (period + 1) / 2.
    """
    if len(values) < period or period < 1:
        return np.array([])

    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()

    result = np.empty(len(values) - period + 1)
    for i in range(len(result)):
        result[i] = np.dot(values[i : i + period], weights) / weight_sum

    return result


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index. Range: [0, 100].

    Returns array of length max(0, len(closes) - period).
    """
    if len(closes) < period + 1 or period < 1:
        return np.array([])

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    result = np.empty(len(deltas) - period + 1)

    if avg_loss == 0:
        result[0] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[0] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(1, len(result)):
        idx = period - 1 + i
        avg_gain = (avg_gain * (period - 1) + gains[idx]) / period
        avg_loss = (avg_loss * (period - 1) + losses[idx]) / period

        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))

    return result


def macd(
    closes: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD indicator.

    Returns:
        (macd_line, signal_line, histogram) — all aligned to the same length.
    """
    if len(closes) < slow or slow < 1:
        return np.array([]), np.array([]), np.array([])

    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)

    # Align: fast_ema is longer than slow_ema
    offset = len(fast_ema) - len(slow_ema)
    macd_line = fast_ema[offset:] - slow_ema

    if len(macd_line) < signal:
        return macd_line, np.array([]), np.array([])

    signal_line = ema(macd_line, signal)
    # Align macd_line to signal_line
    offset2 = len(macd_line) - len(signal_line)
    macd_aligned = macd_line[offset2:]
    histogram = macd_aligned - signal_line

    return macd_aligned, signal_line, histogram


def bollinger_bands(
    closes: np.ndarray, period: int = 20, std_dev: float = 2.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands.

    Returns:
        (upper_band, middle_band, lower_band) — all same length.
    """
    if len(closes) < period or period < 1:
        return np.array([]), np.array([]), np.array([])

    middle = sma(closes, period)

    # Rolling standard deviation
    stds = np.empty(len(middle))
    for i in range(len(stds)):
        window = closes[i : i + period]
        stds[i] = np.std(window, ddof=0)

    upper = middle + std_dev * stds
    lower = middle - std_dev * stds

    return upper, middle, lower


def atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average True Range.

    Returns array of length max(0, len(closes) - period).
    """
    if len(closes) < period + 1 or period < 1:
        return np.array([])

    tr = np.empty(len(closes) - 1)
    for i in range(len(tr)):
        hl = highs[i + 1] - lows[i + 1]
        hc = abs(highs[i + 1] - closes[i])
        lc = abs(lows[i + 1] - closes[i])
        tr[i] = max(hl, hc, lc)

    # First ATR is SMA of first `period` TRs
    if len(tr) < period:
        return np.array([])

    result = np.empty(len(tr) - period + 1)
    result[0] = np.mean(tr[:period])

    for i in range(1, len(result)):
        result[i] = (result[i - 1] * (period - 1) + tr[period - 1 + i]) / period

    return result


def adx(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average Directional Index. Range: [0, 100].

    Returns array of length based on available data after smoothing.
    """
    if len(closes) < 2 * period + 1 or period < 1:
        return np.array([])

    # Directional movements
    plus_dm = np.empty(len(highs) - 1)
    minus_dm = np.empty(len(highs) - 1)
    tr_vals = np.empty(len(highs) - 1)

    for i in range(len(plus_dm)):
        up = highs[i + 1] - highs[i]
        down = lows[i] - lows[i + 1]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0

        hl = highs[i + 1] - lows[i + 1]
        hc = abs(highs[i + 1] - closes[i])
        lc = abs(lows[i + 1] - closes[i])
        tr_vals[i] = max(hl, hc, lc)

    if len(tr_vals) < period:
        return np.array([])

    # Smooth using Wilder's method
    def wilder_smooth(data, p):
        result = np.empty(len(data) - p + 1)
        result[0] = np.sum(data[:p])
        for j in range(1, len(result)):
            result[j] = result[j - 1] - result[j - 1] / p + data[p - 1 + j]
        return result

    smooth_tr = wilder_smooth(tr_vals, period)
    smooth_plus = wilder_smooth(plus_dm, period)
    smooth_minus = wilder_smooth(minus_dm, period)

    n = min(len(smooth_tr), len(smooth_plus), len(smooth_minus))
    smooth_tr = smooth_tr[:n]
    smooth_plus = smooth_plus[:n]
    smooth_minus = smooth_minus[:n]

    # +DI and -DI
    plus_di = np.where(smooth_tr != 0, 100 * smooth_plus / smooth_tr, 0.0)
    minus_di = np.where(smooth_tr != 0, 100 * smooth_minus / smooth_tr, 0.0)

    # DX
    di_sum = plus_di + minus_di
    dx = np.where(di_sum != 0, 100 * np.abs(plus_di - minus_di) / di_sum, 0.0)

    if len(dx) < period:
        return np.array([])

    # ADX = smoothed DX
    adx_vals = np.empty(len(dx) - period + 1)
    adx_vals[0] = np.mean(dx[:period])
    for i in range(1, len(adx_vals)):
        adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[period - 1 + i]) / period

    return adx_vals


def stochastic(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Stochastic Oscillator. %K and %D range: [0, 100].

    Returns:
        (%K, %D) arrays.
    """
    if len(closes) < k_period or k_period < 1:
        return np.array([]), np.array([])

    k_values = np.empty(len(closes) - k_period + 1)
    for i in range(len(k_values)):
        window_high = np.max(highs[i : i + k_period])
        window_low = np.min(lows[i : i + k_period])
        diff = window_high - window_low
        if diff == 0:
            k_values[i] = 50.0
        else:
            k_values[i] = 100.0 * (closes[i + k_period - 1] - window_low) / diff

    if len(k_values) < d_period:
        return k_values, np.array([])

    d_values = sma(k_values, d_period)
    return k_values, d_values


def obv(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """On-Balance Volume.

    Returns array of same length as input.
    """
    if len(closes) == 0:
        return np.array([])

    result = np.empty(len(closes))
    result[0] = volumes[0]

    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            result[i] = result[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            result[i] = result[i - 1] - volumes[i]
        else:
            result[i] = result[i - 1]

    return result
