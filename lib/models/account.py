from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Account:
    balances: dict[str, Decimal] = field(default_factory=dict)
    equity: Decimal = Decimal("0")
    margin_used: Decimal = Decimal("0")
    margin_available: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")

    def update_equity(self) -> None:
        total = sum(self.balances.values(), Decimal("0"))
        self.equity = total + self.unrealized_pnl

    def to_dict(self) -> dict:
        return {
            "balances": {k: str(v) for k, v in self.balances.items()},
            "equity": str(self.equity),
            "margin_used": str(self.margin_used),
            "unrealized_pnl": str(self.unrealized_pnl),
            "realized_pnl": str(self.realized_pnl),
            "daily_pnl": str(self.daily_pnl),
            "max_drawdown": str(self.max_drawdown),
        }
