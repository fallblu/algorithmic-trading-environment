"""SimulatedBroker — fill simulation for backtest and paper trading."""

from datetime import datetime
from decimal import Decimal

from broker.base import Broker
from models.account import Account
from models.bar import Bar
from models.fill import Fill
from models.instrument import Instrument
from models.order import Order, OrderSide, OrderStatus, OrderType
from models.position import Position


class SimulatedBroker(Broker):
    """Simulated broker for backtest and paper modes.

    Supports market orders (thin-slice), with limit/stop order support.
    Applies configurable slippage and fees.
    """

    def __init__(
        self,
        initial_cash: Decimal = Decimal("10000"),
        quote_currency: str = "USD",
        fee_rate: Decimal = Decimal("0.0026"),   # Kraken taker fee
        slippage_pct: Decimal = Decimal("0.0001"),  # 1 bps fixed slippage
    ):
        self.fee_rate = fee_rate
        self.slippage_pct = slippage_pct

        self._account = Account(
            balances={quote_currency: initial_cash},
            equity=initial_cash,
        )
        self._quote_currency = quote_currency
        self._orders: dict[str, Order] = {}
        self._open_orders: list[str] = []
        self._positions: dict[str, Position] = {}  # keyed by instrument symbol
        self._fills: list[Fill] = []
        self._current_time: datetime = datetime.now()

    # -- Broker interface --

    def submit_order(self, order: Order) -> Order:
        order.status = OrderStatus.OPEN
        order.updated_at = self._current_time
        self._orders[order.id] = order
        self._open_orders.append(order.id)
        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        order.status = OrderStatus.CANCELLED
        order.updated_at = self._current_time
        if order_id in self._open_orders:
            self._open_orders.remove(order_id)
        return order

    def get_order(self, order_id: str) -> Order:
        return self._orders[order_id]

    def get_open_orders(self, instrument: Instrument | None = None) -> list[Order]:
        orders = [self._orders[oid] for oid in self._open_orders]
        if instrument is not None:
            orders = [o for o in orders if o.instrument.symbol == instrument.symbol]
        return orders

    def get_position(self, instrument: Instrument) -> Position | None:
        pos = self._positions.get(instrument.symbol)
        if pos is not None and pos.quantity == 0:
            return None
        return pos

    def get_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.quantity > 0]

    def get_account(self) -> Account:
        return self._account

    @property
    def fills(self) -> list[Fill]:
        return list(self._fills)

    # -- Simulation engine --

    def process_bar(self, bar: Bar, skip_equity_update: bool = False) -> list[Fill]:
        """Process all open orders against the given bar. Returns new fills."""
        self._current_time = bar.timestamp
        new_fills: list[Fill] = []

        # Update unrealized PnL for existing positions
        pos = self._positions.get(bar.instrument_symbol)
        if pos is not None and pos.quantity > 0:
            pos.update_unrealized_pnl(bar.close)

        # Process open orders
        to_remove = []
        for order_id in list(self._open_orders):
            order = self._orders[order_id]
            if order.instrument.symbol != bar.instrument_symbol:
                continue

            fill = self._try_fill(order, bar)
            if fill is not None:
                new_fills.append(fill)
                self._fills.append(fill)
                to_remove.append(order_id)

        for oid in to_remove:
            self._open_orders.remove(oid)

        # Update account equity (unless suppressed for batch processing)
        if not skip_equity_update:
            self._update_equity(bar)

        return new_fills

    def process_bars(self, bars: list[Bar]) -> list[Fill]:
        """Process a group of bars (one per symbol at same timestamp).

        Defers equity update until all bars are processed, then does a
        bulk equity update using latest prices from each symbol.
        """
        all_fills: list[Fill] = []
        for bar in bars:
            fills = self.process_bar(bar, skip_equity_update=True)
            all_fills.extend(fills)

        # Bulk equity update with latest prices
        latest_prices = {bar.instrument_symbol: bar.close for bar in bars}
        self.update_equity_all(latest_prices)
        return all_fills

    def update_equity_all(self, latest_prices: dict[str, "Decimal"]) -> None:
        """Update unrealized PnL for all positions and recalculate equity."""
        for symbol, price in latest_prices.items():
            pos = self._positions.get(symbol)
            if pos is not None and pos.quantity > 0:
                pos.update_unrealized_pnl(price)

        cash = self._account.balances.get(self._quote_currency, Decimal("0"))
        unrealized = Decimal("0")
        position_value = Decimal("0")
        for pos in self._positions.values():
            unrealized += pos.unrealized_pnl
            if pos.quantity > 0:
                position_value += pos.quantity * pos.entry_price + pos.unrealized_pnl

        self._account.unrealized_pnl = unrealized
        self._account.equity = cash + position_value

    def _try_fill(self, order: Order, bar: Bar) -> Fill | None:
        """Attempt to fill an order against a bar. Returns Fill or None."""
        fill_price: Decimal | None = None

        if order.type == OrderType.MARKET:
            # Fill at open with slippage
            fill_price = self._apply_slippage(bar.open, order.side)

        elif order.type == OrderType.LIMIT:
            if order.price is None:
                return None
            if order.side == OrderSide.BUY and bar.low <= order.price:
                fill_price = order.price
            elif order.side == OrderSide.SELL and bar.high >= order.price:
                fill_price = order.price

        elif order.type == OrderType.STOP:
            if order.stop_price is None:
                return None
            if order.side == OrderSide.BUY and bar.high >= order.stop_price:
                fill_price = self._apply_slippage(order.stop_price, order.side)
            elif order.side == OrderSide.SELL and bar.low <= order.stop_price:
                fill_price = self._apply_slippage(order.stop_price, order.side)

        if fill_price is None:
            return None

        # Calculate fee
        notional = order.quantity * fill_price
        fee = notional * self.fee_rate

        # Calculate slippage from mid price
        mid = (bar.high + bar.low) / 2
        slippage = abs(fill_price - mid)

        # Create fill
        fill = Fill(
            order_id=order.id,
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            fee=fee,
            fee_currency=self._quote_currency,
            timestamp=self._current_time,
            is_maker=order.type == OrderType.LIMIT,
            slippage=slippage,
        )

        # Update order
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.average_fill_price = fill_price
        order.updated_at = self._current_time

        # Update position and account
        self._apply_fill(fill)

        return fill

    def _apply_slippage(self, price: Decimal, side: OrderSide) -> Decimal:
        """Apply slippage to a price."""
        slippage = price * self.slippage_pct
        if side == OrderSide.BUY:
            return price + slippage
        else:
            return price - slippage

    def _apply_fill(self, fill: Fill) -> None:
        """Update position and account based on a fill."""
        symbol = fill.instrument.symbol
        pos = self._positions.get(symbol)

        if pos is None:
            # Open new position
            pos = Position(
                instrument=fill.instrument,
                side=fill.side,
                quantity=fill.quantity,
                entry_price=fill.price,
                opened_at=fill.timestamp,
                last_updated=fill.timestamp,
            )
            self._positions[symbol] = pos
        elif pos.side == fill.side:
            # Adding to existing position — update VWAP entry
            total_cost = pos.entry_price * pos.quantity + fill.price * fill.quantity
            pos.quantity += fill.quantity
            pos.entry_price = total_cost / pos.quantity
            pos.last_updated = fill.timestamp
        else:
            # Reducing or reversing position
            if fill.quantity >= pos.quantity:
                # Close position (and possibly reverse)
                closed_qty = pos.quantity
                if pos.side == OrderSide.BUY:
                    pnl = (fill.price - pos.entry_price) * closed_qty
                else:
                    pnl = (pos.entry_price - fill.price) * closed_qty
                pos.realized_pnl += pnl
                self._account.realized_pnl += pnl

                remaining = fill.quantity - closed_qty
                if remaining > 0:
                    # Reverse into new position
                    pos.side = fill.side
                    pos.quantity = remaining
                    pos.entry_price = fill.price
                    pos.unrealized_pnl = Decimal("0")
                else:
                    pos.quantity = Decimal("0")
                    pos.unrealized_pnl = Decimal("0")
                pos.last_updated = fill.timestamp
            else:
                # Partial close
                if pos.side == OrderSide.BUY:
                    pnl = (fill.price - pos.entry_price) * fill.quantity
                else:
                    pnl = (pos.entry_price - fill.price) * fill.quantity
                pos.realized_pnl += pnl
                self._account.realized_pnl += pnl
                pos.quantity -= fill.quantity
                pos.last_updated = fill.timestamp

        # Deduct fees from cash
        self._account.balances[self._quote_currency] -= fill.fee

        # Update cash for the trade
        notional = fill.price * fill.quantity
        if fill.side == OrderSide.BUY:
            self._account.balances[self._quote_currency] -= notional
        else:
            self._account.balances[self._quote_currency] += notional

    def _update_equity(self, bar: Bar) -> None:
        """Recalculate account equity after processing a bar."""
        cash = self._account.balances.get(self._quote_currency, Decimal("0"))
        unrealized = Decimal("0")
        for pos in self._positions.values():
            if pos.quantity > 0 and pos.instrument.symbol == bar.instrument_symbol:
                pos.update_unrealized_pnl(bar.close)
            unrealized += pos.unrealized_pnl

        # For spot: equity = cash + sum(position_value)
        position_value = Decimal("0")
        for pos in self._positions.values():
            if pos.quantity > 0:
                position_value += pos.quantity * pos.entry_price + pos.unrealized_pnl

        self._account.unrealized_pnl = unrealized
        self._account.equity = cash + position_value
