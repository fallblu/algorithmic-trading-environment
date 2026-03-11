"""Tests for SimulatedBroker — fill simulation, fees, slippage, margin."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from datetime import datetime
from decimal import Decimal

import pytest

from broker.simulated import SimulatedBroker
from models.bar import Bar
from models.instrument import Instrument
from models.order import Order, OrderSide, OrderStatus, OrderType


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


def make_bar(symbol: str, open_: float, high: float, low: float, close: float,
             volume: float = 1.0, ts: datetime | None = None) -> Bar:
    return Bar(
        instrument_symbol=symbol,
        timestamp=ts or datetime(2025, 1, 1, 12, 0),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )


# ---------------------------------------------------------------------------
# Account state
# ---------------------------------------------------------------------------

def test_initial_account_state():
    broker = SimulatedBroker(initial_cash=Decimal("50000"))
    acct = broker.get_account()
    assert acct.balances["USD"] == Decimal("50000")
    assert acct.equity == Decimal("50000")


# ---------------------------------------------------------------------------
# Market orders
# ---------------------------------------------------------------------------

def test_submit_market_buy_and_fill(instrument):
    broker = SimulatedBroker(
        initial_cash=Decimal("100000"),
        fee_rate=Decimal("0"),
        slippage_pct=Decimal("0"),
    )
    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    broker.submit_order(order)
    assert order.status == OrderStatus.OPEN

    bar = make_bar("BTC/USD", 50000, 51000, 49000, 50500)
    fills = broker.process_bars([bar])

    assert len(fills) == 1
    assert fills[0].side == OrderSide.BUY
    # Market fills at bar open (no slippage configured)
    assert fills[0].price == Decimal("50000")
    assert order.status == OrderStatus.FILLED

    # Cash reduced by notional
    acct = broker.get_account()
    assert acct.balances["USD"] == Decimal("100000") - Decimal("50000")


def test_submit_market_sell_order(instrument):
    broker = SimulatedBroker(
        initial_cash=Decimal("100000"),
        fee_rate=Decimal("0"),
        slippage_pct=Decimal("0"),
    )
    # First buy to have a position
    buy = Order(instrument=instrument, side=OrderSide.BUY,
                type=OrderType.MARKET, quantity=Decimal("1"))
    broker.submit_order(buy)
    broker.process_bars([make_bar("BTC/USD", 50000, 51000, 49000, 50500)])

    # Now sell
    sell = Order(instrument=instrument, side=OrderSide.SELL,
                 type=OrderType.MARKET, quantity=Decimal("1"))
    broker.submit_order(sell)
    bar2 = make_bar("BTC/USD", 51000, 52000, 50000, 51500,
                     ts=datetime(2025, 1, 1, 13, 0))
    fills = broker.process_bars([bar2])

    assert len(fills) == 1
    assert fills[0].side == OrderSide.SELL
    assert fills[0].price == Decimal("51000")
    # Position closed
    assert broker.get_position(instrument) is None


# ---------------------------------------------------------------------------
# Limit orders
# ---------------------------------------------------------------------------

def test_limit_buy_fills_when_price_reached(instrument):
    broker = SimulatedBroker(
        initial_cash=Decimal("100000"),
        fee_rate=Decimal("0"),
        slippage_pct=Decimal("0"),
    )
    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("49500"),
    )
    broker.submit_order(order)

    # Bar low reaches limit price
    bar = make_bar("BTC/USD", 50000, 51000, 49000, 50500)
    fills = broker.process_bars([bar])

    assert len(fills) == 1
    assert fills[0].price == Decimal("49500")
    assert order.status == OrderStatus.FILLED


def test_limit_buy_does_not_fill_when_price_not_reached(instrument):
    broker = SimulatedBroker(
        initial_cash=Decimal("100000"),
        fee_rate=Decimal("0"),
        slippage_pct=Decimal("0"),
    )
    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("48000"),  # Below bar low of 49000
    )
    broker.submit_order(order)

    bar = make_bar("BTC/USD", 50000, 51000, 49000, 50500)
    fills = broker.process_bars([bar])

    assert len(fills) == 0
    assert order.status == OrderStatus.OPEN


# ---------------------------------------------------------------------------
# Stop orders
# ---------------------------------------------------------------------------

def test_stop_buy_triggers(instrument):
    broker = SimulatedBroker(
        initial_cash=Decimal("100000"),
        fee_rate=Decimal("0"),
        slippage_pct=Decimal("0"),
    )
    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.STOP,
        quantity=Decimal("1"),
        stop_price=Decimal("51000"),
    )
    broker.submit_order(order)

    # Bar high reaches stop price
    bar = make_bar("BTC/USD", 50000, 51500, 49500, 51000)
    fills = broker.process_bars([bar])

    assert len(fills) == 1
    assert fills[0].price == Decimal("51000")  # no slippage
    assert order.status == OrderStatus.FILLED


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_cancel_order(instrument):
    broker = SimulatedBroker()
    order = Order(
        instrument=instrument,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("40000"),
    )
    broker.submit_order(order)
    assert len(broker.get_open_orders()) == 1

    broker.cancel_order(order.id)
    assert order.status == OrderStatus.CANCELLED
    assert len(broker.get_open_orders()) == 0


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

def test_get_positions(instrument):
    broker = SimulatedBroker(
        initial_cash=Decimal("200000"),
        fee_rate=Decimal("0"),
        slippage_pct=Decimal("0"),
    )
    # No positions initially
    assert broker.get_positions() == []

    order = Order(instrument=instrument, side=OrderSide.BUY,
                  type=OrderType.MARKET, quantity=Decimal("2"))
    broker.submit_order(order)
    broker.process_bars([make_bar("BTC/USD", 50000, 51000, 49000, 50500)])

    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].instrument.symbol == "BTC/USD"
    assert positions[0].quantity == Decimal("2")


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------

def test_fee_deduction(instrument):
    fee_rate = Decimal("0.001")
    broker = SimulatedBroker(
        initial_cash=Decimal("100000"),
        fee_rate=fee_rate,
        slippage_pct=Decimal("0"),
    )
    order = Order(instrument=instrument, side=OrderSide.BUY,
                  type=OrderType.MARKET, quantity=Decimal("1"))
    broker.submit_order(order)

    bar = make_bar("BTC/USD", 50000, 51000, 49000, 50500)
    fills = broker.process_bars([bar])

    expected_fee = Decimal("1") * Decimal("50000") * fee_rate  # 50
    assert fills[0].fee == expected_fee

    acct = broker.get_account()
    # Cash = initial - notional - fee
    expected_cash = Decimal("100000") - Decimal("50000") - expected_fee
    assert acct.balances["USD"] == expected_cash


# ---------------------------------------------------------------------------
# Slippage
# ---------------------------------------------------------------------------

def test_slippage_application(instrument):
    slippage = Decimal("0.001")  # 10 bps
    broker = SimulatedBroker(
        initial_cash=Decimal("100000"),
        fee_rate=Decimal("0"),
        slippage_pct=slippage,
    )
    order = Order(instrument=instrument, side=OrderSide.BUY,
                  type=OrderType.MARKET, quantity=Decimal("1"))
    broker.submit_order(order)

    bar = make_bar("BTC/USD", 50000, 51000, 49000, 50500)
    fills = broker.process_bars([bar])

    # Buy slippage: price + price * slippage_pct
    expected_price = Decimal("50000") + Decimal("50000") * slippage
    assert fills[0].price == expected_price


# ---------------------------------------------------------------------------
# Margin mode
# ---------------------------------------------------------------------------

def test_margin_mode_initial_margin_deduction(instrument):
    broker = SimulatedBroker(
        initial_cash=Decimal("10000"),
        fee_rate=Decimal("0"),
        slippage_pct=Decimal("0"),
        margin_mode=True,
        leverage=Decimal("10"),
    )
    order = Order(instrument=instrument, side=OrderSide.BUY,
                  type=OrderType.MARKET, quantity=Decimal("1"))
    broker.submit_order(order)

    bar = make_bar("BTC/USD", 50000, 51000, 49000, 50500)
    broker.process_bars([bar])

    # Margin used = notional / leverage = 50000 / 10 = 5000
    acct = broker.get_account()
    assert acct.margin_used == Decimal("5000")

    pos = broker.get_position(instrument)
    assert pos is not None
    assert pos.margin_used == Decimal("5000")

    # In margin mode, cash is NOT reduced by notional (only fees)
    assert acct.balances["USD"] == Decimal("10000")


def test_margin_mode_apply_funding(instrument):
    broker = SimulatedBroker(
        initial_cash=Decimal("10000"),
        fee_rate=Decimal("0"),
        slippage_pct=Decimal("0"),
        margin_mode=True,
        leverage=Decimal("10"),
    )
    order = Order(instrument=instrument, side=OrderSide.BUY,
                  type=OrderType.MARKET, quantity=Decimal("1"))
    broker.submit_order(order)
    broker.process_bars([make_bar("BTC/USD", 50000, 51000, 49000, 50500)])

    # Apply positive funding — long pays
    funding_rate = Decimal("0.0001")
    broker.apply_funding("BTC/USD", funding_rate)

    # charge = notional * rate = 50000 * 0.0001 = 5
    acct = broker.get_account()
    expected_cash = Decimal("10000") - Decimal("50000") * funding_rate
    assert acct.balances["USD"] == expected_cash


# ---------------------------------------------------------------------------
# Spread simulation
# ---------------------------------------------------------------------------

def test_spread_pips(instrument):
    broker = SimulatedBroker(
        initial_cash=Decimal("100000"),
        fee_rate=Decimal("0"),
        slippage_pct=Decimal("0"),
        spread_pips=Decimal("20"),  # 20 pips = 20 * 0.0001 = 0.002
    )
    order = Order(instrument=instrument, side=OrderSide.BUY,
                  type=OrderType.MARKET, quantity=Decimal("1"))
    broker.submit_order(order)

    bar = make_bar("BTC/USD", 50000, 51000, 49000, 50500)
    fills = broker.process_bars([bar])

    # half_spread = 20 * 0.0001 / 2 = 0.001
    # buy fill = open + half_spread + slippage(0) = 50000 + 0.001 = 50000.001
    half_spread = Decimal("20") * Decimal("0.0001") / 2
    expected = Decimal("50000") + half_spread
    assert fills[0].price == expected
