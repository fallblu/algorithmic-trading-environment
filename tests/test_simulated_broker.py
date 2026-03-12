"""Tests for SimulatedBroker — order submission, fills, position tracking."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from broker.simulated import SimulatedBroker
from models.bar import Bar
from models.order import Order, OrderSide, OrderType, OrderStatus
from tests.conftest import make_bar


class TestSubmitOrder:
    def test_submit_market_order(self, broker, btc_instrument):
        order = Order(
            instrument=btc_instrument,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )
        submitted = broker.submit_order(order)
        assert submitted.status in (OrderStatus.OPEN, OrderStatus.PENDING)

    def test_submit_limit_order(self, broker, btc_instrument):
        order = Order(
            instrument=btc_instrument,
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            price=Decimal("45000"),
        )
        submitted = broker.submit_order(order)
        open_orders = broker.get_open_orders()
        assert len(open_orders) >= 1

    def test_cancel_order(self, broker, btc_instrument):
        order = Order(
            instrument=btc_instrument,
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            price=Decimal("45000"),
        )
        submitted = broker.submit_order(order)
        cancelled = broker.cancel_order(submitted.id)
        assert cancelled.status == OrderStatus.CANCELLED


class TestMarketFills:
    def test_market_buy_fills_on_next_bar(self, broker, btc_instrument):
        order = Order(
            instrument=btc_instrument,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )
        broker.submit_order(order)

        bar = make_bar("BTC/USD", close=50000)
        fills = broker.process_bar(bar)
        assert len(fills) == 1
        assert fills[0].side == OrderSide.BUY
        assert fills[0].quantity == Decimal("0.1")

    def test_market_sell_fills(self, broker, btc_instrument):
        # First buy
        buy = Order(instrument=btc_instrument, side=OrderSide.BUY,
                    type=OrderType.MARKET, quantity=Decimal("0.1"))
        broker.submit_order(buy)
        broker.process_bar(make_bar("BTC/USD", close=50000))

        # Then sell
        sell = Order(instrument=btc_instrument, side=OrderSide.SELL,
                     type=OrderType.MARKET, quantity=Decimal("0.1"))
        broker.submit_order(sell)
        fills = broker.process_bar(make_bar("BTC/USD", close=51000,
                                            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc)))
        assert len(fills) == 1
        assert fills[0].side == OrderSide.SELL

    def test_fee_applied(self, btc_instrument):
        broker = SimulatedBroker(
            initial_cash=Decimal("100000"),
            fee_rate=Decimal("0.01"),  # 1% fee
            slippage_pct=Decimal("0"),
        )
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("1"))
        broker.submit_order(order)
        fills = broker.process_bar(make_bar("BTC/USD", close=50000))
        assert len(fills) == 1
        assert fills[0].fee > Decimal("0")


class TestLimitOrders:
    def test_limit_buy_fills_when_price_drops(self, broker, btc_instrument):
        order = Order(
            instrument=btc_instrument,
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            price=Decimal("49000"),
        )
        broker.submit_order(order)

        # Price doesn't reach limit
        fills = broker.process_bar(make_bar("BTC/USD", low=49500, close=50000))
        assert len(fills) == 0

        # Price reaches limit
        fills = broker.process_bar(make_bar("BTC/USD", low=48500, close=49200,
                                            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc)))
        assert len(fills) == 1

    def test_limit_sell_fills_when_price_rises(self, broker, btc_instrument):
        # First create a position
        buy = Order(instrument=btc_instrument, side=OrderSide.BUY,
                    type=OrderType.MARKET, quantity=Decimal("0.1"))
        broker.submit_order(buy)
        broker.process_bar(make_bar("BTC/USD", close=50000))

        # Place limit sell
        sell = Order(instrument=btc_instrument, side=OrderSide.SELL,
                     type=OrderType.LIMIT, quantity=Decimal("0.1"),
                     price=Decimal("52000"))
        broker.submit_order(sell)

        fills = broker.process_bar(make_bar("BTC/USD", high=52500, close=52300,
                                            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc)))
        assert len(fills) == 1
        assert fills[0].side == OrderSide.SELL


class TestStopOrders:
    def test_stop_sell_triggers(self, broker, btc_instrument):
        # Create position
        buy = Order(instrument=btc_instrument, side=OrderSide.BUY,
                    type=OrderType.MARKET, quantity=Decimal("0.1"))
        broker.submit_order(buy)
        broker.process_bar(make_bar("BTC/USD", close=50000))

        # Place stop
        stop = Order(instrument=btc_instrument, side=OrderSide.SELL,
                     type=OrderType.STOP, quantity=Decimal("0.1"),
                     stop_price=Decimal("48000"))
        broker.submit_order(stop)

        # Price doesn't hit stop
        fills = broker.process_bar(make_bar("BTC/USD", low=48500, close=49000,
                                            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc)))
        assert len(fills) == 0

        # Price hits stop
        fills = broker.process_bar(make_bar("BTC/USD", low=47500, close=47800,
                                            timestamp=datetime(2024, 1, 3, tzinfo=timezone.utc)))
        assert len(fills) == 1


class TestPositionTracking:
    def test_position_created_on_fill(self, broker, btc_instrument):
        order = Order(instrument=btc_instrument, side=OrderSide.BUY,
                      type=OrderType.MARKET, quantity=Decimal("0.5"))
        broker.submit_order(order)
        broker.process_bar(make_bar("BTC/USD", close=50000))

        pos = broker.get_position(btc_instrument)
        assert pos is not None
        assert pos.quantity == Decimal("0.5")
        assert pos.side == OrderSide.BUY

    def test_position_closed_on_sell(self, broker, btc_instrument):
        # Buy
        broker.submit_order(Order(instrument=btc_instrument, side=OrderSide.BUY,
                                  type=OrderType.MARKET, quantity=Decimal("0.5")))
        broker.process_bar(make_bar("BTC/USD", close=50000))

        # Sell all
        broker.submit_order(Order(instrument=btc_instrument, side=OrderSide.SELL,
                                  type=OrderType.MARKET, quantity=Decimal("0.5")))
        broker.process_bar(make_bar("BTC/USD", close=51000,
                                    timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc)))

        pos = broker.get_position(btc_instrument)
        assert pos is None or pos.quantity == Decimal("0")

    def test_get_positions_list(self, broker, btc_instrument, eth_instrument):
        broker.submit_order(Order(instrument=btc_instrument, side=OrderSide.BUY,
                                  type=OrderType.MARKET, quantity=Decimal("0.1")))
        broker.process_bar(make_bar("BTC/USD", close=50000))

        broker.submit_order(Order(instrument=eth_instrument, side=OrderSide.BUY,
                                  type=OrderType.MARKET, quantity=Decimal("1")))
        broker.process_bar(make_bar("ETH/USD", close=3000,
                                    timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc)))

        positions = broker.get_positions()
        assert len(positions) >= 2


class TestAccount:
    def test_initial_equity(self, broker):
        acc = broker.get_account()
        assert acc.equity == Decimal("100000")

    def test_equity_decreases_on_fees(self, btc_instrument):
        broker = SimulatedBroker(
            initial_cash=Decimal("100000"),
            fee_rate=Decimal("0.01"),
            slippage_pct=Decimal("0"),
        )
        broker.submit_order(Order(instrument=btc_instrument, side=OrderSide.BUY,
                                  type=OrderType.MARKET, quantity=Decimal("1")))
        broker.process_bar(make_bar("BTC/USD", close=50000))
        acc = broker.get_account()
        assert acc.equity < Decimal("100000")
