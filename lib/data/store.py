from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from models.bar import Bar


class MarketDataStore:
    """Local Parquet-based storage for OHLCV bar data.

    Layout: {base_dir}/{exchange}/{symbol}/{timeframe}.parquet
    """

    SCHEMA = pa.schema([
        ("timestamp", pa.timestamp("us")),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("volume", pa.float64()),
        ("trades", pa.int64()),
        ("vwap", pa.float64()),
    ])

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def _path_for(self, exchange: str, symbol: str, timeframe: str) -> Path:
        safe_symbol = symbol.replace("/", "_")
        return self.base_dir / exchange / safe_symbol / f"{timeframe}.parquet"

    def write_bars(self, bars: list[Bar], exchange: str, timeframe: str) -> None:
        if not bars:
            return
        symbol = bars[0].instrument_symbol
        path = self._path_for(exchange, symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)

        rows = []
        for bar in bars:
            rows.append({
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
                "trades": bar.trades,
                "vwap": float(bar.vwap) if bar.vwap is not None else None,
            })

        new_df = pd.DataFrame(rows)
        new_df["timestamp"] = pd.to_datetime(new_df["timestamp"], utc=True)

        if path.exists():
            existing_df = pd.read_parquet(path)
            existing_df["timestamp"] = pd.to_datetime(existing_df["timestamp"], utc=True)
            combined = pd.concat([existing_df, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
            combined = combined.sort_values("timestamp").reset_index(drop=True)
        else:
            combined = new_df.sort_values("timestamp").reset_index(drop=True)

        table = pa.Table.from_pandas(combined, schema=self.SCHEMA, preserve_index=False)
        pq.write_table(table, path)

    def read_bars(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        path = self._path_for(exchange, symbol, timeframe)
        if not path.exists():
            return []

        df = pd.read_parquet(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        if start is not None:
            start_ts = pd.Timestamp(start)
            if start_ts.tzinfo is None:
                start_ts = start_ts.tz_localize("UTC")
            df = df[df["timestamp"] >= start_ts]
        if end is not None:
            end_ts = pd.Timestamp(end)
            if end_ts.tzinfo is None:
                end_ts = end_ts.tz_localize("UTC")
            df = df[df["timestamp"] <= end_ts]

        df = df.sort_values("timestamp")

        bars = []
        for _, row in df.iterrows():
            bars.append(Bar(
                instrument_symbol=symbol,
                timestamp=row["timestamp"].to_pydatetime(),
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row["volume"])),
                trades=int(row["trades"]) if pd.notna(row["trades"]) else None,
                vwap=Decimal(str(row["vwap"])) if pd.notna(row["vwap"]) else None,
            ))
        return bars

    def has_data(self, exchange: str, symbol: str, timeframe: str) -> bool:
        return self._path_for(exchange, symbol, timeframe).exists()

    def get_date_range(
        self, exchange: str, symbol: str, timeframe: str
    ) -> tuple[datetime, datetime] | None:
        path = self._path_for(exchange, symbol, timeframe)
        if not path.exists():
            return None
        df = pd.read_parquet(path, columns=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df["timestamp"].min().to_pydatetime(), df["timestamp"].max().to_pydatetime()
