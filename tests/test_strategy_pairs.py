"""Tests for pairs trading strategy."""

from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from strategy.pairs import PairsTrading, _compute_spread, _zscore
from tests.conftest import make_panel_df


def _make_ctx(instruments, broker=None):
    ctx = MagicMock()
    univ = MagicMock()
    univ.instruments = instruments
    ctx.get_universe.return_value = univ
    if broker is None:
        broker = MagicMock()
        broker.get_position.return_value = None
    ctx.get_broker.return_value = broker
    return ctx


class TestComputeSpread:
    def test_cointegrated_series(self):
        rng = np.random.default_rng(42)
        n = 100
        b = np.cumsum(rng.normal(0, 1, n)) + 100
        a = 2 * b + rng.normal(0, 0.5, n) + 10
        spread, beta = _compute_spread(a, b)
        assert len(spread) == n
        assert abs(beta - 2.0) < 0.5  # Hedge ratio close to 2

    def test_spread_mean_near_zero(self):
        rng = np.random.default_rng(42)
        n = 200
        b = np.cumsum(rng.normal(0, 1, n)) + 100
        a = 1.5 * b + rng.normal(0, 0.3, n) + 5
        spread, _ = _compute_spread(a, b)
        assert abs(np.mean(spread)) < 5.0  # Should be near zero


class TestZScore:
    def test_basic(self):
        series = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 5.0])
        z = _zscore(series, 5)
        assert z > 1.0  # 5.0 is above mean of the window

    def test_at_mean(self):
        series = np.array([10.0, 10.0, 10.0, 10.0, 10.0])
        z = _zscore(series, 5)
        assert abs(z) < 0.1

    def test_insufficient_data(self):
        series = np.array([1.0, 2.0])
        z = _zscore(series, 10)
        assert z == 0.0

    def test_zero_std(self):
        series = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
        z = _zscore(series, 5)
        assert z == 0.0


class TestPairsTrading:
    def test_requires_two_symbols(self, btc_instrument, eth_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument, "ETH/USD": eth_instrument})
        strat = PairsTrading(ctx, params={
            "pair_symbols": ["BTC/USD", "ETH/USD"],
            "lookback": 30,
        })
        assert strat.universe() == ["BTC/USD", "ETH/USD"]

    def test_rejects_wrong_number_of_symbols(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        try:
            PairsTrading(ctx, params={"pair_symbols": ["BTC/USD"]})
            assert False, "Should raise ValueError"
        except ValueError:
            pass

    def test_on_bar_with_cointegrated_data(self, btc_instrument, eth_instrument):
        rng = np.random.default_rng(42)
        n = 60
        eth_closes = 3000 + np.cumsum(rng.normal(0, 50, n))
        btc_closes = 15 * eth_closes + rng.normal(0, 100, n)

        panel = make_panel_df({
            "BTC/USD": btc_closes,
            "ETH/USD": eth_closes,
        }, n_bars=n)

        ctx = _make_ctx({
            "BTC/USD": btc_instrument,
            "ETH/USD": eth_instrument,
        })
        strat = PairsTrading(ctx, params={
            "pair_symbols": ["BTC/USD", "ETH/USD"],
            "lookback": 30,
            "entry_z": 2.0,
            "exit_z": 0.5,
            "quantity": "0.01",
        })
        orders = strat.on_bar(panel)
        assert isinstance(orders, list)

    def test_empty_panel(self, btc_instrument, eth_instrument):
        ctx = _make_ctx({
            "BTC/USD": btc_instrument,
            "ETH/USD": eth_instrument,
        })
        strat = PairsTrading(ctx, params={
            "pair_symbols": ["BTC/USD", "ETH/USD"],
        })
        assert strat.on_bar(pd.DataFrame()) == []
