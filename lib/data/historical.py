"""HistoricalFeed — replays bars from the MarketDataStore."""

from datetime import datetime

from data.feed import DataFeed
from data.store import MarketDataStore
from data.universe import Universe
from models.bar import Bar
from models.instrument import Instrument


class HistoricalFeed(DataFeed):
    """Replays OHLCV bars from local Parquet storage for backtesting."""

    def __init__(self, store: MarketDataStore, exchange: str = "kraken"):
        self.store = store
        self.exchange = exchange
        self._bars: list[Bar] = []
        self._index: int = 0
        # Multi-symbol timeline: list of bar groups at each timestamp
        self._timeline: list[list[Bar]] = []
        self._timeline_index: int = 0

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

    def load_universe(
        self,
        universe: Universe,
        start: datetime,
        end: datetime,
    ) -> None:
        """Load bars for all symbols in the universe and build a timeline.

        The timeline groups bars by timestamp, sorted chronologically.
        """
        all_bars: list[Bar] = []
        for symbol, instrument in universe.instruments.items():
            bars = self.store.read_bars(
                exchange=self.exchange,
                symbol=symbol,
                timeframe=universe.timeframe,
                start=start,
                end=end,
            )
            all_bars.extend(bars)

        # Group by timestamp
        from collections import defaultdict
        groups: dict[datetime, list[Bar]] = defaultdict(list)
        for bar in all_bars:
            groups[bar.timestamp].append(bar)

        # Sort by timestamp
        self._timeline = [groups[ts] for ts in sorted(groups.keys())]
        self._timeline_index = 0

    def next_bar_group(self) -> list[Bar] | None:
        """Return all bars at the next timestamp, or None if exhausted."""
        if self._timeline_index >= len(self._timeline):
            return None
        group = self._timeline[self._timeline_index]
        self._timeline_index += 1
        return group

    def reset(self) -> None:
        self._index = 0
        self._timeline_index = 0

    @property
    def total_bars(self) -> int:
        return len(self._bars)

    @property
    def remaining_bars(self) -> int:
        return max(0, len(self._bars) - self._index)

    @property
    def total_groups(self) -> int:
        return len(self._timeline)
