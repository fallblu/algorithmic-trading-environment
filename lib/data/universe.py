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

# OANDA forex defaults with pip-based tick sizes
_OANDA_DEFAULTS: dict[str, dict] = {
    "EUR/USD": {"tick_size": "0.00001", "lot_size": "1", "min_notional": "1"},
    "GBP/USD": {"tick_size": "0.00001", "lot_size": "1", "min_notional": "1"},
    "USD/JPY": {"tick_size": "0.001", "lot_size": "1", "min_notional": "1"},
    "AUD/USD": {"tick_size": "0.00001", "lot_size": "1", "min_notional": "1"},
    "USD/CAD": {"tick_size": "0.00001", "lot_size": "1", "min_notional": "1"},
    "USD/CHF": {"tick_size": "0.00001", "lot_size": "1", "min_notional": "1"},
    "NZD/USD": {"tick_size": "0.00001", "lot_size": "1", "min_notional": "1"},
    "EUR/GBP": {"tick_size": "0.00001", "lot_size": "1", "min_notional": "1"},
    "EUR/JPY": {"tick_size": "0.001", "lot_size": "1", "min_notional": "1"},
    "GBP/JPY": {"tick_size": "0.001", "lot_size": "1", "min_notional": "1"},
}


# -- Symbol mappings: our format -> exchange API format --

KRAKEN_SYMBOL_MAP = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
    "SOL/USD": "SOLUSD",
    "XRP/USD": "XRPUSD",
}


def resolve_kraken_symbol(symbol: str) -> str:
    """Map our symbol (e.g. BTC/USD) to the Kraken API pair name."""
    return KRAKEN_SYMBOL_MAP.get(symbol, symbol.replace("/", ""))


def get_kraken_specs(base: str) -> dict[str, str]:
    """Get instrument specs for a Kraken spot base currency."""
    return _KRAKEN_DEFAULTS.get(base, dict(_DEFAULT_SPECS))


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

    @classmethod
    def from_forex_symbols(
        cls,
        symbols: list[str],
        timeframe: str,
        exchange: str = "oanda",
    ) -> "Universe":
        """Build a Universe from forex symbol strings like 'EUR/USD'."""
        instruments: dict[str, Instrument] = {}
        for symbol in symbols:
            parts = symbol.split("/")
            base = parts[0]
            quote = parts[1] if len(parts) > 1 else "USD"
            specs = _OANDA_DEFAULTS.get(symbol, {
                "tick_size": "0.00001", "lot_size": "1", "min_notional": "1",
            })
            instruments[symbol] = Instrument(
                symbol=symbol,
                base=base,
                quote=quote,
                exchange=exchange,
                asset_class="forex",
                tick_size=Decimal(specs["tick_size"]),
                lot_size=Decimal(specs["lot_size"]),
                min_notional=Decimal(specs["min_notional"]),
            )
        return cls(instruments=instruments, timeframe=timeframe)
