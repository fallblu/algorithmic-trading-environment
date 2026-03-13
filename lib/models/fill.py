"""Fill — executed trade fill."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from models.order import OrderSide


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    fee: float
    timestamp: datetime
    strategy_id: str = ""
    slippage: float = 0.0
