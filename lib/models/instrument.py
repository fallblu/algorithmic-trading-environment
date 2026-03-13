"""Instrument — trading instrument metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Instrument:
    symbol: str
    exchange: str
    tick_size: float = 0.01
    lot_size: float = 0.001
    min_notional: float = 10.0


# Default instrument configs for common symbols
INSTRUMENTS: dict[str, Instrument] = {
    # Crypto (Kraken)
    "BTC/USD": Instrument("BTC/USD", "kraken", tick_size=0.1, lot_size=0.0001, min_notional=10.0),
    "ETH/USD": Instrument("ETH/USD", "kraken", tick_size=0.01, lot_size=0.001, min_notional=10.0),
    "SOL/USD": Instrument("SOL/USD", "kraken", tick_size=0.001, lot_size=0.01, min_notional=10.0),
    "XRP/USD": Instrument("XRP/USD", "kraken", tick_size=0.0001, lot_size=1.0, min_notional=10.0),
    # Forex (OANDA)
    "EUR/USD": Instrument("EUR/USD", "oanda", tick_size=0.00001, lot_size=1.0, min_notional=1.0),
    "GBP/USD": Instrument("GBP/USD", "oanda", tick_size=0.00001, lot_size=1.0, min_notional=1.0),
    "USD/JPY": Instrument("USD/JPY", "oanda", tick_size=0.001, lot_size=1.0, min_notional=1.0),
    "AUD/USD": Instrument("AUD/USD", "oanda", tick_size=0.00001, lot_size=1.0, min_notional=1.0),
}


def get_instrument(symbol: str) -> Instrument:
    """Look up instrument metadata. Returns a default if not found."""
    if symbol in INSTRUMENTS:
        return INSTRUMENTS[symbol]
    exchange = "oanda" if "/" in symbol and not any(
        c in symbol for c in ("BTC", "ETH", "SOL", "XRP", "ADA", "DOT", "DOGE")
    ) else "kraken"
    return Instrument(symbol, exchange)
