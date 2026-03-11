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

    def subscribe_all(self, instruments: list[Instrument], timeframe: str) -> None:
        """Subscribe to multiple instruments. Default: calls subscribe() in loop."""
        for instrument in instruments:
            self.subscribe(instrument, timeframe)

    def next_bars(self) -> list[Bar]:
        """Drain all available bars. Default: calls next_bar() in loop."""
        bars: list[Bar] = []
        while True:
            bar = self.next_bar()
            if bar is None:
                break
            bars.append(bar)
        return bars
