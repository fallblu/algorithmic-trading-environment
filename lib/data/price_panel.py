"""PricePanel — aggregates Bar objects into a rolling MultiIndex DataFrame window."""

from collections import deque

import pandas as pd

from data.universe import Universe
from models.bar import Bar


class PricePanel:
    """Collects bars per symbol into a rolling window and produces a
    MultiIndex DataFrame for strategy consumption.

    The DataFrame has a MultiIndex of (timestamp, symbol) and columns:
    [open, high, low, close, volume, trades, vwap].

    Decimal fields are converted to float64 at ingestion.
    """

    def __init__(self, universe: Universe, lookback: int):
        self._universe = universe
        self._lookback = lookback
        self._buffers: dict[str, deque[dict]] = {
            sym: deque(maxlen=lookback) for sym in universe.symbols
        }

    def append_bar(self, bar: Bar) -> None:
        """Append a single bar. Converts Decimal to float."""
        buf = self._buffers.get(bar.instrument_symbol)
        if buf is None:
            return
        buf.append({
            "timestamp": bar.timestamp,
            "symbol": bar.instrument_symbol,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
            "trades": bar.trades or 0,
            "vwap": float(bar.vwap) if bar.vwap is not None else 0.0,
        })

    def append_bars(self, bars: list[Bar]) -> None:
        """Bulk append."""
        for bar in bars:
            self.append_bar(bar)

    def get_window(self) -> pd.DataFrame:
        """Build a MultiIndex DataFrame from all symbol buffers.

        Inner-joins on timestamps so strategies only see timestamps
        present for all symbols.
        """
        all_rows: list[dict] = []
        for buf in self._buffers.values():
            all_rows.extend(buf)

        if not all_rows:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume", "trades", "vwap"]
            )

        df = pd.DataFrame(all_rows)

        # Inner-join on timestamps: keep only timestamps present for ALL symbols
        n_symbols = len(self._buffers)
        if n_symbols > 1:
            ts_counts = df.groupby("timestamp")["symbol"].nunique()
            valid_ts = ts_counts[ts_counts == n_symbols].index
            df = df[df["timestamp"].isin(valid_ts)]

        if df.empty:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume", "trades", "vwap"]
            )

        df = df.set_index(["timestamp", "symbol"]).sort_index()
        return df

    @property
    def is_ready(self) -> bool:
        """True when all symbol buffers have at least 1 bar."""
        return all(len(buf) >= 1 for buf in self._buffers.values())

    @property
    def latest_timestamp(self):
        """Most recent timestamp across all buffers."""
        latest = None
        for buf in self._buffers.values():
            if buf:
                ts = buf[-1]["timestamp"]
                if latest is None or ts > latest:
                    latest = ts
        return latest
