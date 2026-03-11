from abc import ABC, abstractmethod
from datetime import datetime

from models.bar import Bar
from models.instrument import Instrument


class DataFeed(ABC):
    @abstractmethod
    def subscribe(self, instrument: Instrument, timeframe: str) -> None:
        """Subscribe to a data feed for the given instrument and timeframe."""
        ...

    @abstractmethod
    def next_bar(self) -> Bar | None:
        """Get the next bar. Returns None when no more data is available."""
        ...

    @abstractmethod
    def historical_bars(
        self,
        instrument: Instrument,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        """Get historical bars for the given instrument and timeframe."""
        ...
