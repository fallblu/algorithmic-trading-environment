"""Tests for technical indicators."""

import numpy as np
import pytest

from analytics.indicators import (
    sma, ema, rsi, macd, bollinger_bands, atr, adx, stochastic, obv, wma,
)


class TestSMA:
    def test_basic(self, sample_closes):
        result = sma(sample_closes, 10)
        assert len(result) > 0
        # SMA of last 10 should be average of last 10 values
        expected = np.mean(sample_closes[-10:])
        assert abs(result[-1] - expected) < 1.0

    def test_period_larger_than_data(self):
        data = np.array([1.0, 2.0, 3.0])
        result = sma(data, 10)
        assert len(result) == 0 or np.all(np.isnan(result[:7]))

    def test_single_period(self, sample_closes):
        result = sma(sample_closes, 1)
        # SMA(1) = original values
        assert len(result) == len(sample_closes)
        np.testing.assert_allclose(result, sample_closes, rtol=1e-10)


class TestEMA:
    def test_basic(self, sample_closes):
        result = ema(sample_closes, 10)
        assert len(result) > 0

    def test_ema_follows_trend(self):
        # Upward trend: EMA should be below latest price
        data = np.arange(1.0, 101.0)
        result = ema(data, 10)
        assert result[-1] < data[-1]  # EMA lags in uptrend

    def test_ema_vs_sma_responsiveness(self, sample_closes):
        ema_result = ema(sample_closes, 20)
        sma_result = sma(sample_closes, 20)
        # Both should be similar length, both valid
        assert len(ema_result) > 0
        assert len(sma_result) > 0


class TestRSI:
    def test_basic(self, sample_closes):
        result = rsi(sample_closes, 14)
        assert len(result) > 0
        # RSI should be between 0 and 100
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0)
        assert np.all(valid <= 100)

    def test_strong_uptrend(self):
        data = np.arange(1.0, 51.0)  # Perfect uptrend
        result = rsi(data, 14)
        valid = result[~np.isnan(result)]
        if len(valid) > 0:
            assert valid[-1] > 90  # Should be very high

    def test_strong_downtrend(self):
        data = np.arange(50.0, 0.0, -1.0)  # Perfect downtrend
        result = rsi(data, 14)
        valid = result[~np.isnan(result)]
        if len(valid) > 0:
            assert valid[-1] < 10  # Should be very low


class TestMACD:
    def test_basic(self, sample_closes):
        macd_line, signal_line, histogram = macd(sample_closes)
        assert len(macd_line) > 0
        assert len(signal_line) > 0
        assert len(histogram) > 0

    def test_histogram_is_difference(self, sample_closes):
        macd_line, signal_line, histogram = macd(sample_closes)
        # Histogram = MACD line - Signal line
        n = min(len(macd_line), len(signal_line), len(histogram))
        if n > 0:
            expected = macd_line[-n:] - signal_line[-n:]
            np.testing.assert_allclose(histogram[-n:], expected, rtol=1e-10)


class TestBollingerBands:
    def test_basic(self, sample_closes):
        upper, middle, lower = bollinger_bands(sample_closes, 20, 2.0)
        assert len(upper) > 0
        assert len(middle) > 0
        assert len(lower) > 0

    def test_band_ordering(self, sample_closes):
        upper, middle, lower = bollinger_bands(sample_closes, 20, 2.0)
        n = min(len(upper), len(middle), len(lower))
        for i in range(n):
            if not np.isnan(upper[i]):
                assert upper[i] >= middle[i] >= lower[i]

    def test_middle_is_sma(self, sample_closes):
        upper, middle, lower = bollinger_bands(sample_closes, 20, 2.0)
        sma_vals = sma(sample_closes, 20)
        n = min(len(middle), len(sma_vals))
        if n > 0:
            np.testing.assert_allclose(middle[-n:], sma_vals[-n:], rtol=1e-10)


class TestATR:
    def test_basic(self, sample_ohlcv):
        opens, highs, lows, closes, volumes = sample_ohlcv
        result = atr(highs, lows, closes, 14)
        assert len(result) > 0
        # ATR should be positive
        valid = result[~np.isnan(result)]
        assert np.all(valid > 0)

    def test_flat_market_low_atr(self):
        n = 50
        closes = np.full(n, 100.0)
        highs = np.full(n, 100.1)
        lows = np.full(n, 99.9)
        result = atr(highs, lows, closes, 14)
        valid = result[~np.isnan(result)]
        if len(valid) > 0:
            assert valid[-1] < 1.0  # Very low ATR


class TestADX:
    def test_basic(self, sample_ohlcv):
        opens, highs, lows, closes, volumes = sample_ohlcv
        result = adx(highs, lows, closes, 14)
        assert len(result) > 0

    def test_strong_trend_high_adx(self):
        n = 100
        closes = np.arange(100.0, 100.0 + n)
        highs = closes + 1
        lows = closes - 0.5
        result = adx(highs, lows, closes, 14)
        valid = result[~np.isnan(result)]
        if len(valid) > 5:
            assert valid[-1] > 20  # Should indicate trending


class TestWMA:
    def test_basic(self, sample_closes):
        result = wma(sample_closes, 10)
        assert len(result) > 0
        assert len(result) == len(sample_closes) - 10 + 1

    def test_known_values(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = wma(data, 3)
        # Weights: [1, 2, 3], sum=6
        # wma[0] = (1*1 + 2*2 + 3*3)/6 = 14/6
        expected_0 = (1 * 1 + 2 * 2 + 3 * 3) / 6.0
        assert abs(result[0] - expected_0) < 1e-10

    def test_period_larger_than_data(self):
        data = np.array([1.0, 2.0])
        result = wma(data, 5)
        assert len(result) == 0

    def test_single_period(self):
        data = np.array([10.0, 20.0, 30.0])
        result = wma(data, 1)
        np.testing.assert_allclose(result, data, rtol=1e-10)


class TestStochastic:
    def test_basic(self, sample_ohlcv):
        opens, highs, lows, closes, volumes = sample_ohlcv
        k, d = stochastic(highs, lows, closes)
        assert len(k) > 0
        assert len(d) > 0

    def test_range_0_to_100(self, sample_ohlcv):
        opens, highs, lows, closes, volumes = sample_ohlcv
        k, d = stochastic(highs, lows, closes, k_period=14, d_period=3)
        assert np.all(k >= 0) and np.all(k <= 100)
        assert np.all(d >= 0) and np.all(d <= 100)

    def test_insufficient_data(self):
        data = np.array([1.0, 2.0, 3.0])
        k, d = stochastic(data, data, data, k_period=10)
        assert len(k) == 0

    def test_flat_market(self):
        n = 30
        closes = np.full(n, 100.0)
        highs = np.full(n, 100.0)
        lows = np.full(n, 100.0)
        k, d = stochastic(highs, lows, closes, k_period=14)
        # When high == low, %K defaults to 50
        assert np.all(k == 50.0)


class TestOBV:
    def test_basic(self, sample_ohlcv):
        opens, highs, lows, closes, volumes = sample_ohlcv
        result = obv(closes, volumes)
        assert len(result) == len(closes)

    def test_uptrend_increases_obv(self):
        closes = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
        volumes = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
        result = obv(closes, volumes)
        # Consecutive up closes: OBV should increase monotonically
        assert result[-1] == 500.0  # 100 + 100 + 100 + 100 + 100

    def test_downtrend_decreases_obv(self):
        closes = np.array([14.0, 13.0, 12.0, 11.0, 10.0])
        volumes = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
        result = obv(closes, volumes)
        # First bar = 100, then -100 for each down
        assert result[-1] == 100.0 - 400.0

    def test_flat_unchanged(self):
        closes = np.array([10.0, 10.0, 10.0])
        volumes = np.array([100.0, 200.0, 300.0])
        result = obv(closes, volumes)
        # No price change -> OBV stays at initial volume
        np.testing.assert_array_equal(result, [100.0, 100.0, 100.0])

    def test_empty(self):
        result = obv(np.array([]), np.array([]))
        assert len(result) == 0
