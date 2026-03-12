"""Tests for regime-adaptive strategy."""

from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from strategy.regime_adaptive import RegimeAdaptive
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


class TestRegimeClassification:
    def test_low_vol_regime(self, btc_instrument):
        # Very low volatility data
        rng = np.random.default_rng(42)
        closes = 50000 + rng.normal(0, 10, 60)  # Nearly flat
        panel = make_panel_df({"BTC/USD": closes})

        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = RegimeAdaptive(ctx, params={
            "symbols": ["BTC/USD"],
            "vol_threshold": 0.3,
            "extreme_vol_threshold": 0.6,
            "quantity": "0.01",
        })
        strat.on_bar(panel)
        assert strat._current_regime.get("BTC/USD") == "low_vol"

    def test_high_vol_regime(self, btc_instrument):
        # High volatility data
        rng = np.random.default_rng(42)
        closes = 50000 + np.cumsum(rng.normal(0, 2000, 60))
        panel = make_panel_df({"BTC/USD": closes})

        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = RegimeAdaptive(ctx, params={
            "symbols": ["BTC/USD"],
            "vol_threshold": 0.1,   # Very low threshold
            "extreme_vol_threshold": 5.0,
            "quantity": "0.01",
        })
        strat.on_bar(panel)
        regime = strat._current_regime.get("BTC/USD")
        assert regime in ("high_vol", "extreme")


class TestRegimeAdaptive:
    def test_empty_panel(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = RegimeAdaptive(ctx)
        assert strat.on_bar(pd.DataFrame()) == []

    def test_returns_orders_list(self, btc_instrument):
        rng = np.random.default_rng(42)
        closes = 50000 + np.cumsum(rng.normal(10, 200, 60))
        panel = make_panel_df({"BTC/USD": closes})

        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = RegimeAdaptive(ctx, params={
            "symbols": ["BTC/USD"],
            "quantity": "0.01",
        })
        orders = strat.on_bar(panel)
        assert isinstance(orders, list)

    def test_lookback(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = RegimeAdaptive(ctx, params={
            "vol_lookback": 21,
            "slow_period": 30,
            "bb_period": 20,
        })
        assert strat.lookback() >= 30

    def test_universe(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = RegimeAdaptive(ctx, params={"symbols": ["BTC/USD", "ETH/USD"]})
        assert strat.universe() == ["BTC/USD", "ETH/USD"]
