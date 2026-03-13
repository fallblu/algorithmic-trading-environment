"""MarketDataStore — Parquet-based OHLCV data storage."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from models.bar import Bar

log = logging.getLogger(__name__)

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class MarketDataStore:
    """Read/write OHLCV data as Parquet files.

    Layout: {base_dir}/{exchange}/{symbol_safe}/{timeframe}.parquet
    where symbol_safe replaces '/' with '_' (e.g., BTC_USD).
    """

    def __init__(self, base_dir: Path | str) -> None:
        self._base_dir = Path(base_dir)

    def _parquet_path(self, exchange: str, symbol: str, timeframe: str) -> Path:
        safe_symbol = symbol.replace("/", "_")
        return self._base_dir / exchange / safe_symbol / f"{timeframe}.parquet"

    def write_bars(self, bars: list[Bar], exchange: str, timeframe: str) -> int:
        """Write bars to Parquet, merging with existing data. Returns total row count."""
        if not bars:
            return 0

        symbol = bars[0].symbol
        path = self._parquet_path(exchange, symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)

        new_df = pd.DataFrame([
            {
                "timestamp": b.timestamp,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ])
        new_df["timestamp"] = pd.to_datetime(new_df["timestamp"], utc=True)

        if path.exists():
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
            combined = combined.sort_values("timestamp").reset_index(drop=True)
        else:
            combined = new_df.sort_values("timestamp").reset_index(drop=True)

        combined.to_parquet(path, index=False)
        log.info("Wrote %d bars for %s/%s/%s", len(combined), exchange, symbol, timeframe)
        return len(combined)

    def read_dataframe(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Read OHLCV data as a DataFrame. Returns empty DataFrame if no data."""
        path = self._parquet_path(exchange, symbol, timeframe)
        if not path.exists():
            return pd.DataFrame(columns=COLUMNS)

        df = pd.read_parquet(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        if start is not None:
            start_ts = pd.Timestamp(start, tz="UTC")
            df = df[df["timestamp"] >= start_ts]
        if end is not None:
            end_ts = pd.Timestamp(end, tz="UTC")
            df = df[df["timestamp"] <= end_ts]

        return df.sort_values("timestamp").reset_index(drop=True)

    def read_bars(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        """Read OHLCV data as Bar objects."""
        df = self.read_dataframe(exchange, symbol, timeframe, start, end)
        return [
            Bar(
                symbol=symbol,
                timestamp=row["timestamp"].to_pydatetime(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for _, row in df.iterrows()
        ]

    def has_data(self, exchange: str, symbol: str, timeframe: str) -> bool:
        return self._parquet_path(exchange, symbol, timeframe).exists()

    def get_date_range(
        self, exchange: str, symbol: str, timeframe: str
    ) -> tuple[datetime, datetime] | None:
        """Return (earliest, latest) timestamps, or None if no data."""
        df = self.read_dataframe(exchange, symbol, timeframe)
        if df.empty:
            return None
        return (
            df["timestamp"].min().to_pydatetime(),
            df["timestamp"].max().to_pydatetime(),
        )

    def get_row_count(self, exchange: str, symbol: str, timeframe: str) -> int:
        path = self._parquet_path(exchange, symbol, timeframe)
        if not path.exists():
            return 0
        meta = pq.read_metadata(path)
        return meta.num_rows

    def inventory(self) -> list[dict]:
        """Scan base directory and return list of available datasets."""
        results: list[dict] = []
        if not self._base_dir.exists():
            return results

        for exchange_dir in sorted(self._base_dir.iterdir()):
            if not exchange_dir.is_dir():
                continue
            exchange = exchange_dir.name
            for symbol_dir in sorted(exchange_dir.iterdir()):
                if not symbol_dir.is_dir():
                    continue
                symbol = symbol_dir.name.replace("_", "/")
                for pq_file in sorted(symbol_dir.glob("*.parquet")):
                    timeframe = pq_file.stem
                    try:
                        meta = pq.read_metadata(pq_file)
                        rows = meta.num_rows
                        df = pd.read_parquet(pq_file, columns=["timestamp"])
                        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                        start = df["timestamp"].min()
                        end = df["timestamp"].max()
                        mtime = datetime.fromtimestamp(
                            pq_file.stat().st_mtime, tz=timezone.utc
                        )
                        results.append({
                            "exchange": exchange,
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "rows": rows,
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                            "last_modified": mtime.isoformat(),
                        })
                    except Exception:
                        log.warning("Failed to read metadata for %s", pq_file)
        return results
