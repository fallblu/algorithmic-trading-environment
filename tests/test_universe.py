import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from models.instrument import FuturesInstrument, Instrument
from data.universe import Universe


def test_from_symbols_creates_correct_instruments():
    universe = Universe.from_symbols(["BTC/USD", "ETH/USD"], timeframe="1h")

    assert len(universe.instruments) == 2
    assert "BTC/USD" in universe.instruments
    assert "ETH/USD" in universe.instruments

    btc = universe.instruments["BTC/USD"]
    assert isinstance(btc, Instrument)
    assert btc.base == "BTC"
    assert btc.quote == "USD"
    assert btc.exchange == "kraken"
    assert btc.asset_class == "crypto"
    assert universe.timeframe == "1h"


def test_from_futures_symbols_creates_futures_instruments():
    universe = Universe.from_futures_symbols(["BTC-PERP", "ETH-PERP"], timeframe="1h")

    assert len(universe.instruments) == 2
    btc_perp = universe.instruments["BTC-PERP"]
    assert isinstance(btc_perp, FuturesInstrument)
    assert btc_perp.base == "BTC"
    assert btc_perp.asset_class == "crypto_futures"
    assert btc_perp.exchange == "kraken_futures"


def test_from_forex_symbols_creates_forex_instruments():
    universe = Universe.from_forex_symbols(["EUR/USD", "GBP/USD"], timeframe="1h")

    assert len(universe.instruments) == 2
    eur = universe.instruments["EUR/USD"]
    assert isinstance(eur, Instrument)
    assert eur.base == "EUR"
    assert eur.quote == "USD"
    assert eur.exchange == "oanda"
    assert eur.asset_class == "forex"


def test_symbols_property_returns_list_of_strings():
    universe = Universe.from_symbols(["BTC/USD", "ETH/USD", "SOL/USD"], timeframe="1h")
    symbols = universe.symbols

    assert isinstance(symbols, list)
    assert len(symbols) == 3
    assert all(isinstance(s, str) for s in symbols)
    assert set(symbols) == {"BTC/USD", "ETH/USD", "SOL/USD"}
