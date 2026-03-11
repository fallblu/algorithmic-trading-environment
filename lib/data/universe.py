"""Universe — a configurable set of instruments to trade."""

from dataclasses import dataclass, field
from decimal import Decimal

from models.instrument import Instrument


# Sensible defaults for common Kraken pairs
_KRAKEN_DEFAULTS: dict[str, dict] = {
    "BTC": {"tick_size": "0.01", "lot_size": "0.00001", "min_notional": "5"},
    "ETH": {"tick_size": "0.01", "lot_size": "0.0001", "min_notional": "5"},
    "SOL": {"tick_size": "0.001", "lot_size": "0.01", "min_notional": "5"},
    "XRP": {"tick_size": "0.0001", "lot_size": "1", "min_notional": "5"},
    "DOGE": {"tick_size": "0.00001", "lot_size": "1", "min_notional": "5"},
    "ADA": {"tick_size": "0.0001", "lot_size": "1", "min_notional": "5"},
    "AVAX": {"tick_size": "0.001", "lot_size": "0.01", "min_notional": "5"},
    "DOT": {"tick_size": "0.001", "lot_size": "0.1", "min_notional": "5"},
    "LINK": {"tick_size": "0.001", "lot_size": "0.1", "min_notional": "5"},
}

_DEFAULT_SPECS = {"tick_size": "0.01", "lot_size": "0.001", "min_notional": "5"}


@dataclass(frozen=True)
class Universe:
    """A set of instruments with a shared timeframe."""

    instruments: dict[str, Instrument] = field(default_factory=dict)
    timeframe: str = "1h"

    @property
    def symbols(self) -> list[str]:
        return list(self.instruments.keys())

    @classmethod
    def from_symbols(
        cls,
        symbols: list[str],
        timeframe: str,
        exchange: str = "kraken",
    ) -> "Universe":
        """Build a Universe from a list of symbol strings like 'BTC/USD'."""
        instruments: dict[str, Instrument] = {}
        for symbol in symbols:
            parts = symbol.split("/")
            base = parts[0]
            quote = parts[1] if len(parts) > 1 else "USD"
            specs = _KRAKEN_DEFAULTS.get(base, _DEFAULT_SPECS)
            instruments[symbol] = Instrument(
                symbol=symbol,
                base=base,
                quote=quote,
                exchange=exchange,
                asset_class="crypto",
                tick_size=Decimal(specs["tick_size"]),
                lot_size=Decimal(specs["lot_size"]),
                min_notional=Decimal(specs["min_notional"]),
            )
        return cls(instruments=instruments, timeframe=timeframe)
