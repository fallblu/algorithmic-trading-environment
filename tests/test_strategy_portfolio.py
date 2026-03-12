"""Tests for portfolio optimization and rebalancing strategy."""

from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from strategy.portfolio import PortfolioOptimizer, PortfolioRebalance
from tests.conftest import make_panel_df


@pytest.fixture
def returns_df():
    rng = np.random.default_rng(42)
    n = 100
    return pd.DataFrame({
        "BTC/USD": rng.normal(0.001, 0.03, n),
        "ETH/USD": rng.normal(0.0005, 0.04, n),
        "SOL/USD": rng.normal(0.002, 0.05, n),
    })


class TestMeanVariance:
    def test_weights_sum_to_one(self, returns_df):
        weights = PortfolioOptimizer.mean_variance(returns_df)
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_long_only(self, returns_df):
        weights = PortfolioOptimizer.mean_variance(returns_df)
        assert all(w >= 0 for w in weights.values())

    def test_empty_returns(self):
        weights = PortfolioOptimizer.mean_variance(pd.DataFrame())
        assert weights == {}


class TestMinVariance:
    def test_weights_sum_to_one(self, returns_df):
        weights = PortfolioOptimizer.min_variance(returns_df)
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_long_only(self, returns_df):
        weights = PortfolioOptimizer.min_variance(returns_df)
        assert all(w >= 0 for w in weights.values())

    def test_favors_low_vol(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "LOW_VOL": rng.normal(0, 0.01, 100),
            "HIGH_VOL": rng.normal(0, 0.10, 100),
        })
        weights = PortfolioOptimizer.min_variance(df)
        assert weights["LOW_VOL"] > weights["HIGH_VOL"]


class TestRiskParity:
    def test_weights_sum_to_one(self, returns_df):
        weights = PortfolioOptimizer.risk_parity(returns_df)
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_inverse_vol_weighting(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "LOW": rng.normal(0, 0.01, 100),
            "HIGH": rng.normal(0, 0.10, 100),
        })
        weights = PortfolioOptimizer.risk_parity(df)
        assert weights["LOW"] > weights["HIGH"]  # Low vol gets higher weight

    def test_equal_vol_gives_equal_weight(self):
        rng = np.random.default_rng(42)
        n = 1000
        vol = 0.02
        df = pd.DataFrame({
            "A": rng.normal(0, vol, n),
            "B": rng.normal(0, vol, n),
        })
        weights = PortfolioOptimizer.risk_parity(df)
        assert abs(weights["A"] - weights["B"]) < 0.05  # Approximately equal


class TestEqualWeight:
    def test_equal_allocation(self):
        weights = PortfolioOptimizer.equal_weight(["A", "B", "C"])
        assert len(weights) == 3
        for w in weights.values():
            assert abs(w - 1 / 3) < 1e-10

    def test_single_asset(self):
        weights = PortfolioOptimizer.equal_weight(["A"])
        assert weights["A"] == pytest.approx(1.0)

    def test_empty(self):
        assert PortfolioOptimizer.equal_weight([]) == {}


class TestPortfolioRebalance:
    def _make_ctx(self, instruments, equity=100000):
        ctx = MagicMock()
        univ = MagicMock()
        univ.instruments = instruments
        ctx.get_universe.return_value = univ
        broker = MagicMock()
        account = MagicMock()
        account.equity = Decimal(str(equity))
        broker.get_account.return_value = account
        broker.get_position.return_value = None
        ctx.get_broker.return_value = broker
        return ctx

    def test_equal_weight_rebalance(self, btc_instrument, eth_instrument):
        rng = np.random.default_rng(42)
        n = 60
        btc_closes = 50000 + np.cumsum(rng.normal(0, 500, n))
        eth_closes = 3000 + np.cumsum(rng.normal(0, 50, n))
        panel = make_panel_df({"BTC/USD": btc_closes, "ETH/USD": eth_closes}, n_bars=n)

        ctx = self._make_ctx({"BTC/USD": btc_instrument, "ETH/USD": eth_instrument})
        strat = PortfolioRebalance(ctx, params={
            "method": "equal_weight",
            "rebalance_freq": 1,  # Rebalance every bar
            "symbols": ["BTC/USD", "ETH/USD"],
        })

        # First bar doesn't rebalance (count starts at 0)
        # Need to get to rebalance_freq
        orders = strat.on_bar(panel)
        assert isinstance(orders, list)

    def test_no_rebalance_before_freq(self, btc_instrument):
        rng = np.random.default_rng(42)
        closes = 50000 + np.cumsum(rng.normal(0, 500, 60))
        panel = make_panel_df({"BTC/USD": closes})

        ctx = self._make_ctx({"BTC/USD": btc_instrument})
        strat = PortfolioRebalance(ctx, params={
            "method": "equal_weight",
            "rebalance_freq": 100,  # Won't trigger
            "symbols": ["BTC/USD"],
        })
        orders = strat.on_bar(panel)
        assert orders == []

    def test_empty_panel(self, btc_instrument):
        ctx = self._make_ctx({"BTC/USD": btc_instrument})
        strat = PortfolioRebalance(ctx)
        assert strat.on_bar(pd.DataFrame()) == []
