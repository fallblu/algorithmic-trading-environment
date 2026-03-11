"""Tests for strategy base, SmaCrossover, and strategy registry."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from data.price_panel import PricePanel
from data.universe import Universe
from models.bar import Bar
from models.instrument import Instrument
from models.order import OrderSide, OrderType
from strategy.base import Strategy
from strategy.registry import STRATEGY_REGISTRY, get_strategy, list_strategies, register
from strategy.sma_crossover import SmaCrossover


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_instrument():
    return Instrument(
        symbol="BTC/USD",
        base="BTC",
        quote="USD",
        exchange="kraken",
        asset_class="crypto",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.00001"),
        min_notional=Decimal("5"),
    )


def _make_ctx(universe=None, broker=None):
    """Build a mock ExecutionContext."""
    ctx = MagicMock()
    ctx.get_universe.return_value = universe
    ctx.get_broker.return_value = broker
    return ctx


# ---------------------------------------------------------------------------
# Strategy ABC
# ---------------------------------------------------------------------------

def test_strategy_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Strategy(ctx=MagicMock())


# ---------------------------------------------------------------------------
# SmaCrossover
# ---------------------------------------------------------------------------

def test_sma_crossover_lookback_default():
    ctx = _make_ctx()
    strat = SmaCrossover(ctx)
    # Default slow_period = 30
    assert strat.lookback() == 30


def test_sma_crossover_lookback_custom():
    ctx = _make_ctx()
    strat = SmaCrossover(ctx, params={"slow_period": 50, "fast_period": 20})
    assert strat.lookback() == 50


def test_sma_crossover_on_bar_generates_buy():
    """Feed a synthetic price panel where fast SMA crosses above slow SMA."""
    instrument = _make_instrument()
    universe = Universe(
        instruments={"BTC/USD": instrument},
        timeframe="1h",
    )

    # Build a mock broker that says no current position
    broker = MagicMock()
    broker.get_position.return_value = None

    ctx = _make_ctx(universe=universe, broker=broker)

    fast_period = 3
    slow_period = 5
    strat = SmaCrossover(ctx, params={
        "fast_period": fast_period,
        "slow_period": slow_period,
        "quantity": "1",
        "symbols": ["BTC/USD"],
    })

    # --- First call: establish prev_fast_above = False ---
    # Prices where fast < slow  (declining last 3 vs last 5)
    prices_down = [110, 108, 106, 104, 100]
    panel_down = _build_panel("BTC/USD", prices_down)
    orders = strat.on_bar(panel_down)
    # First call sets prev but no crossover yet
    assert orders == []

    # --- Second call: fast SMA now above slow SMA (crossover) ---
    # Prices where fast > slow  (recent prices jump up)
    prices_up = [100, 98, 96, 120, 130]
    panel_up = _build_panel("BTC/USD", prices_up)
    orders = strat.on_bar(panel_up)

    assert len(orders) == 1
    assert orders[0].side == OrderSide.BUY
    assert orders[0].type == OrderType.MARKET


def test_sma_crossover_on_bar_generates_sell():
    """Feed a synthetic price panel where fast SMA crosses below slow SMA."""
    instrument = _make_instrument()
    universe = Universe(
        instruments={"BTC/USD": instrument},
        timeframe="1h",
    )

    # Mock broker: has existing long position
    position = MagicMock()
    position.quantity = Decimal("1")
    broker = MagicMock()
    broker.get_position.return_value = position

    ctx = _make_ctx(universe=universe, broker=broker)

    fast_period = 3
    slow_period = 5
    strat = SmaCrossover(ctx, params={
        "fast_period": fast_period,
        "slow_period": slow_period,
        "quantity": "1",
        "symbols": ["BTC/USD"],
    })

    # First call: fast > slow
    prices_up = [100, 102, 104, 120, 130]
    orders = strat.on_bar(_build_panel("BTC/USD", prices_up))
    assert orders == []  # sets prev_fast_above = True

    # Second call: fast < slow (crossover down)
    prices_down = [130, 128, 126, 100, 90]
    orders = strat.on_bar(_build_panel("BTC/USD", prices_down))
    assert len(orders) == 1
    assert orders[0].side == OrderSide.SELL


def _build_panel(symbol: str, close_prices: list[float]) -> pd.DataFrame:
    """Build a MultiIndex DataFrame similar to PricePanel.get_window()."""
    n = len(close_prices)
    base_ts = datetime(2025, 1, 1, 0, 0)
    rows = []
    for i, c in enumerate(close_prices):
        rows.append({
            "timestamp": base_ts + timedelta(hours=i),
            "symbol": symbol,
            "open": float(c),
            "high": float(c) + 1.0,
            "low": float(c) - 1.0,
            "close": float(c),
            "volume": 100.0,
            "trades": 50,
            "vwap": float(c),
        })
    df = pd.DataFrame(rows)
    df = df.set_index(["timestamp", "symbol"]).sort_index()
    return df


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

def test_register_decorator():
    # The import of sma_crossover already registered it; verify
    assert "sma_crossover" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["sma_crossover"] is SmaCrossover


def test_get_strategy_known():
    cls = get_strategy("sma_crossover")
    assert cls is SmaCrossover


def test_get_strategy_unknown():
    with pytest.raises(KeyError, match="Unknown strategy"):
        get_strategy("nonexistent_strategy")


def test_list_strategies():
    names = list_strategies()
    assert isinstance(names, list)
    assert "sma_crossover" in names


def test_register_non_strategy_raises():
    with pytest.raises(TypeError, match="must be a subclass of Strategy"):
        @register("bad_strategy")
        class NotAStrategy:
            pass
