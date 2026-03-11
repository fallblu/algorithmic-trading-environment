from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from models.instrument import Instrument
from models.order import OrderSide


@dataclass(frozen=True)
class Fill:
    order_id: str
    instrument: Instrument
    side: OrderSide
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    timestamp: datetime
    is_maker: bool = False
    slippage: Decimal = Decimal("0")
