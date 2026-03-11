"""Exchange abstraction layer — unified interface for exchange-specific operations."""

from abc import ABC, abstractmethod

from broker.base import Broker
from data.feed import DataFeed
from models.bar import Bar
from models.instrument import Instrument


class Exchange(ABC):
    """Unified interface for exchange-specific operations.

    Each exchange implementation provides methods for fetching data,
    creating live feeds and brokers, and resolving instruments.
    """

    name: str

    @abstractmethod
    def fetch_ohlcv(
        self, symbol: str, timeframe: str, start=None, end=None
    ) -> list[Bar]:
        """Fetch historical OHLCV bars."""
        ...

    @abstractmethod
    def create_live_feed(self) -> DataFeed:
        """Create a live data feed for this exchange."""
        ...

    @abstractmethod
    def create_broker(self) -> Broker:
        """Create a broker for this exchange."""
        ...

    @abstractmethod
    def get_instruments(self) -> list[Instrument]:
        """Return available instruments on this exchange."""
        ...


class KrakenSpotExchange(Exchange):
    """Kraken spot exchange adapter."""

    name = "kraken"

    def fetch_ohlcv(self, symbol, timeframe, start=None, end=None):
        from data.kraken_api import backfill_ohlcv
        return backfill_ohlcv(symbol=symbol, timeframe=timeframe, start=start, end=end)

    def create_live_feed(self):
        from data.live import LiveFeed
        return LiveFeed()

    def create_broker(self):
        from broker.kraken import KrakenBroker
        return KrakenBroker()

    def get_instruments(self):
        from data.universe import Universe
        universe = Universe.from_symbols(
            ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"], "1h", exchange="kraken"
        )
        return list(universe.instruments.values())


class OandaExchange(Exchange):
    """OANDA forex exchange adapter."""

    name = "oanda"

    def fetch_ohlcv(self, symbol, timeframe, start=None, end=None):
        from data.oanda_api import backfill_candles
        return backfill_candles(
            symbol=symbol, timeframe=timeframe, start=start, end=end
        )

    def create_live_feed(self):
        from data.live_oanda import LiveOandaFeed
        return LiveOandaFeed()

    def create_broker(self):
        from broker.oanda import OandaBroker
        return OandaBroker()

    def get_instruments(self):
        from data.universe import Universe
        universe = Universe.from_forex_symbols(
            ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"], "1h"
        )
        return list(universe.instruments.values())


# Registry for resolving exchange by name
EXCHANGE_REGISTRY: dict[str, type[Exchange]] = {
    "kraken": KrakenSpotExchange,
    "oanda": OandaExchange,
}


def get_exchange(name: str) -> Exchange:
    """Resolve an exchange adapter by name string."""
    cls = EXCHANGE_REGISTRY.get(name)
    if cls is None:
        raise KeyError(f"Unknown exchange: {name!r}. Available: {list(EXCHANGE_REGISTRY)}")
    return cls()
