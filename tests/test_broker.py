from __future__ import annotations

from datetime import datetime, timezone

import pytest

from broker.simulated import SimulatedBroker
from broker.position_manager import PositionManager
from models.bar import Bar
from models.fill import Fill
from models.order import Order, OrderSide, OrderStatus, OrderType
from models.position import PositionSide


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bar(
    symbol: str = "BTC/USD",
    open_: float = 100.0,
    high: float = 110.0,
    low: float = 90.0,
    close: float = 105.0,
    volume: float = 1000.0,
    ts: datetime | None = None,
) -> Bar:
    if ts is None:
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return Bar(
        symbol=symbol, timestamp=ts, open=open_, high=high, low=low, close=close, volume=volume
    )


def make_order(
    symbol: str = "BTC/USD",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    quantity: float = 1.0,
    price: float | None = None,
) -> Order:
    return Order(symbol=symbol, side=side, type=order_type, quantity=quantity, price=price)


# ---------------------------------------------------------------------------
# SimulatedBroker
# ---------------------------------------------------------------------------

class TestSimulatedBrokerMarketOrder:
    def test_submit_market_order_and_fill(self):
        broker = SimulatedBroker(initial_cash=100_000.0, fee_rate=0.0, slippage_pct=0.0)
        order = make_order(side=OrderSide.BUY, quantity=2.0)
        broker.submit_order(order)

        bar = make_bar(open_=50000.0, high=51000.0, low=49000.0, close=50500.0)
        fills = broker.process_bar(bar)

        assert len(fills) == 1
        fill = fills[0]
        assert fill.symbol == "BTC/USD"
        assert fill.side == OrderSide.BUY
        assert fill.quantity == 2.0
        # Market orders fill at bar open
        assert fill.price == 50000.0
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 2.0
        assert order.fill_price == 50000.0


class TestSimulatedBrokerLimitOrder:
    def test_limit_buy_fills_when_price_dips(self):
        broker = SimulatedBroker(initial_cash=100_000.0, fee_rate=0.0, slippage_pct=0.0)
        order = make_order(
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            price=95.0,
        )
        broker.submit_order(order)

        # Bar where low does not reach limit price -- no fill
        bar_high = make_bar(open_=100.0, high=110.0, low=96.0, close=105.0)
        fills = broker.process_bar(bar_high)
        assert len(fills) == 0
        assert order.status == OrderStatus.OPEN

        # Bar where low dips below limit price -- should fill
        bar_dip = make_bar(
            open_=100.0, high=105.0, low=90.0, close=98.0,
            ts=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
        fills = broker.process_bar(bar_dip)
        assert len(fills) == 1
        # Fill at min(limit_price, bar.open) = min(95, 100) = 95
        assert fills[0].price == 95.0
        assert order.status == OrderStatus.FILLED


class TestSimulatedBrokerFees:
    def test_fee_calculation(self):
        fee_rate = 0.001  # 0.1%
        broker = SimulatedBroker(
            initial_cash=100_000.0, fee_rate=fee_rate, slippage_pct=0.0
        )
        order = make_order(side=OrderSide.BUY, quantity=2.0)
        broker.submit_order(order)

        bar = make_bar(open_=1000.0)
        fills = broker.process_bar(bar)

        assert len(fills) == 1
        expected_fee = abs(1000.0 * 2.0 * fee_rate)  # 2.0
        assert fills[0].fee == pytest.approx(expected_fee)

        # Cash should decrease by notional + fee
        expected_cash = 100_000.0 - (1000.0 * 2.0) - expected_fee
        assert broker.cash == pytest.approx(expected_cash)


class TestSimulatedBrokerSlippage:
    def test_slippage_applied_to_buy(self):
        slippage = 0.001  # 0.1%
        broker = SimulatedBroker(
            initial_cash=100_000.0, fee_rate=0.0, slippage_pct=slippage
        )
        order = make_order(side=OrderSide.BUY, quantity=1.0)
        broker.submit_order(order)

        bar = make_bar(open_=1000.0)
        fills = broker.process_bar(bar)

        # Buy slippage increases fill price
        expected_price = 1000.0 + 1000.0 * slippage  # 1001.0
        assert fills[0].price == pytest.approx(expected_price)

    def test_slippage_applied_to_sell(self):
        slippage = 0.001
        broker = SimulatedBroker(
            initial_cash=100_000.0, fee_rate=0.0, slippage_pct=slippage
        )
        order = make_order(side=OrderSide.SELL, quantity=1.0)
        broker.submit_order(order)

        bar = make_bar(open_=1000.0)
        fills = broker.process_bar(bar)

        # Sell slippage decreases fill price
        expected_price = 1000.0 - 1000.0 * slippage  # 999.0
        assert fills[0].price == pytest.approx(expected_price)


class TestSimulatedBrokerPnL:
    def test_buy_then_sell_realized_pnl(self):
        broker = SimulatedBroker(initial_cash=100_000.0, fee_rate=0.0, slippage_pct=0.0)

        # Buy 1 @ 100
        buy = make_order(side=OrderSide.BUY, quantity=1.0)
        broker.submit_order(buy)
        broker.process_bar(make_bar(
            open_=100.0, high=110.0, low=90.0, close=105.0,
            ts=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ))

        # Sell 1 @ 120
        sell = make_order(side=OrderSide.SELL, quantity=1.0)
        broker.submit_order(sell)
        broker.process_bar(make_bar(
            open_=120.0, high=125.0, low=115.0, close=122.0,
            ts=datetime(2024, 1, 2, tzinfo=timezone.utc),
        ))

        # Realized PnL = (120 - 100) * 1 = 20
        account = broker.get_account()
        assert account.realized_pnl == pytest.approx(20.0)

        # Cash: started 100k, bought at 100, sold at 120 => 100_020
        assert broker.cash == pytest.approx(100_020.0)


class TestSimulatedBrokerEquity:
    def test_get_account_equity_tracking(self):
        broker = SimulatedBroker(initial_cash=50_000.0, fee_rate=0.0, slippage_pct=0.0)

        account = broker.get_account()
        assert account.cash == 50_000.0
        assert account.equity == 50_000.0
        assert account.unrealized_pnl == 0.0

        # Buy 10 units @ 100
        buy = make_order(side=OrderSide.BUY, quantity=10.0)
        broker.submit_order(buy)
        broker.process_bar(make_bar(
            open_=100.0, high=110.0, low=90.0, close=105.0,
            ts=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ))

        # After buying: cash = 50000 - 1000 = 49000
        # Unrealized PnL at close 105: (105 - 100) * 10 = 50
        account = broker.get_account()
        assert account.cash == pytest.approx(49_000.0)
        assert account.unrealized_pnl == pytest.approx(50.0)
        assert account.equity == pytest.approx(49_050.0)


class TestSimulatedBrokerCancelOrder:
    def test_cancel_order(self):
        broker = SimulatedBroker()
        order = make_order(
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            price=50.0,
        )
        order_id = broker.submit_order(order)

        assert len(broker.get_open_orders()) == 1
        result = broker.cancel_order(order_id)
        assert result is True
        assert order.status == OrderStatus.CANCELLED
        assert len(broker.get_open_orders()) == 0

    def test_cancel_nonexistent_order(self):
        broker = SimulatedBroker()
        result = broker.cancel_order("nonexistent-id")
        assert result is False

    def test_cancel_already_filled_order(self):
        broker = SimulatedBroker(fee_rate=0.0, slippage_pct=0.0)
        order = make_order(side=OrderSide.BUY, quantity=1.0)
        order_id = broker.submit_order(order)
        broker.process_bar(make_bar(open_=100.0))

        assert order.status == OrderStatus.FILLED
        result = broker.cancel_order(order_id)
        assert result is False


# ---------------------------------------------------------------------------
# PositionManager
# ---------------------------------------------------------------------------

class TestPositionManager:
    def _make_fill(
        self,
        symbol: str = "BTC/USD",
        side: OrderSide = OrderSide.BUY,
        quantity: float = 1.0,
        price: float = 100.0,
        strategy_id: str = "",
    ) -> Fill:
        return Fill(
            order_id="test",
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            fee=0.0,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            strategy_id=strategy_id,
        )

    def test_open_position(self):
        pm = PositionManager()
        fill = self._make_fill(side=OrderSide.BUY, quantity=5.0, price=100.0)
        realized = pm.apply_fill(fill)

        assert realized == 0.0
        pos = pm.get_position("BTC/USD")
        assert pos is not None
        assert pos.side == PositionSide.LONG
        assert pos.quantity == 5.0
        assert pos.avg_entry_price == 100.0

    def test_add_to_position(self):
        pm = PositionManager()
        pm.apply_fill(self._make_fill(side=OrderSide.BUY, quantity=2.0, price=100.0))
        pm.apply_fill(self._make_fill(side=OrderSide.BUY, quantity=3.0, price=110.0))

        pos = pm.get_position("BTC/USD")
        assert pos is not None
        assert pos.quantity == 5.0
        # Weighted avg: (2*100 + 3*110) / 5 = 530/5 = 106
        assert pos.avg_entry_price == pytest.approx(106.0)

    def test_reduce_position(self):
        pm = PositionManager()
        pm.apply_fill(self._make_fill(side=OrderSide.BUY, quantity=5.0, price=100.0))
        realized = pm.apply_fill(
            self._make_fill(side=OrderSide.SELL, quantity=3.0, price=120.0)
        )

        # Realized PnL = (120 - 100) * 3 = 60
        assert realized == pytest.approx(60.0)
        pos = pm.get_position("BTC/USD")
        assert pos is not None
        assert pos.quantity == 2.0

    def test_close_position(self):
        pm = PositionManager()
        pm.apply_fill(self._make_fill(side=OrderSide.BUY, quantity=5.0, price=100.0))
        realized = pm.apply_fill(
            self._make_fill(side=OrderSide.SELL, quantity=5.0, price=150.0)
        )

        assert realized == pytest.approx(250.0)
        # Position is closed (quantity=0), get_position returns None
        pos = pm.get_position("BTC/USD")
        assert pos is None

    def test_reverse_position(self):
        pm = PositionManager()
        pm.apply_fill(self._make_fill(side=OrderSide.BUY, quantity=3.0, price=100.0))
        # Sell 5: closes the 3 long, opens 2 short
        realized = pm.apply_fill(
            self._make_fill(side=OrderSide.SELL, quantity=5.0, price=120.0)
        )

        # Realized on the close: (120 - 100) * 3 = 60
        assert realized == pytest.approx(60.0)

        pos = pm.get_position("BTC/USD")
        assert pos is not None
        assert pos.side == PositionSide.SHORT
        assert pos.quantity == 2.0
        assert pos.avg_entry_price == 120.0

    def test_get_all_quantities(self):
        pm = PositionManager()
        pm.apply_fill(self._make_fill(symbol="BTC/USD", side=OrderSide.BUY, quantity=2.0, price=100.0))
        pm.apply_fill(self._make_fill(symbol="ETH/USD", side=OrderSide.SELL, quantity=10.0, price=3000.0))

        qtys = pm.get_all_quantities()
        assert qtys["BTC/USD"] == pytest.approx(2.0)
        assert qtys["ETH/USD"] == pytest.approx(-10.0)

    def test_short_position_opens_correctly(self):
        pm = PositionManager()
        pm.apply_fill(self._make_fill(side=OrderSide.SELL, quantity=3.0, price=200.0))

        pos = pm.get_position("BTC/USD")
        assert pos is not None
        assert pos.side == PositionSide.SHORT
        assert pos.quantity == 3.0

    def test_open_positions_excludes_flat(self):
        pm = PositionManager()
        pm.apply_fill(self._make_fill(side=OrderSide.BUY, quantity=1.0, price=100.0))
        pm.apply_fill(self._make_fill(side=OrderSide.SELL, quantity=1.0, price=110.0))

        assert len(pm.get_open_positions()) == 0
