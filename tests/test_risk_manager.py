"""Tests for RiskManager — pre-trade validation and risk checks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from models.instrument import Instrument
from models.order import Order, OrderSide, OrderType
from risk.manager import RiskManager


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def instrument():
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


def _mock_broker(position=None):
    """Create a mock broker with optional existing position."""
    broker = MagicMock()
    broker.get_position.return_value = position
    return broker


# ---------------------------------------------------------------------------
# Position size limit
# ---------------------------------------------------------------------------

def test_order_within_position_size_limit_passes(instrument):
    rm = RiskManager(max_position_size=Decimal("5"))
    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=Decimal("3"),
    )
    broker = _mock_broker(position=None)  # no existing position
    assert rm.check(order, broker) is True


def test_order_exceeding_position_size_limit_fails(instrument):
    rm = RiskManager(max_position_size=Decimal("2"))
    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=Decimal("3"),
    )
    broker = _mock_broker(position=None)
    assert rm.check(order, broker) is False


def test_existing_position_plus_order_exceeds_limit(instrument):
    rm = RiskManager(max_position_size=Decimal("5"))

    existing = MagicMock()
    existing.quantity = Decimal("4")
    existing.side = OrderSide.BUY

    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=Decimal("3"),
    )
    broker = _mock_broker(position=existing)
    # new_qty = 4 + 3 = 7 > 5
    assert rm.check(order, broker) is False


# ---------------------------------------------------------------------------
# Max order value
# ---------------------------------------------------------------------------

def test_order_exceeding_max_order_value_fails(instrument):
    rm = RiskManager(
        max_position_size=Decimal("100"),
        max_order_value=Decimal("10000"),
    )
    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("50000"),  # notional = 50000 > 10000
    )
    broker = _mock_broker(position=None)
    assert rm.check(order, broker) is False


def test_order_within_max_order_value_passes(instrument):
    rm = RiskManager(
        max_position_size=Decimal("100"),
        max_order_value=Decimal("100000"),
    )
    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("50000"),
    )
    broker = _mock_broker(position=None)
    assert rm.check(order, broker) is True


def test_market_order_skips_notional_check(instrument):
    """Market orders have no price, so notional check is skipped."""
    rm = RiskManager(
        max_position_size=Decimal("100"),
        max_order_value=Decimal("1"),  # Tiny limit — but market has no price
    )
    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    broker = _mock_broker(position=None)
    assert rm.check(order, broker) is True


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def test_kill_switch_rejects_all_orders(instrument):
    rm = RiskManager()
    rm.kill_switch = True

    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=Decimal("0.01"),
    )
    broker = _mock_broker(position=None)
    assert rm.check(order, broker) is False


def test_kill_switch_off_allows_orders(instrument):
    rm = RiskManager()
    rm.kill_switch = False

    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=Decimal("0.01"),
    )
    broker = _mock_broker(position=None)
    assert rm.check(order, broker) is True


# ---------------------------------------------------------------------------
# Daily loss limit (attribute presence — enforcement is TODO in source)
# ---------------------------------------------------------------------------

def test_daily_loss_limit_attribute():
    rm = RiskManager(daily_loss_limit=Decimal("500"))
    assert rm.daily_loss_limit == Decimal("500")


def test_daily_loss_limit_defaults_to_none():
    rm = RiskManager()
    assert rm.daily_loss_limit is None
