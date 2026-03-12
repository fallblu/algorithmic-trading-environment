"""Tests for analytics statistics module."""

import numpy as np
import pandas as pd
import pytest

from analytics.statistics import (
    return_distribution,
    volatility_analysis,
    tail_risk_analysis,
    autocorrelation_analysis,
)


@pytest.fixture
def bars_df():
    """Synthetic bars DataFrame with 'close' column."""
    rng = np.random.default_rng(42)
    n = 200
    closes = 50000 + np.cumsum(rng.normal(5, 500, n))
    return pd.DataFrame({"close": closes})


class TestReturnDistribution:
    def test_basic(self, bars_df):
        result = return_distribution(bars_df)
        assert "mean" in result
        assert "std" in result
        assert "skewness" in result
        assert "kurtosis" in result

    def test_uptrend_positive_mean(self):
        closes = np.arange(100, 200, dtype=float)
        df = pd.DataFrame({"close": closes})
        result = return_distribution(df)
        assert result["mean"] > 0

    def test_short_series(self):
        df = pd.DataFrame({"close": [100.0, 101.0]})
        result = return_distribution(df)
        assert "mean" in result


class TestVolatilityAnalysis:
    def test_basic(self, bars_df):
        result = volatility_analysis(bars_df)
        assert "realized_vol" in result

    def test_flat_data_low_vol(self):
        df = pd.DataFrame({"close": np.full(100, 50000.0)})
        result = volatility_analysis(df)
        assert result["realized_vol"] < 0.01


class TestTailRisk:
    def test_basic(self, bars_df):
        result = tail_risk_analysis(bars_df)
        assert "var_95" in result
        assert "cvar_95" in result

    def test_returns_numeric(self, bars_df):
        result = tail_risk_analysis(bars_df)
        for key, val in result.items():
            if isinstance(val, (int, float)):
                assert not np.isnan(val)

    def test_short_series(self):
        df = pd.DataFrame({"close": [100.0, 101.0]})
        result = tail_risk_analysis(df)
        assert result["var_95"] == 0.0


class TestAutocorrelation:
    def test_basic(self, bars_df):
        result = autocorrelation_analysis(bars_df)
        assert "acf_returns" in result
        assert isinstance(result["acf_returns"], list)

    def test_short_series(self):
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
        result = autocorrelation_analysis(df)
        assert isinstance(result, dict)
