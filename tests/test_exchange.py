import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from data.exchange import (
    EXCHANGE_REGISTRY,
    Exchange,
    KrakenFuturesExchange,
    KrakenSpotExchange,
    OandaExchange,
    get_exchange,
)


def test_get_exchange_returns_correct_implementations():
    kraken = get_exchange("kraken")
    assert isinstance(kraken, KrakenSpotExchange)
    assert kraken.name == "kraken"

    futures = get_exchange("kraken_futures")
    assert isinstance(futures, KrakenFuturesExchange)
    assert futures.name == "kraken_futures"

    oanda = get_exchange("oanda")
    assert isinstance(oanda, OandaExchange)
    assert oanda.name == "oanda"


def test_get_exchange_unknown_raises_key_error():
    with pytest.raises(KeyError, match="Unknown exchange"):
        get_exchange("binance")


def test_exchange_registry_contents():
    assert "kraken" in EXCHANGE_REGISTRY
    assert "kraken_futures" in EXCHANGE_REGISTRY
    assert "oanda" in EXCHANGE_REGISTRY
    assert len(EXCHANGE_REGISTRY) == 3

    assert EXCHANGE_REGISTRY["kraken"] is KrakenSpotExchange
    assert EXCHANGE_REGISTRY["kraken_futures"] is KrakenFuturesExchange
    assert EXCHANGE_REGISTRY["oanda"] is OandaExchange


def test_exchange_abc_methods():
    # All concrete exchange classes must be subclasses of Exchange
    assert issubclass(KrakenSpotExchange, Exchange)
    assert issubclass(KrakenFuturesExchange, Exchange)
    assert issubclass(OandaExchange, Exchange)

    # Verify that the abstract methods exist on the ABC
    abstract_methods = Exchange.__abstractmethods__
    assert "fetch_ohlcv" in abstract_methods
    assert "create_live_feed" in abstract_methods
    assert "create_broker" in abstract_methods
    assert "get_instruments" in abstract_methods
