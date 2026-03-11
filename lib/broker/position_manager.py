"""PositionManager — manages positions, margin accounting, and PnL from fills."""

from decimal import Decimal

from models.account import Account
from models.fill import Fill
from models.order import OrderSide
from models.position import Position


class PositionManager:
    """Maintains positions and updates account equity from fills.

    Extracted from SimulatedBroker._apply_fill() to make each position
    operation independently testable.
    """

    def __init__(
        self,
        account: Account,
        quote_currency: str = "USD",
        margin_mode: bool = False,
        leverage: Decimal = Decimal("1"),
    ):
        self._account = account
        self._quote_currency = quote_currency
        self._positions: dict[str, Position] = {}
        self.margin_mode = margin_mode
        self.leverage = leverage

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    def get_position(self, symbol: str) -> Position | None:
        pos = self._positions.get(symbol)
        if pos is not None and pos.quantity == 0:
            return None
        return pos

    def get_open_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.quantity > 0]

    def apply_fill(self, fill: Fill) -> None:
        """Update position and account based on a fill."""
        symbol = fill.instrument.symbol
        pos = self._positions.get(symbol)

        if pos is None:
            self._open_position(fill)
        elif pos.side == fill.side:
            self._add_to_position(pos, fill)
        else:
            self._reduce_or_reverse_position(pos, fill)

        # Deduct fees from cash
        self._account.balances[self._quote_currency] -= fill.fee

        if not self.margin_mode:
            # Spot: update cash for the trade
            notional = fill.price * fill.quantity
            if fill.side == OrderSide.BUY:
                self._account.balances[self._quote_currency] -= notional
            else:
                self._account.balances[self._quote_currency] += notional

    def _open_position(self, fill: Fill) -> None:
        """Open a new position from a fill."""
        pos = Position(
            instrument=fill.instrument,
            side=fill.side,
            quantity=fill.quantity,
            entry_price=fill.price,
            opened_at=fill.timestamp,
            last_updated=fill.timestamp,
        )
        self._positions[fill.instrument.symbol] = pos

        if self.margin_mode:
            notional = fill.price * fill.quantity
            margin = notional / self.leverage
            pos.margin_used = margin
            self._account.margin_used += margin

    def _add_to_position(self, pos: Position, fill: Fill) -> None:
        """Add to an existing same-direction position (VWAP entry update)."""
        total_cost = pos.entry_price * pos.quantity + fill.price * fill.quantity
        pos.quantity += fill.quantity
        pos.entry_price = total_cost / pos.quantity
        pos.last_updated = fill.timestamp

        if self.margin_mode:
            new_margin = fill.price * fill.quantity / self.leverage
            pos.margin_used += new_margin
            self._account.margin_used += new_margin

    def _reduce_or_reverse_position(self, pos: Position, fill: Fill) -> None:
        """Reduce, close, or reverse an opposing-direction position."""
        if fill.quantity >= pos.quantity:
            self._close_or_reverse(pos, fill)
        else:
            self._partial_close(pos, fill)

    def _close_or_reverse(self, pos: Position, fill: Fill) -> None:
        """Close the position entirely, optionally reversing into the opposite side."""
        closed_qty = pos.quantity
        pnl = self._compute_pnl(pos.side, pos.entry_price, fill.price, closed_qty)
        pos.realized_pnl += pnl
        self._account.realized_pnl += pnl

        if self.margin_mode:
            self._account.margin_used -= pos.margin_used
            pos.margin_used = Decimal("0")

        remaining = fill.quantity - closed_qty
        if remaining > 0:
            # Reverse into opposite direction
            pos.side = fill.side
            pos.quantity = remaining
            pos.entry_price = fill.price
            pos.unrealized_pnl = Decimal("0")

            if self.margin_mode:
                margin = fill.price * remaining / self.leverage
                pos.margin_used = margin
                self._account.margin_used += margin
        else:
            # Fully closed
            pos.quantity = Decimal("0")
            pos.unrealized_pnl = Decimal("0")

        pos.last_updated = fill.timestamp

    def _partial_close(self, pos: Position, fill: Fill) -> None:
        """Partially reduce a position."""
        pnl = self._compute_pnl(pos.side, pos.entry_price, fill.price, fill.quantity)
        pos.realized_pnl += pnl
        self._account.realized_pnl += pnl

        if self.margin_mode:
            margin_released = pos.margin_used * fill.quantity / pos.quantity
            pos.margin_used -= margin_released
            self._account.margin_used -= margin_released

        pos.quantity -= fill.quantity
        pos.last_updated = fill.timestamp

    @staticmethod
    def _compute_pnl(
        side: OrderSide, entry_price: Decimal, exit_price: Decimal, quantity: Decimal
    ) -> Decimal:
        """Compute realized PnL for a closed quantity."""
        if side == OrderSide.BUY:
            return (exit_price - entry_price) * quantity
        else:
            return (entry_price - exit_price) * quantity
