from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Instrument:
    symbol: str           # "BTC/USD", "ETH-PERP"
    base: str             # "BTC"
    quote: str            # "USD"
    exchange: str         # "kraken"
    asset_class: str      # "crypto", "forex"
    tick_size: Decimal     # Minimum price increment
    lot_size: Decimal      # Minimum quantity increment
    min_notional: Decimal  # Minimum order value


@dataclass(frozen=True)
class FuturesInstrument(Instrument):
    contract_type: str = "perpetual"                # "perpetual" | "fixed"
    max_leverage: Decimal = Decimal("100")
    initial_margin_rate: Decimal = Decimal("0.01")  # e.g. 0.01 for 100x
    maintenance_margin_rate: Decimal = Decimal("0.005")
    funding_interval_hours: int = 8
    expiry: datetime | None = None                  # None for perpetuals
