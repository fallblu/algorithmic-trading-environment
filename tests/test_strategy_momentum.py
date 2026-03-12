"""Tests for momentum/trend-following strategies."""

from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from models.order import OrderSide
from strategy.momentum import BreakoutStrategy, MACDTrend, ADXTrend
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


class TestBreakoutStrategy:
    def test_breakout_on_new_high(self, btc_instrument):
        # Flat then breakout
        closes = np.concatenate([
            np.full(50, 50000.0),
            np.linspace(50000, 55000, 10),  # Sharp upward breakout
        ])
        panel = make_panel_df({"BTC/USD": closes})

        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = BreakoutStrategy(ctx, params={
            "symbols": ["BTC/USD"],
            "breakout_period": 20,
            "quantity": "0.1",
        })
        orders = strat.on_bar(panel)
        assert isinstance(orders, list)

    def test_empty_panel(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = BreakoutStrategy(ctx)
        assert strat.on_bar(pd.DataFrame()) == []

    def test_universe(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = BreakoutStrategy(ctx, params={"symbols": ["BTC/USD"]})
        assert "BTC/USD" in strat.universe()


class TestMACDTrend:
    def test_returns_valid_orders(self, btc_instrument):
        rng = np.random.default_rng(42)
        closes = 50000 + np.cumsum(rng.normal(50, 500, 60))
        panel = make_panel_df({"BTC/USD": closes})

        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = MACDTrend(ctx, params={
            "symbols": ["BTC/USD"],
            "quantity": "0.1",
        })
        # Process twice to get prev state
        strat.on_bar(panel)
        orders = strat.on_bar(panel)
        assert isinstance(orders, list)

    def test_lookback(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = MACDTrend(ctx)
        assert strat.lookback() > 26  # At least slow period


class TestADXTrend:
    def test_returns_valid_orders(self, btc_instrument):
        rng = np.random.default_rng(42)
        closes = 50000 + np.cumsum(rng.normal(50, 500, 60))
        panel = make_panel_df({"BTC/USD": closes})

        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = ADXTrend(ctx, params={
            "symbols": ["BTC/USD"],
            "quantity": "0.1",
            "adx_threshold": 20,
        })
        # Process twice for prev state
        strat.on_bar(panel)
        orders = strat.on_bar(panel)
        assert isinstance(orders, list)

    def test_empty_panel(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = ADXTrend(ctx)
        assert strat.on_bar(pd.DataFrame()) == []
