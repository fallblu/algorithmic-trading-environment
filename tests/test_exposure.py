"""Tests for ExposureManager — portfolio-level exposure limits."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from broker.simulated import SimulatedBroker
from models.order import Order, OrderSide, OrderType
from risk.exposure import ExposureManager, ExposureCheckResult
from tests.conftest import make_bar


@pytest.fixture
def exposure_mgr():
    return ExposureManager(
        max_gross_exposure=Decimal("100000"),
        max_net_exposure=Decimal("50000"),
        max_concentration_pct=Decimal("0.5"),
    )


class TestConcentration:
    def test_rejects_concentrated_position(self, btc_instrument):
        broker = SimulatedBroker(initial_cash=Decimal("10000"), fee_rate=Decimal("0"))
        mgr = ExposureManager(max_concentration_pct=Decimal("0.25"))

        # Order that would be 50% of equity
        order = Order(
            instrument=btc_instrument, side=OrderSide.BUY,
            type=OrderType.LIMIT, quantity=Decimal("0.1"),
            price=Decimal("50000"),  # notional = 5000, 50% of 10000
        )
        result = mgr.check_order(order, broker)
        assert not result.passed
        assert "concentration" in result.reason.lower() or "Concentration" in result.reason

    def test_allows_small_position(self, btc_instrument):
        broker = SimulatedBroker(initial_cash=Decimal("100000"), fee_rate=Decimal("0"))
        mgr = ExposureManager(max_concentration_pct=Decimal("0.5"))

        order = Order(
            instrument=btc_instrument, side=OrderSide.BUY,
            type=OrderType.LIMIT, quantity=Decimal("0.1"),
            price=Decimal("50000"),  # notional = 5000, 5% of 100000
        )
        result = mgr.check_order(order, broker)
        assert result.passed


class TestGrossExposure:
    def test_rejects_over_gross_limit(self, btc_instrument):
        broker = SimulatedBroker(initial_cash=Decimal("200000"), fee_rate=Decimal("0"))
        mgr = ExposureManager(
            max_gross_exposure=Decimal("60000"),
            max_concentration_pct=Decimal("1.0"),  # No concentration limit
        )

        # First fill a position
        broker.submit_order(Order(
            instrument=btc_instrument, side=OrderSide.BUY,
            type=OrderType.MARKET, quantity=Decimal("1"),
        ))
        broker.process_bar(make_bar("BTC/USD", close=50000))

        # Now try to add more — gross would be 50000 + 20000 = 70000 > 60000
        order = Order(
            instrument=btc_instrument, side=OrderSide.BUY,
            type=OrderType.LIMIT, quantity=Decimal("0.4"),
            price=Decimal("50000"),  # notional = 20000
        )
        result = mgr.check_order(order, broker)
        assert not result.passed


class TestMarketOrderBypass:
    def test_market_order_passes_without_price(self, btc_instrument):
        broker = SimulatedBroker(initial_cash=Decimal("10000"), fee_rate=Decimal("0"))
        mgr = ExposureManager(max_concentration_pct=Decimal("0.1"))

        order = Order(
            instrument=btc_instrument, side=OrderSide.BUY,
            type=OrderType.MARKET, quantity=Decimal("1"),
        )
        result = mgr.check_order(order, broker)
        assert result.passed  # Market orders skip notional checks


class TestReducingPosition:
    def test_sell_always_allowed(self, btc_instrument):
        broker = SimulatedBroker(initial_cash=Decimal("100000"), fee_rate=Decimal("0"))
        mgr = ExposureManager(max_concentration_pct=Decimal("0.01"))

        # Open position
        broker.submit_order(Order(
            instrument=btc_instrument, side=OrderSide.BUY,
            type=OrderType.MARKET, quantity=Decimal("1"),
        ))
        broker.process_bar(make_bar("BTC/USD", close=50000))

        # Selling (reducing) should always pass concentration check
        order = Order(
            instrument=btc_instrument, side=OrderSide.SELL,
            type=OrderType.LIMIT, quantity=Decimal("0.5"),
            price=Decimal("51000"),
        )
        result = mgr.check_order(order, broker)
        assert result.passed
