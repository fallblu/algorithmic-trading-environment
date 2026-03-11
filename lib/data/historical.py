"""HistoricalFeed — replays bars from the MarketDataStore."""

from datetime import datetime

from data.feed import DataFeed
from data.store import MarketDataStore
from models.bar import Bar
from models.instrument import Instrument


class HistoricalFeed(DataFeed):
    """Replays OHLCV bars from local Parquet storage for backtesting."""

    def __init__(self, store: MarketDataStore, exchange: str = "kraken"):
        self.store = store
        self.exchange = exchange
        self._bars: list[Bar] = []
        self._index: int = 0

    def subscribe(self, instrument: Instrument, timeframe: str) -> None:
        """Not used for historical feed — bars are loaded via historical_bars()."""
        pass

    def next_bar(self) -> Bar | None:
        if self._index >= len(self._bars):
            return None
        bar = self._bars[self._index]
        self._index += 1
        return bar

    def historical_bars(
        self,
        instrument: Instrument,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        bars = self.store.read_bars(
            exchange=self.exchange,
            symbol=instrument.symbol,
            timeframe=timeframe,
            start=start,
            end=end,
        )
        # Also populate internal buffer for next_bar() usage
        self._bars = bars
        self._index = 0
        return bars

    def reset(self) -> None:
        self._index = 0

    @property
    def total_bars(self) -> int:
        return len(self._bars)

    @property
    def remaining_bars(self) -> int:
        return max(0, len(self._bars) - self._index)
