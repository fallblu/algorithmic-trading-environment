"""PositionManager — tracks positions and computes PnL from fills."""

from __future__ import annotations

from models.fill import Fill
from models.order import OrderSide
from models.position import Position, PositionSide


class PositionManager:
    """Maintains positions and computes PnL from trade fills.

    Each position is keyed by (symbol, strategy_id) to support
    per-strategy position tracking within a portfolio.
    """

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}
        self._total_realized_pnl: float = 0.0

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    @property
    def total_realized_pnl(self) -> float:
        return self._total_realized_pnl

    def _key(self, symbol: str, strategy_id: str = "") -> str:
        return f"{symbol}:{strategy_id}" if strategy_id else symbol

    def get_position(self, symbol: str, strategy_id: str = "") -> Position | None:
        pos = self._positions.get(self._key(symbol, strategy_id))
        if pos is not None and pos.quantity == 0:
            return None
        return pos

    def get_open_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.quantity > 0]

    def get_position_quantity(self, symbol: str, strategy_id: str = "") -> float:
        """Get signed position quantity (positive=long, negative=short)."""
        pos = self.get_position(symbol, strategy_id)
        if pos is None:
            return 0.0
        sign = 1.0 if pos.side == PositionSide.LONG else -1.0
        return sign * pos.quantity

    def get_all_quantities(self, strategy_id: str = "") -> dict[str, float]:
        """Get {symbol: signed_quantity} for all positions, optionally filtered by strategy."""
        result: dict[str, float] = {}
        for key, pos in self._positions.items():
            if pos.quantity == 0:
                continue
            if strategy_id and pos.strategy_id != strategy_id:
                continue
            sign = 1.0 if pos.side == PositionSide.LONG else -1.0
            result[pos.symbol] = sign * pos.quantity
        return result

    def apply_fill(self, fill: Fill) -> float:
        """Update position from fill. Returns realized PnL from this fill (0 for opens)."""
        key = self._key(fill.symbol, fill.strategy_id)
        pos = self._positions.get(key)

        if pos is None or pos.quantity == 0:
            return self._open_position(key, fill)
        elif (pos.side == PositionSide.LONG and fill.side == OrderSide.BUY) or \
             (pos.side == PositionSide.SHORT and fill.side == OrderSide.SELL):
            return self._add_to_position(pos, fill)
        else:
            return self._reduce_position(pos, key, fill)

    def update_unrealized_pnl(self, symbol: str, current_price: float) -> None:
        """Update unrealized PnL for all positions in a symbol."""
        for pos in self._positions.values():
            if pos.symbol == symbol and pos.quantity > 0:
                if pos.side == PositionSide.LONG:
                    pos.unrealized_pnl = (current_price - pos.avg_entry_price) * pos.quantity
                else:
                    pos.unrealized_pnl = (pos.avg_entry_price - current_price) * pos.quantity

    def _open_position(self, key: str, fill: Fill) -> float:
        side = PositionSide.LONG if fill.side == OrderSide.BUY else PositionSide.SHORT
        self._positions[key] = Position(
            symbol=fill.symbol,
            side=side,
            quantity=fill.quantity,
            avg_entry_price=fill.price,
            strategy_id=fill.strategy_id,
            opened_at=fill.timestamp,
        )
        return 0.0

    def _add_to_position(self, pos: Position, fill: Fill) -> float:
        total_cost = pos.avg_entry_price * pos.quantity + fill.price * fill.quantity
        pos.quantity += fill.quantity
        pos.avg_entry_price = total_cost / pos.quantity
        return 0.0

    def _reduce_position(self, pos: Position, key: str, fill: Fill) -> float:
        close_qty = min(fill.quantity, pos.quantity)

        if pos.side == PositionSide.LONG:
            realized = (fill.price - pos.avg_entry_price) * close_qty
        else:
            realized = (pos.avg_entry_price - fill.price) * close_qty

        self._total_realized_pnl += realized
        pos.realized_pnl += realized

        remaining_fill = fill.quantity - close_qty
        pos.quantity -= close_qty

        if pos.quantity == 0 and remaining_fill > 0:
            # Reverse: open in opposite direction
            new_side = PositionSide.LONG if fill.side == OrderSide.BUY else PositionSide.SHORT
            self._positions[key] = Position(
                symbol=fill.symbol,
                side=new_side,
                quantity=remaining_fill,
                avg_entry_price=fill.price,
                strategy_id=fill.strategy_id,
                opened_at=fill.timestamp,
            )
        elif pos.quantity == 0:
            pos.side = PositionSide.FLAT

        return realized
