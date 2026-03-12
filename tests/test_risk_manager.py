"""Tests for RiskManager — pre-trade check pipeline."""

from decimal import Decimal

import pytest

from broker.simulated import SimulatedBroker
from models.order import Order, OrderSide, OrderType
from risk.manager import RiskManager, RiskCheckResult
from tests.conftest import make_bar


class TestKillSwitch:
    def test_kill_switch_rejects_all(self, btc_instrument, broker):
        rm = RiskManager(max_position_size=Decimal("10"))
        rm.kill_switch = True

        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.1"))
        assert rm.check(order, broker) is False

    def test_reset_kill_switch(self, btc_instrument, broker):
        rm = RiskManager(max_position_size=Decimal("10"))
        rm.kill_switch = True
        rm.reset_kill_switch()
        assert rm.kill_switch is False

        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.1"))
        assert rm.check(order, broker) is True


class TestPositionSizeLimit:
    def test_rejects_oversized_order(self, btc_instrument, broker):
        rm = RiskManager(max_position_size=Decimal("0.5"))
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("1.0"))
        assert rm.check(order, broker) is False

    def test_accepts_within_limit(self, btc_instrument, broker):
        rm = RiskManager(max_position_size=Decimal("1.0"))
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.5"))
        assert rm.check(order, broker) is True


class TestOrderNotional:
    def test_rejects_high_notional(self, btc_instrument, broker):
        rm = RiskManager(
            max_position_size=Decimal("100"),
            max_order_value=Decimal("10000"),
        )
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.LIMIT, quantity=Decimal("1"),
                      price=Decimal("50000"))
        # notional = 1 * 50000 = 50000 > 10000
        assert rm.check(order, broker) is False

    def test_market_orders_pass_notional(self, btc_instrument, broker):
        rm = RiskManager(
            max_position_size=Decimal("100"),
            max_order_value=Decimal("10000"),
        )
        # Market orders have no price, so notional check is skipped
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("1"))
        assert rm.check(order, broker) is True


class TestCheckAll:
    def test_returns_list_of_results(self, btc_instrument, broker):
        rm = RiskManager(max_position_size=Decimal("1.0"))
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.1"))
        results = rm.check_all(order, broker)
        assert isinstance(results, list)
        assert all(isinstance(r, RiskCheckResult) for r in results)
        assert all(r.passed for r in results)

    def test_failed_check_in_results(self, btc_instrument, broker):
        rm = RiskManager(max_position_size=Decimal("0.01"))
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("1"))
        results = rm.check_all(order, broker)
        failed = [r for r in results if not r.passed]
        assert len(failed) >= 1
        assert any("position" in r.check_name.lower() for r in failed)


class TestDailyLoss:
    def test_daily_loss_triggers_kill_switch(self, btc_instrument):
        broker = SimulatedBroker(
            initial_cash=Decimal("100000"),
            fee_rate=Decimal("0"),
            slippage_pct=Decimal("0"),
        )
        rm = RiskManager(
            max_position_size=Decimal("10"),
            daily_loss_limit=Decimal("-100"),
        )

        # Initialize session start equity
        dummy = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.001"))
        rm.check_all(dummy, broker)  # Sets _session_start_equity = 100000

        # Buy 1 BTC at open price ~50000
        broker.submit_order(Order(instrument=btc_instrument, side=OrderSide.BUY,
                                  type=OrderType.MARKET, quantity=Decimal("1")))
        broker.process_bar(make_bar("BTC/USD", open_=50000, close=50000))

        # Sell at lower price — lose $500
        broker.submit_order(Order(instrument=btc_instrument, side=OrderSide.SELL,
                                  type=OrderType.MARKET, quantity=Decimal("1")))
        from datetime import datetime, timezone
        broker.process_bar(make_bar("BTC/USD", open_=49500, close=49500,
                                    high=49500, low=49500,
                                    timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc)))

        # After losing ~$500, daily loss limit of -100 should be breached
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.1"))
        results = rm.check_all(order, broker)
        daily_checks = [r for r in results if "daily" in r.check_name.lower()]
        assert len(daily_checks) >= 1
        assert not daily_checks[0].passed


class TestResetDaily:
    def test_reset_clears_daily_tracking(self, btc_instrument, broker):
        rm = RiskManager(
            max_position_size=Decimal("10"),
            daily_loss_limit=Decimal("-100"),
        )
        rm.reset_daily()
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.1"))
        assert rm.check(order, broker) is True


class TestRiskConfig:
    def test_construct_from_risk_config(self, btc_instrument, broker):
        from config import RiskConfig
        config = RiskConfig(
            max_position_size=Decimal("2.0"),
            max_order_value=Decimal("50000"),
            daily_loss_limit=Decimal("-200"),
            max_drawdown_limit=Decimal("0.10"),
            max_concentration_pct=Decimal("0.30"),
        )
        rm = RiskManager(risk_config=config)
        assert rm.max_position_size == Decimal("2.0")
        assert rm.max_order_value == Decimal("50000")
        assert rm.daily_loss_limit == Decimal("-200")
        assert rm.max_drawdown_limit == Decimal("0.10")

        # Should accept orders within the config limits
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("1.5"))
        assert rm.check(order, broker) is True

    def test_risk_config_overrides_individual_params(self, btc_instrument, broker):
        from config import RiskConfig
        config = RiskConfig(max_position_size=Decimal("0.5"))
        rm = RiskManager(max_position_size=Decimal("100"), risk_config=config)
        # risk_config should win
        assert rm.max_position_size == Decimal("0.5")

        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("1.0"))
        assert rm.check(order, broker) is False


class TestDrawdown:
    def test_drawdown_rejects_when_exceeded(self, btc_instrument):
        broker = SimulatedBroker(
            initial_cash=Decimal("100000"),
            fee_rate=Decimal("0"),
            slippage_pct=Decimal("0"),
        )
        rm = RiskManager(
            max_position_size=Decimal("10"),
            max_drawdown_limit=Decimal("0.05"),  # 5% max drawdown
        )
        # Set HWM to 100000
        rm.update_high_water_mark(Decimal("100000"))

        # Simulate equity drop to 94000 (6% drawdown > 5% limit)
        # We need to manipulate the broker's account equity
        broker._account.equity = Decimal("94000")

        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.1"))
        results = rm.check_all(order, broker)
        dd_checks = [r for r in results if r.check_name == "drawdown"]
        assert len(dd_checks) == 1
        assert not dd_checks[0].passed

    def test_drawdown_passes_within_limit(self, btc_instrument):
        broker = SimulatedBroker(
            initial_cash=Decimal("100000"),
            fee_rate=Decimal("0"),
            slippage_pct=Decimal("0"),
        )
        rm = RiskManager(
            max_position_size=Decimal("10"),
            max_drawdown_limit=Decimal("0.10"),  # 10% max drawdown
        )
        rm.update_high_water_mark(Decimal("100000"))

        # 3% drawdown — within limit
        broker._account.equity = Decimal("97000")

        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.1"))
        results = rm.check_all(order, broker)
        dd_checks = [r for r in results if r.check_name == "drawdown"]
        assert len(dd_checks) == 1
        assert dd_checks[0].passed

    def test_drawdown_auto_updates_hwm(self, btc_instrument, broker):
        rm = RiskManager(
            max_position_size=Decimal("10"),
            max_drawdown_limit=Decimal("0.10"),
        )
        # With initial equity of 100000 and no HWM set (starts at 0),
        # the first check should update HWM to current equity
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.1"))
        rm.check_all(order, broker)
        assert rm._high_water_mark == Decimal("100000")
