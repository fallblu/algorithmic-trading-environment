"""Tests for MarketDataStore — Parquet read/write."""

import tempfile
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from data.store import MarketDataStore
from models.bar import Bar


def _make_bars(symbol="BTC/USD", n=10, start_price=50000):
    bars = []
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        bars.append(Bar(
            instrument_symbol=symbol,
            timestamp=base + timedelta(hours=i),
            open=Decimal(str(start_price + i * 10)),
            high=Decimal(str(start_price + i * 10 + 50)),
            low=Decimal(str(start_price + i * 10 - 50)),
            close=Decimal(str(start_price + i * 10 + 20)),
            volume=Decimal("100"),
        ))
    return bars


class TestWriteAndRead:
    def test_write_then_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MarketDataStore(base_dir=Path(tmpdir))
            bars = _make_bars(n=10)
            store.write_bars(bars, exchange="kraken", timeframe="1h")

            loaded = store.read_bars(
                symbol="BTC/USD",
                timeframe="1h",
                exchange="kraken",
            )
            assert len(loaded) >= 10

    def test_deduplication(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MarketDataStore(base_dir=Path(tmpdir))
            bars = _make_bars(n=5)
            store.write_bars(bars, exchange="kraken", timeframe="1h")
            store.write_bars(bars, exchange="kraken", timeframe="1h")  # Write same bars again

            loaded = store.read_bars(
                symbol="BTC/USD",
                timeframe="1h",
                exchange="kraken",
            )
            # Should have 5, not 10 (deduped)
            assert len(loaded) == 5

    def test_date_range_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MarketDataStore(base_dir=Path(tmpdir))
            bars = _make_bars(n=24)
            store.write_bars(bars, exchange="kraken", timeframe="1h")

            start = datetime(2024, 1, 1, 5, tzinfo=timezone.utc)
            end = datetime(2024, 1, 1, 15, tzinfo=timezone.utc)
            loaded = store.read_bars(
                symbol="BTC/USD",
                timeframe="1h",
                exchange="kraken",
                start=start,
                end=end,
            )
            for bar in loaded:
                assert bar.timestamp >= start
                assert bar.timestamp <= end

    def test_empty_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MarketDataStore(base_dir=Path(tmpdir))
            loaded = store.read_bars(
                symbol="NONEXISTENT/USD",
                timeframe="1h",
                exchange="kraken",
            )
            assert len(loaded) == 0
