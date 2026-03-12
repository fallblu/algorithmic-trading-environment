"""SimulatedBroker — fill simulation for backtest and paper trading."""

from datetime import datetime
from decimal import Decimal

from broker.base import Broker
from broker.position_manager import PositionManager
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
        margin_mode: bool = False,
        leverage: Decimal = Decimal("1"),
        spread_pips: Decimal = Decimal("0"),
    ):
        self.fee_rate = fee_rate
        self.slippage_pct = slippage_pct
        self.spread_pips = spread_pips

        self._account = Account(
            balances={quote_currency: initial_cash},
            equity=initial_cash,
        )
        self._quote_currency = quote_currency
        self._orders: dict[str, Order] = {}
        self._open_orders: list[str] = []
        self._fills: list[Fill] = []
        self._current_time: datetime = datetime.now()

        self._position_mgr = PositionManager(
            account=self._account,
            quote_currency=quote_currency,
            margin_mode=margin_mode,
            leverage=leverage,
        )

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
        return self._position_mgr.get_position(instrument.symbol)

    def get_positions(self) -> list[Position]:
        return self._position_mgr.get_open_positions()

    def get_account(self) -> Account:
        return self._account

    @property
    def fills(self) -> list[Fill]:
        return list(self._fills)

    # Expose positions dict for backwards compatibility (used by LiveContext)
    @property
    def _positions(self) -> dict[str, Position]:
        return self._position_mgr.positions

    @property
    def margin_mode(self) -> bool:
        return self._position_mgr.margin_mode

    # -- Simulation engine --

    def process_bar(self, bar: Bar, skip_equity_update: bool = False) -> list[Fill]:
        """Process all open orders against the given bar. Returns new fills."""
        self._current_time = bar.timestamp
        new_fills: list[Fill] = []

        # Update unrealized PnL for existing positions
        pos = self._position_mgr.positions.get(bar.instrument_symbol)
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

    def update_equity_all(self, latest_prices: dict[str, Decimal]) -> None:
        """Update unrealized PnL for all positions and recalculate equity."""
        for symbol, price in latest_prices.items():
            pos = self._position_mgr.positions.get(symbol)
            if pos is not None and pos.quantity > 0:
                pos.update_unrealized_pnl(price)

        cash = self._account.balances.get(self._quote_currency, Decimal("0"))
        unrealized = Decimal("0")
        position_value = Decimal("0")
        for pos in self._position_mgr.positions.values():
            unrealized += pos.unrealized_pnl
            if pos.quantity > 0:
                position_value += pos.quantity * pos.entry_price + pos.unrealized_pnl

        self._account.unrealized_pnl = unrealized
        self._account.equity = cash + position_value

    def _try_fill(self, order: Order, bar: Bar) -> Fill | None:
        """Attempt to fill an order against a bar. Returns Fill or None."""
        fill_price: Decimal | None = None

        if order.type == OrderType.MARKET:
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

        # Calculate fee and slippage
        notional = order.quantity * fill_price
        fee = notional * self.fee_rate
        mid = (bar.high + bar.low) / 2
        slippage = abs(fill_price - mid)

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

        # Update order status
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.average_fill_price = fill_price
        order.updated_at = self._current_time

        # Delegate position and account updates to PositionManager
        self._position_mgr.apply_fill(fill)

        return fill

    def _apply_slippage(self, price: Decimal, side: OrderSide) -> Decimal:
        """Apply slippage to a price. For forex, also applies spread."""
        slippage = price * self.slippage_pct
        if self.spread_pips > 0:
            half_spread = self.spread_pips * Decimal("0.0001") / 2
            if side == OrderSide.BUY:
                return price + half_spread + slippage
            else:
                return price - half_spread - slippage
        if side == OrderSide.BUY:
            return price + slippage
        else:
            return price - slippage

    def _update_equity(self, bar: Bar) -> None:
        """Recalculate account equity after processing a bar."""
        cash = self._account.balances.get(self._quote_currency, Decimal("0"))
        unrealized = Decimal("0")
        for pos in self._position_mgr.positions.values():
            if pos.quantity > 0 and pos.instrument.symbol == bar.instrument_symbol:
                pos.update_unrealized_pnl(bar.close)
            unrealized += pos.unrealized_pnl

        self._account.unrealized_pnl = unrealized

        if self._position_mgr.margin_mode:
            self._account.equity = cash + unrealized
            self._account.margin_available = self._account.equity - self._account.margin_used
        else:
            position_value = Decimal("0")
            for pos in self._position_mgr.positions.values():
                if pos.quantity > 0:
                    position_value += pos.quantity * pos.entry_price + pos.unrealized_pnl
            self._account.equity = cash + position_value
