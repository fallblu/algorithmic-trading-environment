"""HistoricalFeed — loads bars from Parquet and groups by timestamp."""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from data.store import MarketDataStore
from models.bar import Bar

log = logging.getLogger(__name__)


class HistoricalFeed:
    """Loads OHLCV data from Parquet and iterates bar groups by timestamp.

    For single-symbol backtests, each group is a single bar.
    For multi-symbol, groups contain one bar per symbol at each timestamp.
    """

    def __init__(self, store: MarketDataStore, exchange: str = "kraken") -> None:
        self._store = store
        self._exchange = exchange
        self._groups: list[list[Bar]] = []
        self._index: int = 0

    @property
    def total_groups(self) -> int:
        return len(self._groups)

    @property
    def current_index(self) -> int:
        return self._index

    def load(
        self,
        symbols: list[str],
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> None:
        """Load data for all symbols and group by timestamp."""
        all_bars: dict[str, list[Bar]] = {}
        for symbol in symbols:
            bars = self._store.read_bars(self._exchange, symbol, timeframe, start, end)
            all_bars[symbol] = bars
            log.info("Loaded %d bars for %s", len(bars), symbol)

        if len(symbols) == 1:
            self._groups = [[b] for b in all_bars[symbols[0]]]
        else:
            self._build_multi_symbol_groups(all_bars)

        self._index = 0
        log.info("Built %d timestamp groups for %d symbols", len(self._groups), len(symbols))

    def _build_multi_symbol_groups(self, all_bars: dict[str, list[Bar]]) -> None:
        """Group bars across symbols by timestamp."""
        by_ts: dict[datetime, list[Bar]] = {}
        for bars in all_bars.values():
            for bar in bars:
                by_ts.setdefault(bar.timestamp, []).append(bar)

        self._groups = [by_ts[ts] for ts in sorted(by_ts.keys())]

    def next_bar_group(self) -> list[Bar] | None:
        """Return next group of bars, or None if exhausted."""
        if self._index >= len(self._groups):
            return None
        group = self._groups[self._index]
        self._index += 1
        return group

    def reset(self) -> None:
        """Reset iterator to the beginning."""
        self._index = 0

    def get_dataframes(
        self,
        symbols: list[str],
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Load raw DataFrames for each symbol (used by chart builder)."""
        result: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            df = self._store.read_dataframe(self._exchange, symbol, timeframe, start, end)
            result[symbol] = df
        return result
