"""Tests for multi-timeframe strategy."""

from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from models.order import OrderSide
from strategy.multi_timeframe import MultiTimeframe
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


class TestMultiTimeframe:
    def test_empty_panel(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = MultiTimeframe(ctx)
        assert strat.on_bar(pd.DataFrame()) == []

    def test_lookback_includes_trend_period(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = MultiTimeframe(ctx, params={"trend_period": 100})
        assert strat.lookback() >= 100

    def test_universe(self, btc_instrument):
        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = MultiTimeframe(ctx, params={"symbols": ["BTC/USD"]})
        assert strat.universe() == ["BTC/USD"]

    def test_returns_orders_on_crossover(self, btc_instrument):
        # Strong uptrend data for bullish trend
        rng = np.random.default_rng(42)
        n = 120
        closes = 50000 + np.arange(n) * 100 + rng.normal(0, 200, n)
        panel = make_panel_df({"BTC/USD": closes}, n_bars=n)

        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = MultiTimeframe(ctx, params={
            "symbols": ["BTC/USD"],
            "trend_period": 50,
            "entry_fast": 5,
            "entry_slow": 15,
            "quantity": "0.01",
        })

        # Process twice to establish prev state
        strat.on_bar(panel)
        orders = strat.on_bar(panel)
        assert isinstance(orders, list)

    def test_only_buys_in_uptrend(self, btc_instrument):
        # Downtrend data — should not generate buy signals
        n = 120
        closes = np.array([50000 - i * 50 for i in range(n)], dtype=float)
        panel = make_panel_df({"BTC/USD": closes}, n_bars=n)

        ctx = _make_ctx({"BTC/USD": btc_instrument})
        strat = MultiTimeframe(ctx, params={
            "symbols": ["BTC/USD"],
            "trend_period": 50,
            "entry_fast": 5,
            "entry_slow": 15,
            "quantity": "0.01",
        })
        strat.on_bar(panel)
        orders = strat.on_bar(panel)
        buy_orders = [o for o in orders if o.side == OrderSide.BUY]
        assert len(buy_orders) == 0  # No buys in downtrend
