"""Tests for PositionManager — position lifecycle operations."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from broker.position_manager import PositionManager
from models.account import Account
from models.fill import Fill
from models.order import OrderSide


class TestOpenPosition:
    def test_open_long(self, btc_instrument):
        account = Account(
            balances={"USD": Decimal("100000")},
            equity=Decimal("100000"),
            margin_available=Decimal("100000"),
        )
        pm = PositionManager(account)

        fill = Fill(
            order_id="1", instrument=btc_instrument, side=OrderSide.BUY,
            quantity=Decimal("0.5"), price=Decimal("50000"),
            fee=Decimal("25"), fee_currency="USD",
            timestamp=datetime.now(timezone.utc),
        )
        pm.apply_fill(fill)

        pos = pm.get_position("BTC/USD")
        assert pos is not None
        assert pos.quantity == Decimal("0.5")
        assert pos.side == OrderSide.BUY
        assert pos.entry_price == Decimal("50000")

    def test_open_short(self, btc_instrument):
        account = Account(
            balances={"USD": Decimal("100000")},
            equity=Decimal("100000"),
            margin_available=Decimal("100000"),
        )
        pm = PositionManager(account)

        fill = Fill(
            order_id="1", instrument=btc_instrument, side=OrderSide.SELL,
            quantity=Decimal("0.5"), price=Decimal("50000"),
            fee=Decimal("25"), fee_currency="USD",
            timestamp=datetime.now(timezone.utc),
        )
        pm.apply_fill(fill)

        pos = pm.get_position("BTC/USD")
        assert pos is not None
        assert pos.side == OrderSide.SELL


class TestAddToPosition:
    def test_add_to_long_averages_price(self, btc_instrument):
        account = Account(
            balances={"USD": Decimal("100000")},
            equity=Decimal("100000"),
            margin_available=Decimal("100000"),
        )
        pm = PositionManager(account)

        fill1 = Fill(
            order_id="1", instrument=btc_instrument, side=OrderSide.BUY,
            quantity=Decimal("1"), price=Decimal("50000"),
            fee=Decimal("50"), fee_currency="USD",
            timestamp=datetime.now(timezone.utc),
        )
        pm.apply_fill(fill1)

        fill2 = Fill(
            order_id="2", instrument=btc_instrument, side=OrderSide.BUY,
            quantity=Decimal("1"), price=Decimal("52000"),
            fee=Decimal("52"), fee_currency="USD",
            timestamp=datetime.now(timezone.utc),
        )
        pm.apply_fill(fill2)

        pos = pm.get_position("BTC/USD")
        assert pos.quantity == Decimal("2")
        # Weighted avg: (1*50000 + 1*52000) / 2 = 51000
        assert pos.entry_price == Decimal("51000")


class TestReducePosition:
    def test_partial_close_long(self, btc_instrument):
        account = Account(
            balances={"USD": Decimal("100000")},
            equity=Decimal("100000"),
            margin_available=Decimal("100000"),
        )
        pm = PositionManager(account)

        # Open
        pm.apply_fill(Fill(
            order_id="1", instrument=btc_instrument, side=OrderSide.BUY,
            quantity=Decimal("1"), price=Decimal("50000"),
            fee=Decimal("50"), fee_currency="USD",
            timestamp=datetime.now(timezone.utc),
        ))

        # Partial close
        pm.apply_fill(Fill(
            order_id="2", instrument=btc_instrument, side=OrderSide.SELL,
            quantity=Decimal("0.5"), price=Decimal("52000"),
            fee=Decimal("26"), fee_currency="USD",
            timestamp=datetime.now(timezone.utc),
        ))

        pos = pm.get_position("BTC/USD")
        assert pos is not None
        assert pos.quantity == Decimal("0.5")
        # PnL from closing 0.5 @ 52000 (entry 50000): 0.5 * 2000 = 1000
        assert pos.realized_pnl > Decimal("0")


class TestClosePosition:
    def test_full_close_long(self, btc_instrument):
        account = Account(
            balances={"USD": Decimal("100000")},
            equity=Decimal("100000"),
            margin_available=Decimal("100000"),
        )
        pm = PositionManager(account)

        pm.apply_fill(Fill(
            order_id="1", instrument=btc_instrument, side=OrderSide.BUY,
            quantity=Decimal("1"), price=Decimal("50000"),
            fee=Decimal("50"), fee_currency="USD",
            timestamp=datetime.now(timezone.utc),
        ))

        pm.apply_fill(Fill(
            order_id="2", instrument=btc_instrument, side=OrderSide.SELL,
            quantity=Decimal("1"), price=Decimal("52000"),
            fee=Decimal("52"), fee_currency="USD",
            timestamp=datetime.now(timezone.utc),
        ))

        pos = pm.get_position("BTC/USD")
        assert pos is None or pos.quantity == Decimal("0")

    def test_get_open_positions_excludes_closed(self, btc_instrument):
        account = Account(
            balances={"USD": Decimal("100000")},
            equity=Decimal("100000"),
            margin_available=Decimal("100000"),
        )
        pm = PositionManager(account)

        pm.apply_fill(Fill(
            order_id="1", instrument=btc_instrument, side=OrderSide.BUY,
            quantity=Decimal("1"), price=Decimal("50000"),
            fee=Decimal("0"), fee_currency="USD",
            timestamp=datetime.now(timezone.utc),
        ))

        assert len(pm.get_open_positions()) == 1

        pm.apply_fill(Fill(
            order_id="2", instrument=btc_instrument, side=OrderSide.SELL,
            quantity=Decimal("1"), price=Decimal("51000"),
            fee=Decimal("0"), fee_currency="USD",
            timestamp=datetime.now(timezone.utc),
        ))

        assert len(pm.get_open_positions()) == 0
