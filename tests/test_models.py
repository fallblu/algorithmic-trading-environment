"""Tests for core data models."""

from datetime import datetime, timezone
from decimal import Decimal

from models.bar import Bar
from models.fill import Fill
from models.instrument import Instrument
from models.order import Order, OrderSide, OrderType, OrderStatus, TimeInForce
from models.position import Position
from models.account import Account


class TestBar:
    def test_creation(self):
        bar = Bar(
            instrument_symbol="BTC/USD",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=Decimal("50000"),
            high=Decimal("50500"),
            low=Decimal("49500"),
            close=Decimal("50200"),
            volume=Decimal("100"),
        )
        assert bar.instrument_symbol == "BTC/USD"
        assert bar.close == Decimal("50200")
        assert bar.trades is None
        assert bar.vwap is None

    def test_frozen(self):
        bar = Bar(
            instrument_symbol="BTC/USD",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=Decimal("50000"), high=Decimal("50500"),
            low=Decimal("49500"), close=Decimal("50200"),
            volume=Decimal("100"),
        )
        try:
            bar.close = Decimal("99999")
            assert False, "Should not allow mutation"
        except AttributeError:
            pass


class TestInstrument:
    def test_creation(self, btc_instrument):
        assert btc_instrument.symbol == "BTC/USD"
        assert btc_instrument.base == "BTC"
        assert btc_instrument.quote == "USD"
        assert btc_instrument.exchange == "kraken"

    def test_frozen(self, btc_instrument):
        try:
            btc_instrument.symbol = "ETH/USD"
            assert False, "Should not allow mutation"
        except AttributeError:
            pass


class TestOrder:
    def test_market_order(self, btc_instrument):
        order = Order(
            instrument=btc_instrument,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=Decimal("0.1"),
            strategy_id="test",
        )
        assert order.side == OrderSide.BUY
        assert order.type == OrderType.MARKET
        assert order.quantity == Decimal("0.1")
        assert order.status == OrderStatus.PENDING
        assert order.price is None
        assert order.tif == TimeInForce.GTC
        assert order.id  # UUID generated

    def test_limit_order(self, btc_instrument):
        order = Order(
            instrument=btc_instrument,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            quantity=Decimal("0.5"),
            price=Decimal("55000"),
            strategy_id="test",
        )
        assert order.price == Decimal("55000")
        assert order.type == OrderType.LIMIT

    def test_stop_order(self, btc_instrument):
        order = Order(
            instrument=btc_instrument,
            side=OrderSide.SELL,
            type=OrderType.STOP,
            quantity=Decimal("0.1"),
            stop_price=Decimal("48000"),
            strategy_id="test",
        )
        assert order.stop_price == Decimal("48000")

    def test_unique_ids(self, btc_instrument):
        o1 = Order(instrument=btc_instrument, side=OrderSide.BUY,
                   type=OrderType.MARKET, quantity=Decimal("1"))
        o2 = Order(instrument=btc_instrument, side=OrderSide.BUY,
                   type=OrderType.MARKET, quantity=Decimal("1"))
        assert o1.id != o2.id


class TestFill:
    def test_creation(self, btc_instrument):
        fill = Fill(
            order_id="abc-123",
            instrument=btc_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
            price=Decimal("50000"),
            fee=Decimal("5"),
            fee_currency="USD",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert fill.quantity == Decimal("0.1")
        assert fill.fee == Decimal("5")
        assert fill.is_maker is False
        assert fill.slippage == Decimal("0")


class TestPosition:
    def test_creation(self, btc_instrument):
        pos = Position(
            instrument=btc_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("0.5"),
            entry_price=Decimal("50000"),
        )
        assert pos.quantity == Decimal("0.5")
        assert pos.unrealized_pnl == Decimal("0")

    def test_update_unrealized_pnl_long(self, btc_instrument):
        pos = Position(
            instrument=btc_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
        )
        pos.update_unrealized_pnl(Decimal("52000"))
        assert pos.unrealized_pnl == Decimal("2000")

    def test_update_unrealized_pnl_short(self, btc_instrument):
        pos = Position(
            instrument=btc_instrument,
            side=OrderSide.SELL,
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
        )
        pos.update_unrealized_pnl(Decimal("48000"))
        assert pos.unrealized_pnl == Decimal("2000")

    def test_to_dict(self, btc_instrument):
        pos = Position(
            instrument=btc_instrument,
            side=OrderSide.BUY,
            quantity=Decimal("0.5"),
            entry_price=Decimal("50000"),
        )
        d = pos.to_dict()
        assert d["instrument_symbol"] == "BTC/USD"
        assert "quantity" in d


class TestAccount:
    def test_defaults(self):
        acc = Account()
        assert acc.equity == Decimal("0")
        assert acc.margin_used == Decimal("0")

    def test_to_dict(self):
        acc = Account(
            equity=Decimal("100000"),
            balances={"USD": Decimal("100000")},
        )
        d = acc.to_dict()
        assert str(d["equity"]) == "100000"
