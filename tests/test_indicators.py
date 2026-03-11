import numpy as np
import pytest

from analytics.indicators import (
    atr,
    bollinger_bands,
    ema,
    macd,
    obv,
    rsi,
    sma,
    wma,
)


# ---------------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------------

class TestSMA:
    def test_known_values(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(data, 3)
        np.testing.assert_allclose(result, [2.0, 3.0, 4.0])

    def test_period_equals_length(self):
        data = np.array([10.0, 20.0, 30.0])
        result = sma(data, 3)
        np.testing.assert_allclose(result, [20.0])

    def test_period_one(self):
        data = np.array([5.0, 10.0, 15.0])
        result = sma(data, 1)
        np.testing.assert_allclose(result, [5.0, 10.0, 15.0])

    def test_insufficient_data(self):
        data = np.array([1.0, 2.0])
        result = sma(data, 5)
        assert len(result) == 0

    def test_empty_input(self):
        result = sma(np.array([]), 3)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

class TestEMA:
    def test_first_value_is_sma(self):
        data = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
        result = ema(data, 3)
        # First value should be SMA of first 3 elements: (2+4+6)/3 = 4.0
        assert result[0] == pytest.approx(4.0)

    def test_known_values(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = ema(data, 3)
        alpha = 2.0 / (3 + 1)
        expected_0 = 2.0  # SMA(1,2,3)
        expected_1 = alpha * 4.0 + (1 - alpha) * expected_0  # 0.5*4 + 0.5*2 = 3.0
        expected_2 = alpha * 5.0 + (1 - alpha) * expected_1  # 0.5*5 + 0.5*3 = 4.0
        np.testing.assert_allclose(result, [expected_0, expected_1, expected_2])

    def test_custom_alpha(self):
        data = np.array([10.0, 20.0, 30.0, 40.0])
        result = ema(data, 2, alpha=0.5)
        expected_0 = 15.0  # SMA(10, 20)
        expected_1 = 0.5 * 30.0 + 0.5 * 15.0  # 22.5
        expected_2 = 0.5 * 40.0 + 0.5 * 22.5  # 31.25
        np.testing.assert_allclose(result, [expected_0, expected_1, expected_2])

    def test_insufficient_data(self):
        result = ema(np.array([1.0]), 3)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# WMA
# ---------------------------------------------------------------------------

class TestWMA:
    def test_known_values(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = wma(data, 3)
        # weights = [1, 2, 3], weight_sum = 6
        expected_0 = (1 * 1.0 + 2 * 2.0 + 3 * 3.0) / 6  # 14/6
        expected_1 = (1 * 2.0 + 2 * 3.0 + 3 * 4.0) / 6  # 20/6
        expected_2 = (1 * 3.0 + 2 * 4.0 + 3 * 5.0) / 6  # 26/6
        np.testing.assert_allclose(result, [expected_0, expected_1, expected_2])

    def test_period_one(self):
        data = np.array([7.0, 8.0, 9.0])
        result = wma(data, 1)
        np.testing.assert_allclose(result, [7.0, 8.0, 9.0])

    def test_insufficient_data(self):
        result = wma(np.array([1.0]), 3)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

class TestRSI:
    def test_all_gains(self):
        # Monotonically increasing prices => RSI should be 100
        closes = np.arange(1.0, 20.0)  # 1, 2, 3, ..., 19
        result = rsi(closes, period=14)
        assert len(result) > 0
        assert result[0] == pytest.approx(100.0)

    def test_all_losses(self):
        # Monotonically decreasing prices => RSI should be 0
        closes = np.arange(20.0, 0.0, -1.0)  # 20, 19, 18, ..., 1
        result = rsi(closes, period=14)
        assert len(result) > 0
        assert result[0] == pytest.approx(0.0)

    def test_range_0_to_100(self):
        np.random.seed(42)
        closes = np.cumsum(np.random.randn(100)) + 100
        result = rsi(closes, period=14)
        assert len(result) > 0
        assert np.all(result >= 0.0)
        assert np.all(result <= 100.0)

    def test_insufficient_data(self):
        result = rsi(np.array([1.0, 2.0, 3.0]), period=14)
        assert len(result) == 0

    def test_output_length(self):
        closes = np.arange(1.0, 31.0)
        result = rsi(closes, period=14)
        # len(closes) - period = 30 - 14 = 16
        assert len(result) == 16


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

class TestMACD:
    def test_returns_three_arrays(self):
        closes = np.cumsum(np.ones(60)) + 100
        macd_line, signal_line, histogram = macd(closes)
        assert isinstance(macd_line, np.ndarray)
        assert isinstance(signal_line, np.ndarray)
        assert isinstance(histogram, np.ndarray)

    def test_histogram_equals_macd_minus_signal(self):
        np.random.seed(42)
        closes = np.cumsum(np.random.randn(60)) + 100
        macd_line, signal_line, histogram = macd(closes)
        if len(histogram) > 0:
            np.testing.assert_allclose(histogram, macd_line - signal_line, atol=1e-10)

    def test_same_length_outputs(self):
        closes = np.cumsum(np.ones(60)) + 100
        macd_line, signal_line, histogram = macd(closes)
        assert len(macd_line) == len(signal_line)
        assert len(macd_line) == len(histogram)

    def test_insufficient_data(self):
        closes = np.array([1.0, 2.0, 3.0])
        macd_line, signal_line, histogram = macd(closes)
        assert len(macd_line) == 0


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

class TestBollingerBands:
    def test_middle_equals_sma(self):
        np.random.seed(42)
        closes = np.cumsum(np.random.randn(50)) + 100
        upper, middle, lower = bollinger_bands(closes, period=20)
        expected_middle = sma(closes, 20)
        np.testing.assert_allclose(middle, expected_middle)

    def test_upper_above_lower(self):
        np.random.seed(42)
        closes = np.cumsum(np.random.randn(50)) + 100
        upper, middle, lower = bollinger_bands(closes, period=20)
        assert np.all(upper >= lower)

    def test_symmetry_around_middle(self):
        np.random.seed(42)
        closes = np.cumsum(np.random.randn(50)) + 100
        upper, middle, lower = bollinger_bands(closes, period=20, std_dev=2.0)
        np.testing.assert_allclose(upper - middle, middle - lower, atol=1e-10)

    def test_insufficient_data(self):
        closes = np.array([1.0, 2.0])
        upper, middle, lower = bollinger_bands(closes, period=20)
        assert len(upper) == 0
        assert len(middle) == 0
        assert len(lower) == 0


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

class TestATR:
    def test_simple_data(self):
        # 6 bars with constant high-low range of 10
        highs = np.array([110.0, 112.0, 111.0, 113.0, 112.0, 114.0])
        lows = np.array([100.0, 102.0, 101.0, 103.0, 102.0, 104.0])
        closes = np.array([105.0, 107.0, 106.0, 108.0, 107.0, 109.0])
        result = atr(highs, lows, closes, period=3)
        assert len(result) > 0
        # All true ranges should be 10 (high-low) since close stays in range
        assert result[0] == pytest.approx(10.0)

    def test_output_length(self):
        n = 20
        np.random.seed(42)
        highs = np.random.rand(n) + 101
        lows = np.random.rand(n) + 99
        closes = np.random.rand(n) + 100
        result = atr(highs, lows, closes, period=5)
        # len(closes) - period = 20 - 5 = 15
        assert len(result) == 15

    def test_insufficient_data(self):
        result = atr(np.array([1.0]), np.array([0.5]), np.array([0.8]), period=5)
        assert len(result) == 0

    def test_positive_values(self):
        np.random.seed(42)
        n = 30
        closes = np.cumsum(np.random.randn(n)) + 100
        highs = closes + np.abs(np.random.randn(n))
        lows = closes - np.abs(np.random.randn(n))
        result = atr(highs, lows, closes, period=14)
        assert np.all(result > 0)


# ---------------------------------------------------------------------------
# OBV
# ---------------------------------------------------------------------------

class TestOBV:
    def test_direction_changes(self):
        closes = np.array([10.0, 12.0, 11.0, 13.0, 13.0])
        volumes = np.array([100.0, 200.0, 150.0, 300.0, 250.0])
        result = obv(closes, volumes)
        assert len(result) == 5
        assert result[0] == 100.0       # initial
        assert result[1] == 300.0       # up: 100 + 200
        assert result[2] == 150.0       # down: 300 - 150
        assert result[3] == 450.0       # up: 150 + 300
        assert result[4] == 450.0       # flat: unchanged

    def test_all_up(self):
        closes = np.array([1.0, 2.0, 3.0, 4.0])
        volumes = np.array([10.0, 20.0, 30.0, 40.0])
        result = obv(closes, volumes)
        np.testing.assert_array_equal(result, [10.0, 30.0, 60.0, 100.0])

    def test_empty_input(self):
        result = obv(np.array([]), np.array([]))
        assert len(result) == 0

    def test_single_element(self):
        result = obv(np.array([50.0]), np.array([1000.0]))
        assert len(result) == 1
        assert result[0] == 1000.0
