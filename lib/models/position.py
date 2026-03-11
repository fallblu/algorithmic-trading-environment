from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from models.instrument import Instrument
from models.order import OrderSide


@dataclass
class Position:
    instrument: Instrument
    side: OrderSide                          # LONG=BUY, SHORT=SELL
    quantity: Decimal = Decimal("0")
    entry_price: Decimal = Decimal("0")      # Volume-weighted avg entry
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    margin_used: Decimal = Decimal("0")      # For margin/leverage mode
    opened_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)

    def update_unrealized_pnl(self, current_price: Decimal) -> None:
        if self.quantity == 0:
            self.unrealized_pnl = Decimal("0")
            return
        if self.side == OrderSide.BUY:
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity

    def to_dict(self) -> dict:
        return {
            "instrument_symbol": self.instrument.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "entry_price": str(self.entry_price),
            "unrealized_pnl": str(self.unrealized_pnl),
            "realized_pnl": str(self.realized_pnl),
            "opened_at": self.opened_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
        }
