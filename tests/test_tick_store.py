import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from data.tick_store import TickStore


def _make_ticks_df(timestamps, bid=1.1000, spread=0.0002, volume=1000.0):
    rows = []
    for ts in timestamps:
        ask = bid + spread
        mid = (bid + ask) / 2
        rows.append({
            "timestamp": ts,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": spread,
            "volume": volume,
        })
    return pd.DataFrame(rows)


def test_write_and_read_ticks_roundtrip(tmp_path):
    store = TickStore(tmp_path)
    timestamps = pd.date_range("2024-01-15 10:00", periods=5, freq="s", tz="UTC")
    df = _make_ticks_df(timestamps)

    store.write_ticks(df, exchange="oanda", pair="EUR/USD")
    result = store.read_ticks("oanda", "EUR/USD")

    assert len(result) == 5
    assert "bid" in result.columns
    assert "ask" in result.columns
    assert "mid" in result.columns


def test_date_based_file_routing(tmp_path):
    store = TickStore(tmp_path)
    ts_day1 = pd.date_range("2024-01-15 23:59:58", periods=2, freq="s", tz="UTC")
    ts_day2 = pd.date_range("2024-01-16 00:00:00", periods=3, freq="s", tz="UTC")
    all_ts = ts_day1.append(ts_day2)
    df = _make_ticks_df(all_ts)

    store.write_ticks(df, exchange="oanda", pair="EUR/USD")

    # Should have created two parquet files, one per day
    pair_dir = tmp_path / "oanda" / "EUR_USD"
    files = sorted(pair_dir.glob("*.parquet"))
    assert len(files) == 2
    assert files[0].stem == "2024-01-15"
    assert files[1].stem == "2024-01-16"

    # Reading back should merge all
    result = store.read_ticks("oanda", "EUR/USD")
    assert len(result) == 5


def test_deduplication_on_timestamp(tmp_path):
    store = TickStore(tmp_path)
    timestamps = pd.date_range("2024-01-15 10:00", periods=3, freq="s", tz="UTC")
    df1 = _make_ticks_df(timestamps, bid=1.1000)
    store.write_ticks(df1, exchange="oanda", pair="EUR/USD")

    # Write overlapping ticks with different bid — last write wins
    df2 = _make_ticks_df(timestamps[:2], bid=1.2000)
    store.write_ticks(df2, exchange="oanda", pair="EUR/USD")

    result = store.read_ticks("oanda", "EUR/USD")
    assert len(result) == 3
    # The first two ticks should have been overwritten with bid=1.2
    assert result.iloc[0]["bid"] == 1.2000
    assert result.iloc[1]["bid"] == 1.2000
    # The third tick should retain original bid
    assert result.iloc[2]["bid"] == 1.1000


def test_aggregate_to_bars_output_structure(tmp_path):
    store = TickStore(tmp_path)
    # Create 120 ticks spanning 2 hours (one per minute)
    timestamps = pd.date_range("2024-01-15 10:00", periods=120, freq="min", tz="UTC")
    df = _make_ticks_df(timestamps, bid=1.1000)
    store.write_ticks(df, exchange="oanda", pair="EUR/USD")

    bars = store.aggregate_to_bars("oanda", "EUR/USD", timeframe="1h")
    assert not bars.empty
    expected_cols = {"timestamp", "open", "high", "low", "close", "volume"}
    assert expected_cols.issubset(set(bars.columns))
    # 2 hours of minute data should produce at least 1 bar
    assert len(bars) >= 1
