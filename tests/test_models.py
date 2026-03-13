from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from models.bar import Bar
from models.order import Order, OrderSide, OrderStatus, OrderType
from models.fill import Fill
from models.position import Position, PositionSide
from models.instrument import Instrument, get_instrument


# ---------------------------------------------------------------------------
# Bar
# ---------------------------------------------------------------------------

class TestBar:
    def test_bar_creation(self):
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        bar = Bar(
            symbol="BTC/USD",
            timestamp=ts,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42200.0,
            volume=100.0,
        )
        assert bar.symbol == "BTC/USD"
        assert bar.timestamp == ts
        assert bar.open == 42000.0
        assert bar.high == 42500.0
        assert bar.low == 41800.0
        assert bar.close == 42200.0
        assert bar.volume == 100.0

    def test_bar_frozen_immutability(self):
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        bar = Bar(
            symbol="BTC/USD",
            timestamp=ts,
            open=42000.0,
            high=42500.0,
            low=41800.0,
            close=42200.0,
            volume=100.0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            bar.close = 99999.0

        with pytest.raises(dataclasses.FrozenInstanceError):
            bar.symbol = "ETH/USD"


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------

class TestOrder:
    def test_order_creation_with_defaults(self):
        order = Order(
            symbol="ETH/USD",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=1.5,
        )
        assert order.symbol == "ETH/USD"
        assert order.side == OrderSide.BUY
        assert order.type == OrderType.MARKET
        assert order.quantity == 1.5
        assert order.price is None
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == 0.0
        assert order.fill_price is None
        assert order.strategy_id == ""
        assert order.id  # non-empty uuid
        assert order.created_at.tzinfo is not None  # timezone-aware

    def test_order_side_enum(self):
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"
        assert OrderSide("BUY") is OrderSide.BUY

    def test_order_type_enum(self):
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"
        assert OrderType("LIMIT") is OrderType.LIMIT

    def test_order_with_limit_price(self):
        order = Order(
            symbol="BTC/USD",
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            quantity=0.5,
            price=50000.0,
        )
        assert order.price == 50000.0
        assert order.type == OrderType.LIMIT
        assert order.side == OrderSide.SELL

    def test_order_unique_ids(self):
        o1 = Order(symbol="BTC/USD", side=OrderSide.BUY, type=OrderType.MARKET, quantity=1.0)
        o2 = Order(symbol="BTC/USD", side=OrderSide.BUY, type=OrderType.MARKET, quantity=1.0)
        assert o1.id != o2.id


# ---------------------------------------------------------------------------
# Fill
# ---------------------------------------------------------------------------

class TestFill:
    def test_fill_creation(self):
        ts = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        fill = Fill(
            order_id="order-123",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            quantity=0.5,
            price=42000.0,
            fee=54.6,
            timestamp=ts,
            strategy_id="sma",
            slippage=4.2,
        )
        assert fill.order_id == "order-123"
        assert fill.symbol == "BTC/USD"
        assert fill.side == OrderSide.BUY
        assert fill.quantity == 0.5
        assert fill.price == 42000.0
        assert fill.fee == 54.6
        assert fill.timestamp == ts
        assert fill.strategy_id == "sma"
        assert fill.slippage == 4.2

    def test_fill_defaults(self):
        ts = datetime(2024, 6, 15, tzinfo=timezone.utc)
        fill = Fill(
            order_id="o1",
            symbol="ETH/USD",
            side=OrderSide.SELL,
            quantity=10.0,
            price=3000.0,
            fee=7.8,
            timestamp=ts,
        )
        assert fill.strategy_id == ""
        assert fill.slippage == 0.0

    def test_fill_frozen_immutability(self):
        ts = datetime(2024, 6, 15, tzinfo=timezone.utc)
        fill = Fill(
            order_id="o1",
            symbol="ETH/USD",
            side=OrderSide.SELL,
            quantity=10.0,
            price=3000.0,
            fee=7.8,
            timestamp=ts,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            fill.price = 9999.0


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

class TestPosition:
    def test_position_creation(self):
        pos = Position(symbol="BTC/USD", side=PositionSide.LONG, quantity=1.0)
        assert pos.symbol == "BTC/USD"
        assert pos.side == PositionSide.LONG
        assert pos.quantity == 1.0
        assert pos.avg_entry_price == 0.0
        assert pos.unrealized_pnl == 0.0
        assert pos.realized_pnl == 0.0
        assert pos.strategy_id == ""
        assert pos.opened_at.tzinfo is not None

    def test_position_side_enum(self):
        assert PositionSide.LONG.value == "LONG"
        assert PositionSide.SHORT.value == "SHORT"
        assert PositionSide.FLAT.value == "FLAT"
        assert PositionSide("LONG") is PositionSide.LONG

    def test_position_is_mutable(self):
        pos = Position(symbol="BTC/USD", side=PositionSide.LONG, quantity=1.0)
        pos.quantity = 2.0
        assert pos.quantity == 2.0
        pos.unrealized_pnl = 500.0
        assert pos.unrealized_pnl == 500.0


# ---------------------------------------------------------------------------
# Instrument
# ---------------------------------------------------------------------------

class TestInstrument:
    def test_instrument_creation(self):
        inst = Instrument(symbol="BTC/USD", exchange="kraken")
        assert inst.symbol == "BTC/USD"
        assert inst.exchange == "kraken"
        assert inst.tick_size == 0.01
        assert inst.lot_size == 0.001
        assert inst.min_notional == 10.0

    def test_instrument_custom_params(self):
        inst = Instrument(
            symbol="EUR/USD",
            exchange="oanda",
            tick_size=0.00001,
            lot_size=1.0,
            min_notional=1.0,
        )
        assert inst.tick_size == 0.00001
        assert inst.lot_size == 1.0
        assert inst.min_notional == 1.0

    def test_get_instrument_known_symbol(self):
        inst = get_instrument("BTC/USD")
        assert inst.symbol == "BTC/USD"
        assert inst.exchange == "kraken"
        assert inst.tick_size == 0.1

    def test_get_instrument_known_forex(self):
        inst = get_instrument("EUR/USD")
        assert inst.symbol == "EUR/USD"
        assert inst.exchange == "oanda"

    def test_get_instrument_unknown_symbol_returns_default(self):
        inst = get_instrument("UNKNOWN/PAIR")
        assert inst.symbol == "UNKNOWN/PAIR"
        # Unknown non-crypto defaults to oanda
        assert inst.exchange == "oanda"
        assert inst.tick_size == 0.01  # default
