"""SimulatedBroker — fill simulation for backtest and paper trading."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from broker.base import Account, Broker
from broker.position_manager import PositionManager
from models.bar import Bar
from models.fill import Fill
from models.order import Order, OrderSide, OrderStatus, OrderType
from models.position import Position

log = logging.getLogger(__name__)


class SimulatedBroker(Broker):
    """Simulated broker for backtest and paper modes.

    Supports market and limit orders with configurable fees, slippage,
    and forex spread simulation.
    """

    def __init__(
        self,
        initial_cash: float = 10_000.0,
        fee_rate: float = 0.0026,
        slippage_pct: float = 0.0001,
        spread_pips: float = 0.0,
    ) -> None:
        self._fee_rate = fee_rate
        self._slippage_pct = slippage_pct
        self._spread_pips = spread_pips
        self._initial_cash = initial_cash
        self._cash = initial_cash
        self._orders: dict[str, Order] = {}
        self._open_order_ids: list[str] = []
        self._fills: list[Fill] = []
        self._current_time = datetime.now(timezone.utc)
        self._position_mgr = PositionManager()
        self._latest_prices: dict[str, float] = {}

    # -- Broker interface --

    def submit_order(self, order: Order) -> str:
        order.status = OrderStatus.OPEN
        self._orders[order.id] = order
        self._open_order_ids.append(order.id)
        return order.id

    def cancel_order(self, order_id: str) -> bool:
        if order_id not in self._orders:
            return False
        order = self._orders[order_id]
        if order.status not in (OrderStatus.OPEN, OrderStatus.PENDING):
            return False
        order.status = OrderStatus.CANCELLED
        if order_id in self._open_order_ids:
            self._open_order_ids.remove(order_id)
        return True

    def get_positions(self) -> list[Position]:
        return self._position_mgr.get_open_positions()

    def get_open_orders(self) -> list[Order]:
        return [self._orders[oid] for oid in self._open_order_ids]

    def get_account(self) -> Account:
        unrealized = sum(p.unrealized_pnl for p in self._position_mgr.get_open_positions())
        equity = self._cash + unrealized
        return Account(
            cash=self._cash,
            equity=equity,
            unrealized_pnl=unrealized,
            realized_pnl=self._position_mgr.total_realized_pnl,
        )

    def get_fills(self, since: datetime | None = None) -> list[Fill]:
        if since is None:
            return list(self._fills)
        return [f for f in self._fills if f.timestamp >= since]

    # -- Convenience accessors --

    @property
    def fills(self) -> list[Fill]:
        return list(self._fills)

    @property
    def position_manager(self) -> PositionManager:
        return self._position_mgr

    @property
    def cash(self) -> float:
        return self._cash

    # -- Simulation engine --

    def process_bar(self, bar: Bar) -> list[Fill]:
        """Process open orders against a bar. Returns new fills."""
        self._current_time = bar.timestamp
        self._latest_prices[bar.symbol] = bar.close

        new_fills: list[Fill] = []
        to_remove: list[str] = []

        for order_id in list(self._open_order_ids):
            order = self._orders[order_id]
            if order.symbol != bar.symbol:
                continue

            fill = self._try_fill(order, bar)
            if fill is not None:
                new_fills.append(fill)
                self._fills.append(fill)
                to_remove.append(order_id)

        for oid in to_remove:
            self._open_order_ids.remove(oid)

        # Update unrealized PnL after fills (so new positions are included)
        self._position_mgr.update_unrealized_pnl(bar.symbol, bar.close)

        return new_fills

    def process_bars(self, bars: list[Bar]) -> list[Fill]:
        """Process a group of bars (one per symbol at same timestamp)."""
        all_fills: list[Fill] = []
        for bar in bars:
            fills = self.process_bar(bar)
            all_fills.extend(fills)
        return all_fills

    def _try_fill(self, order: Order, bar: Bar) -> Fill | None:
        """Attempt to fill an order against a bar."""
        if order.type == OrderType.MARKET:
            fill_price = self._apply_slippage(bar.open, order.side, bar.symbol)
        elif order.type == OrderType.LIMIT:
            if order.price is None:
                return None
            if order.side == OrderSide.BUY and bar.low <= order.price:
                fill_price = min(order.price, bar.open)
            elif order.side == OrderSide.SELL and bar.high >= order.price:
                fill_price = max(order.price, bar.open)
            else:
                return None
            fill_price = self._apply_slippage(fill_price, order.side, bar.symbol)
        else:
            return None

        fee = abs(fill_price * order.quantity * self._fee_rate)

        fill = Fill(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            fee=fee,
            timestamp=bar.timestamp,
            strategy_id=order.strategy_id,
        )

        # Update order status
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.fill_price = fill_price

        # Apply fill to position manager
        realized_pnl = self._position_mgr.apply_fill(fill)

        # Update cash
        notional = fill_price * order.quantity
        if order.side == OrderSide.BUY:
            self._cash -= notional + fee
        else:
            self._cash += notional - fee

        return fill

    def _apply_slippage(self, price: float, side: OrderSide, symbol: str) -> float:
        """Apply slippage and spread to a fill price."""
        slippage = price * self._slippage_pct

        if self._spread_pips > 0:
            # Forex spread simulation
            pip_value = 0.0001 if "JPY" not in symbol else 0.01
            half_spread = (self._spread_pips / 2) * pip_value
            if side == OrderSide.BUY:
                return price + half_spread + slippage
            else:
                return price - half_spread - slippage

        if side == OrderSide.BUY:
            return price + slippage
        else:
            return price - slippage
