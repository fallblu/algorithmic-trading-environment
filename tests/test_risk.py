from __future__ import annotations

from datetime import datetime, timezone

import pytest

from broker.base import Account
from broker.simulated import SimulatedBroker
from models.bar import Bar
from models.order import Order, OrderSide, OrderType
from risk.manager import RiskManager
from risk.rules import RiskConfig, RiskLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bar(
    symbol: str = "BTC/USD",
    open_: float = 100.0,
    high: float = 110.0,
    low: float = 90.0,
    close: float = 105.0,
    ts: datetime | None = None,
) -> Bar:
    if ts is None:
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return Bar(symbol=symbol, timestamp=ts, open=open_, high=high, low=low, close=close, volume=1000.0)


def make_order(
    symbol: str = "BTC/USD",
    side: OrderSide = OrderSide.BUY,
    quantity: float = 1.0,
    price: float | None = None,
) -> Order:
    otype = OrderType.LIMIT if price else OrderType.MARKET
    return Order(symbol=symbol, side=side, type=otype, quantity=quantity, price=price)


# ---------------------------------------------------------------------------
# RiskManager
# ---------------------------------------------------------------------------

class TestRiskManagerOrderChecks:
    def test_order_allowed_within_limits(self):
        config = RiskConfig(max_position_pct=0.5)
        mgr = RiskManager(config)
        broker = SimulatedBroker(initial_cash=100_000.0, fee_rate=0.0, slippage_pct=0.0)

        order = make_order(price=1000.0, quantity=10.0)  # 10k / 100k = 10%
        allowed, reason = mgr.check_order(order, broker)
        assert allowed is True

    def test_order_blocked_exceeds_position_pct(self):
        config = RiskConfig(max_position_pct=0.10)
        mgr = RiskManager(config)
        broker = SimulatedBroker(initial_cash=100_000.0, fee_rate=0.0, slippage_pct=0.0)

        # 20% position -> exceeds 10% limit
        order = make_order(price=1000.0, quantity=20.0)  # 20k / 100k = 20%
        allowed, reason = mgr.check_order(order, broker)
        assert allowed is False
        assert "position" in reason.lower() or "Position" in reason

    def test_kill_switch_blocks_all_orders(self):
        config = RiskConfig()
        mgr = RiskManager(config)
        mgr._kill_switch = True

        broker = SimulatedBroker(initial_cash=100_000.0)
        order = make_order(price=10.0, quantity=1.0)
        allowed, reason = mgr.check_order(order, broker)
        assert allowed is False
        assert "kill switch" in reason.lower()

    def test_kill_switch_reset(self):
        config = RiskConfig()
        mgr = RiskManager(config)
        mgr._kill_switch = True
        mgr.reset_kill_switch()
        assert mgr.kill_switch_active is False


class TestRiskManagerPortfolioChecks:
    def test_drawdown_triggers_kill_switch(self):
        config = RiskConfig(max_drawdown_pct=0.10)
        mgr = RiskManager(config)
        broker = SimulatedBroker(initial_cash=100_000.0, fee_rate=0.0, slippage_pct=0.0)

        # Set peak equity high
        mgr._peak_equity = 100_000.0

        # Simulate loss: buy at 100, price drops to 1 (big unrealized loss)
        order = make_order(quantity=500.0)
        broker.submit_order(order)
        broker.process_bar(make_bar(open_=100.0, close=80.0))

        violations = mgr.check_portfolio(broker)
        # With 500 units bought at 100 = 50000 cost, close at 80 -> unrealized = (80-100)*500 = -10000
        # equity = cash + unrealized = 50000 + (-10000) = 40000... let's check

        # Actually: cash = 100000 - 100*500 = 50000, unrealized = (80-100)*500 = -10000, equity = 40000
        # Drawdown from peak 100000: (100000-40000)/100000 = 60% > 10%
        assert mgr.kill_switch_active is True
        assert any(v.level == RiskLevel.CRITICAL for v in violations)
