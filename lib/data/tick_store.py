"""TickStore — storage for raw tick data in Parquet format."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


class TickStore:
    """Write/read tick DataFrames to Parquet.

    Layout: {base_dir}/{exchange}/{pair}/YYYY-MM-DD.parquet
    Schema: (timestamp_us, bid, ask, mid, spread, volume)
    """

    SCHEMA = pa.schema([
        ("timestamp", pa.timestamp("us")),
        ("bid", pa.float64()),
        ("ask", pa.float64()),
        ("mid", pa.float64()),
        ("spread", pa.float64()),
        ("volume", pa.float64()),
    ])

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def _path_for(self, exchange: str, pair: str, date: str) -> Path:
        safe_pair = pair.replace("/", "_")
        return self.base_dir / exchange / safe_pair / f"{date}.parquet"

    def write_ticks(self, ticks_df: pd.DataFrame, exchange: str, pair: str) -> None:
        """Write ticks, automatically routing to daily files."""
        if ticks_df.empty:
            return

        ticks_df = ticks_df.copy()
        ticks_df["timestamp"] = pd.to_datetime(ticks_df["timestamp"], utc=True)
        ticks_df["date"] = ticks_df["timestamp"].dt.strftime("%Y-%m-%d")

        for date, group in ticks_df.groupby("date"):
            path = self._path_for(exchange, pair, date)
            path.parent.mkdir(parents=True, exist_ok=True)

            write_df = group.drop(columns=["date"])

            if path.exists():
                existing = pd.read_parquet(path)
                existing["timestamp"] = pd.to_datetime(existing["timestamp"], utc=True)
                combined = pd.concat([existing, write_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
                combined = combined.sort_values("timestamp").reset_index(drop=True)
            else:
                combined = write_df.sort_values("timestamp").reset_index(drop=True)

            table = pa.Table.from_pandas(combined, schema=self.SCHEMA, preserve_index=False)
            pq.write_table(table, path)

    def read_ticks(
        self,
        exchange: str,
        pair: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Read ticks for a date range."""
        safe_pair = pair.replace("/", "_")
        pair_dir = self.base_dir / exchange / safe_pair

        if not pair_dir.exists():
            return pd.DataFrame(columns=["timestamp", "bid", "ask", "mid", "spread", "volume"])

        dfs = []
        for path in sorted(pair_dir.glob("*.parquet")):
            date_str = path.stem
            df = pd.read_parquet(path)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            dfs.append(df)

        if not dfs:
            return pd.DataFrame(columns=["timestamp", "bid", "ask", "mid", "spread", "volume"])

        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.sort_values("timestamp").reset_index(drop=True)

        if start is not None:
            start_ts = pd.Timestamp(start)
            if start_ts.tzinfo is None:
                start_ts = start_ts.tz_localize("UTC")
            combined = combined[combined["timestamp"] >= start_ts]

        if end is not None:
            end_ts = pd.Timestamp(end)
            if end_ts.tzinfo is None:
                end_ts = end_ts.tz_localize("UTC")
            combined = combined[combined["timestamp"] <= end_ts]

        return combined.reset_index(drop=True)

    def aggregate_to_bars(
        self,
        exchange: str,
        pair: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Aggregate tick data into bars at arbitrary timeframes."""
        ticks = self.read_ticks(exchange, pair, start, end)
        if ticks.empty:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        freq_map = {
            "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
            "1h": "1h", "4h": "4h", "1d": "1D",
        }
        freq = freq_map.get(timeframe, "1h")

        ticks = ticks.set_index("timestamp")
        bars = ticks["mid"].resample(freq).agg(
            open="first", high="max", low="min", close="last"
        ).dropna()

        bars["volume"] = ticks["volume"].resample(freq).sum().fillna(0)
        bars = bars.reset_index()

        return bars
