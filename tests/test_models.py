from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal

import pytest

from models.bar import Bar, FundingRate
from models.instrument import FuturesInstrument, Instrument
from models.order import Order, OrderSide, OrderStatus, OrderType, TimeInForce
from models.fill import Fill
from models.position import Position
from models.account import Account


# ---------------------------------------------------------------------------
# Bar
# ---------------------------------------------------------------------------

class TestBar:
    def test_creation(self, sample_bar):
        assert sample_bar.instrument_symbol == "BTC/USD"
        assert sample_bar.open == Decimal("42000.00")
        assert sample_bar.high == Decimal("42500.00")
        assert sample_bar.low == Decimal("41800.00")
        assert sample_bar.close == Decimal("42300.00")
        assert sample_bar.volume == Decimal("150.5")
        assert sample_bar.trades == 1200
        assert sample_bar.vwap == Decimal("42150.00")

    def test_frozen(self, sample_bar):
        with pytest.raises(FrozenInstanceError):
            sample_bar.close = Decimal("99999")

    def test_optional_fields_default_none(self):
        bar = Bar(
            instrument_symbol="ETH/USD",
            timestamp=datetime(2024, 1, 1),
            open=Decimal("2000"),
            high=Decimal("2100"),
            low=Decimal("1900"),
            close=Decimal("2050"),
            volume=Decimal("500"),
        )
        assert bar.trades is None
        assert bar.vwap is None


# ---------------------------------------------------------------------------
# FundingRate
# ---------------------------------------------------------------------------

class TestFundingRate:
    def test_creation(self):
        now = datetime(2024, 1, 1, 8, 0, 0)
        next_time = datetime(2024, 1, 1, 16, 0, 0)
        fr = FundingRate(
            instrument_symbol="BTC-PERP",
            timestamp=now,
            rate=Decimal("0.0001"),
            next_funding_time=next_time,
        )
        assert fr.instrument_symbol == "BTC-PERP"
        assert fr.rate == Decimal("0.0001")
        assert fr.next_funding_time == next_time

    def test_frozen(self):
        fr = FundingRate(
            instrument_symbol="BTC-PERP",
            timestamp=datetime(2024, 1, 1),
            rate=Decimal("0.0001"),
            next_funding_time=datetime(2024, 1, 1, 8, 0, 0),
        )
        with pytest.raises(FrozenInstanceError):
            fr.rate = Decimal("0.001")


# ---------------------------------------------------------------------------
# Instrument / FuturesInstrument
# ---------------------------------------------------------------------------

class TestInstrument:
    def test_creation(self, sample_instrument):
        assert sample_instrument.symbol == "BTC/USD"
        assert sample_instrument.base == "BTC"
        assert sample_instrument.quote == "USD"
        assert sample_instrument.exchange == "kraken"
        assert sample_instrument.asset_class == "crypto"
        assert sample_instrument.tick_size == Decimal("0.01")
        assert sample_instrument.lot_size == Decimal("0.00001")
        assert sample_instrument.min_notional == Decimal("5")

    def test_frozen(self, sample_instrument):
        with pytest.raises(FrozenInstanceError):
            sample_instrument.symbol = "ETH/USD"


class TestFuturesInstrument:
    def test_creation(self, futures_instrument):
        assert futures_instrument.symbol == "BTC-PERP"
        assert futures_instrument.contract_type == "perpetual"
        assert futures_instrument.max_leverage == Decimal("50")
        assert futures_instrument.initial_margin_rate == Decimal("0.02")
        assert futures_instrument.maintenance_margin_rate == Decimal("0.01")
        assert futures_instrument.funding_interval_hours == 8
        assert futures_instrument.expiry is None

    def test_frozen(self, futures_instrument):
        with pytest.raises(FrozenInstanceError):
            futures_instrument.max_leverage = Decimal("200")

    def test_is_instrument_subclass(self, futures_instrument):
        assert isinstance(futures_instrument, Instrument)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TestEnums:
    def test_order_side_values(self):
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"
        assert len(OrderSide) == 2

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"
        assert OrderType.STOP.value == "STOP"
        assert OrderType.STOP_LIMIT.value == "STOP_LIMIT"
        assert len(OrderType) == 4

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "PENDING"
        assert OrderStatus.OPEN.value == "OPEN"
        assert OrderStatus.PARTIALLY_FILLED.value == "PARTIALLY_FILLED"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.CANCELLED.value == "CANCELLED"
        assert OrderStatus.REJECTED.value == "REJECTED"
        assert len(OrderStatus) == 6

    def test_time_in_force_values(self):
        assert TimeInForce.GTC.value == "GTC"
        assert TimeInForce.IOC.value == "IOC"
        assert TimeInForce.FOK.value == "FOK"
        assert TimeInForce.GTD.value == "GTD"
        assert len(TimeInForce) == 4


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------

class TestOrder:
    def test_creation(self, sample_instrument):
        order = Order(
            instrument=sample_instrument,
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            quantity=Decimal("0.5"),
            price=Decimal("42000"),
        )
        assert order.instrument is sample_instrument
        assert order.side == OrderSide.BUY
        assert order.type == OrderType.LIMIT
        assert order.quantity == Decimal("0.5")
        assert order.price == Decimal("42000")
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == Decimal("0")
        assert order.average_fill_price is None
        assert order.tif == TimeInForce.GTC
        assert order.id  # uuid is set

    def test_status_transitions(self, sample_instrument):
        order = Order(
            instrument=sample_instrument,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=Decimal("1"),
        )
        assert order.status == OrderStatus.PENDING

        order.status = OrderStatus.OPEN
        assert order.status == OrderStatus.OPEN

        order.status = OrderStatus.PARTIALLY_FILLED
        order.filled_quantity = Decimal("0.5")
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == Decimal("0.5")

        order.status = OrderStatus.FILLED
        order.filled_quantity = Decimal("1")
        order.average_fill_price = Decimal("42100")
        assert order.status == OrderStatus.FILLED
        assert order.average_fill_price == Decimal("42100")

    def test_cancelled_status(self, sample_instrument):
        order = Order(
            instrument=sample_instrument,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            quantity=Decimal("2"),
            price=Decimal("50000"),
        )
        order.status = OrderStatus.CANCELLED
        assert order.status == OrderStatus.CANCELLED

    def test_metadata(self, sample_instrument):
        order = Order(
            instrument=sample_instrument,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=Decimal("1"),
            metadata={"reason": "momentum_signal", "confidence": 0.85},
        )
        assert order.metadata["reason"] == "momentum_signal"
        assert order.metadata["confidence"] == 0.85

    def test_default_metadata_empty(self, sample_instrument):
        order = Order(
            instrument=sample_instrument,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=Decimal("1"),
        )
        assert order.metadata == {}

    def test_unique_ids(self, sample_instrument):
        order1 = Order(
            instrument=sample_instrument,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=Decimal("1"),
        )
        order2 = Order(
            instrument=sample_instrument,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=Decimal("1"),
        )
        assert order1.id != order2.id


# ---------------------------------------------------------------------------
# Fill
# ---------------------------------------------------------------------------

class TestFill:
    def test_creation(self, sample_instrument):
        fill = Fill(
            order_id="abc-123",
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("0.5"),
            price=Decimal("42000"),
            fee=Decimal("0.26"),
            fee_currency="USD",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
        )
        assert fill.order_id == "abc-123"
        assert fill.instrument is sample_instrument
        assert fill.side == OrderSide.BUY
        assert fill.quantity == Decimal("0.5")
        assert fill.price == Decimal("42000")
        assert fill.fee == Decimal("0.26")
        assert fill.fee_currency == "USD"
        assert fill.is_maker is False
        assert fill.slippage == Decimal("0")

    def test_frozen(self, sample_instrument):
        fill = Fill(
            order_id="abc-123",
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("0.5"),
            price=Decimal("42000"),
            fee=Decimal("0.26"),
            fee_currency="USD",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
        )
        with pytest.raises(FrozenInstanceError):
            fill.price = Decimal("99999")

    def test_maker_fill(self, sample_instrument):
        fill = Fill(
            order_id="xyz-789",
            instrument=sample_instrument,
            side=OrderSide.SELL,
            quantity=Decimal("1"),
            price=Decimal("43000"),
            fee=Decimal("0.10"),
            fee_currency="USD",
            timestamp=datetime(2024, 1, 1, 13, 0, 0),
            is_maker=True,
            slippage=Decimal("-0.5"),
        )
        assert fill.is_maker is True
        assert fill.slippage == Decimal("-0.5")


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

class TestPosition:
    def test_creation(self, sample_instrument):
        pos = Position(
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("1.5"),
            entry_price=Decimal("42000"),
        )
        assert pos.instrument is sample_instrument
        assert pos.side == OrderSide.BUY
        assert pos.quantity == Decimal("1.5")
        assert pos.entry_price == Decimal("42000")
        assert pos.unrealized_pnl == Decimal("0")
        assert pos.realized_pnl == Decimal("0")

    def test_update_unrealized_pnl_long(self, sample_instrument):
        pos = Position(
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("2"),
            entry_price=Decimal("40000"),
        )
        pos.update_unrealized_pnl(Decimal("42000"))
        assert pos.unrealized_pnl == Decimal("4000")  # (42000 - 40000) * 2

    def test_update_unrealized_pnl_short(self, sample_instrument):
        pos = Position(
            instrument=sample_instrument,
            side=OrderSide.SELL,
            quantity=Decimal("3"),
            entry_price=Decimal("42000"),
        )
        pos.update_unrealized_pnl(Decimal("40000"))
        assert pos.unrealized_pnl == Decimal("6000")  # (42000 - 40000) * 3

    def test_update_unrealized_pnl_zero_quantity(self, sample_instrument):
        pos = Position(
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("0"),
            entry_price=Decimal("42000"),
        )
        pos.unrealized_pnl = Decimal("999")  # set to something nonzero
        pos.update_unrealized_pnl(Decimal("50000"))
        assert pos.unrealized_pnl == Decimal("0")

    def test_to_dict(self, sample_instrument):
        pos = Position(
            instrument=sample_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            entry_price=Decimal("42000"),
        )
        d = pos.to_dict()
        assert d["instrument_symbol"] == "BTC/USD"
        assert d["side"] == "BUY"
        assert d["quantity"] == "1"
        assert d["entry_price"] == "42000"
        assert d["unrealized_pnl"] == "0"
        assert d["realized_pnl"] == "0"
        assert "opened_at" in d
        assert "last_updated" in d


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

class TestAccount:
    def test_creation_defaults(self):
        account = Account()
        assert account.balances == {}
        assert account.equity == Decimal("0")
        assert account.margin_used == Decimal("0")
        assert account.margin_available == Decimal("0")
        assert account.unrealized_pnl == Decimal("0")
        assert account.realized_pnl == Decimal("0")
        assert account.daily_pnl == Decimal("0")
        assert account.max_drawdown == Decimal("0")

    def test_update_equity(self):
        account = Account(
            balances={"USD": Decimal("10000"), "BTC": Decimal("5000")},
            unrealized_pnl=Decimal("500"),
        )
        account.update_equity()
        assert account.equity == Decimal("15500")  # 10000 + 5000 + 500

    def test_update_equity_with_negative_pnl(self):
        account = Account(
            balances={"USD": Decimal("10000")},
            unrealized_pnl=Decimal("-2000"),
        )
        account.update_equity()
        assert account.equity == Decimal("8000")

    def test_update_equity_empty_balances(self):
        account = Account(unrealized_pnl=Decimal("100"))
        account.update_equity()
        assert account.equity == Decimal("100")

    def test_to_dict(self):
        account = Account(
            balances={"USD": Decimal("10000")},
            equity=Decimal("10500"),
            margin_used=Decimal("2000"),
            unrealized_pnl=Decimal("500"),
            realized_pnl=Decimal("300"),
            daily_pnl=Decimal("150"),
            max_drawdown=Decimal("0.05"),
        )
        d = account.to_dict()
        assert d["balances"] == {"USD": "10000"}
        assert d["equity"] == "10500"
        assert d["margin_used"] == "2000"
        assert d["unrealized_pnl"] == "500"
        assert d["realized_pnl"] == "300"
        assert d["daily_pnl"] == "150"
        assert d["max_drawdown"] == "0.05"
