from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Bar:
    instrument_symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trades: int | None = None
    vwap: Decimal | None = None


@dataclass(frozen=True)
class FundingRate:
    instrument_symbol: str
    timestamp: datetime
    rate: Decimal
    next_funding_time: datetime
