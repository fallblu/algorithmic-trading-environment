from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Instrument:
    symbol: str           # "BTC/USD", "EUR/USD"
    base: str             # "BTC"
    quote: str            # "USD"
    exchange: str         # "kraken"
    asset_class: str      # "crypto", "forex"
    tick_size: Decimal     # Minimum price increment
    lot_size: Decimal      # Minimum quantity increment
    min_notional: Decimal  # Minimum order value
