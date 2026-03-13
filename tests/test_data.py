from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.store import MarketDataStore
from models.bar import Bar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bars(
    symbol: str = "BTC/USD",
    count: int = 5,
    start_hour: int = 0,
) -> list[Bar]:
    """Create a list of sequential hourly bars for testing."""
    bars: list[Bar] = []
    for i in range(count):
        bars.append(Bar(
            symbol=symbol,
            timestamp=datetime(2024, 1, 1, start_hour + i, 0, 0, tzinfo=timezone.utc),
            open=100.0 + i,
            high=110.0 + i,
            low=90.0 + i,
            close=105.0 + i,
            volume=1000.0 + i * 100,
        ))
    return bars


# ---------------------------------------------------------------------------
# MarketDataStore — write_bars / read_bars round-trip
# ---------------------------------------------------------------------------

class TestMarketDataStoreRoundTrip:
    def test_write_then_read_bars(self, tmp_path):
        store = MarketDataStore(tmp_path)
        bars = _make_bars(count=3)

        row_count = store.write_bars(bars, exchange="kraken", timeframe="1h")
        assert row_count == 3

        result = store.read_bars("kraken", "BTC/USD", "1h")
        assert len(result) == 3

        for orig, loaded in zip(bars, result):
            assert loaded.symbol == orig.symbol
            assert loaded.open == orig.open
            assert loaded.high == orig.high
            assert loaded.low == orig.low
            assert loaded.close == orig.close
            assert loaded.volume == orig.volume

    def test_write_empty_bars_returns_zero(self, tmp_path):
        store = MarketDataStore(tmp_path)
        assert store.write_bars([], exchange="kraken", timeframe="1h") == 0


# ---------------------------------------------------------------------------
# MarketDataStore — read_dataframe with date filtering
# ---------------------------------------------------------------------------

class TestMarketDataStoreReadDataframe:
    def test_read_dataframe_no_filter(self, tmp_path):
        store = MarketDataStore(tmp_path)
        bars = _make_bars(count=5)
        store.write_bars(bars, exchange="kraken", timeframe="1h")

        df = store.read_dataframe("kraken", "BTC/USD", "1h")
        assert len(df) == 5

    def test_read_dataframe_with_start_filter(self, tmp_path):
        store = MarketDataStore(tmp_path)
        bars = _make_bars(count=5)  # hours 0..4
        store.write_bars(bars, exchange="kraken", timeframe="1h")

        # Use naive datetime — store applies tz="UTC" internally
        start = datetime(2024, 1, 1, 2, 0, 0)
        df = store.read_dataframe("kraken", "BTC/USD", "1h", start=start)
        assert len(df) == 3  # hours 2, 3, 4

    def test_read_dataframe_with_end_filter(self, tmp_path):
        store = MarketDataStore(tmp_path)
        bars = _make_bars(count=5)  # hours 0..4
        store.write_bars(bars, exchange="kraken", timeframe="1h")

        end = datetime(2024, 1, 1, 2, 0, 0)
        df = store.read_dataframe("kraken", "BTC/USD", "1h", end=end)
        assert len(df) == 3  # hours 0, 1, 2

    def test_read_dataframe_with_start_and_end(self, tmp_path):
        store = MarketDataStore(tmp_path)
        bars = _make_bars(count=5)  # hours 0..4
        store.write_bars(bars, exchange="kraken", timeframe="1h")

        start = datetime(2024, 1, 1, 1, 0, 0)
        end = datetime(2024, 1, 1, 3, 0, 0)
        df = store.read_dataframe("kraken", "BTC/USD", "1h", start=start, end=end)
        assert len(df) == 3  # hours 1, 2, 3

    def test_read_dataframe_no_data_returns_empty(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = store.read_dataframe("kraken", "BTC/USD", "1h")
        assert df.empty
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# MarketDataStore — has_data
# ---------------------------------------------------------------------------

class TestMarketDataStoreHasData:
    def test_has_data_false_when_empty(self, tmp_path):
        store = MarketDataStore(tmp_path)
        assert store.has_data("kraken", "BTC/USD", "1h") is False

    def test_has_data_true_after_write(self, tmp_path):
        store = MarketDataStore(tmp_path)
        bars = _make_bars(count=1)
        store.write_bars(bars, exchange="kraken", timeframe="1h")
        assert store.has_data("kraken", "BTC/USD", "1h") is True

    def test_has_data_false_for_different_symbol(self, tmp_path):
        store = MarketDataStore(tmp_path)
        bars = _make_bars(symbol="BTC/USD", count=1)
        store.write_bars(bars, exchange="kraken", timeframe="1h")
        assert store.has_data("kraken", "ETH/USD", "1h") is False


# ---------------------------------------------------------------------------
# MarketDataStore — get_date_range
# ---------------------------------------------------------------------------

class TestMarketDataStoreGetDateRange:
    def test_get_date_range_returns_min_max(self, tmp_path):
        store = MarketDataStore(tmp_path)
        bars = _make_bars(count=5)  # hours 0..4
        store.write_bars(bars, exchange="kraken", timeframe="1h")

        result = store.get_date_range("kraken", "BTC/USD", "1h")
        assert result is not None
        earliest, latest = result
        assert earliest.hour == 0
        assert latest.hour == 4

    def test_get_date_range_none_when_no_data(self, tmp_path):
        store = MarketDataStore(tmp_path)
        result = store.get_date_range("kraken", "BTC/USD", "1h")
        assert result is None


# ---------------------------------------------------------------------------
# MarketDataStore — get_row_count
# ---------------------------------------------------------------------------

class TestMarketDataStoreGetRowCount:
    def test_get_row_count(self, tmp_path):
        store = MarketDataStore(tmp_path)
        bars = _make_bars(count=7)
        store.write_bars(bars, exchange="kraken", timeframe="1h")

        assert store.get_row_count("kraken", "BTC/USD", "1h") == 7

    def test_get_row_count_zero_when_no_data(self, tmp_path):
        store = MarketDataStore(tmp_path)
        assert store.get_row_count("kraken", "BTC/USD", "1h") == 0


# ---------------------------------------------------------------------------
# MarketDataStore — inventory
# ---------------------------------------------------------------------------

class TestMarketDataStoreInventory:
    def test_inventory_empty_when_no_data(self, tmp_path):
        store = MarketDataStore(tmp_path)
        assert store.inventory() == []

    def test_inventory_lists_datasets(self, tmp_path):
        store = MarketDataStore(tmp_path)
        store.write_bars(_make_bars(symbol="BTC/USD", count=3), exchange="kraken", timeframe="1h")
        store.write_bars(_make_bars(symbol="ETH/USD", count=2), exchange="kraken", timeframe="1h")

        inv = store.inventory()
        assert len(inv) == 2

        symbols = {item["symbol"] for item in inv}
        assert symbols == {"BTC/USD", "ETH/USD"}

        for item in inv:
            assert "exchange" in item
            assert "timeframe" in item
            assert "rows" in item
            assert "start" in item
            assert "end" in item
            assert "last_modified" in item
            assert item["exchange"] == "kraken"
            assert item["timeframe"] == "1h"

    def test_inventory_row_counts_correct(self, tmp_path):
        store = MarketDataStore(tmp_path)
        store.write_bars(_make_bars(symbol="BTC/USD", count=5), exchange="kraken", timeframe="1h")

        inv = store.inventory()
        assert len(inv) == 1
        assert inv[0]["rows"] == 5

    def test_inventory_nonexistent_base_dir(self, tmp_path):
        store = MarketDataStore(tmp_path / "nonexistent")
        assert store.inventory() == []


# ---------------------------------------------------------------------------
# MarketDataStore — write_bars merge/dedup
# ---------------------------------------------------------------------------

class TestMarketDataStoreMergeDedup:
    def test_write_bars_merges_with_existing(self, tmp_path):
        store = MarketDataStore(tmp_path)

        # Write first batch: hours 0, 1, 2
        batch1 = _make_bars(count=3, start_hour=0)
        store.write_bars(batch1, exchange="kraken", timeframe="1h")

        # Write second batch: hours 3, 4
        batch2 = _make_bars(count=2, start_hour=3)
        row_count = store.write_bars(batch2, exchange="kraken", timeframe="1h")

        assert row_count == 5
        bars = store.read_bars("kraken", "BTC/USD", "1h")
        assert len(bars) == 5

    def test_write_bars_deduplicates_by_timestamp(self, tmp_path):
        store = MarketDataStore(tmp_path)

        # Write bars for hours 0, 1, 2
        batch1 = _make_bars(count=3, start_hour=0)
        store.write_bars(batch1, exchange="kraken", timeframe="1h")

        # Write overlapping bars for hours 1, 2, 3 (hours 1 and 2 overlap)
        batch2 = _make_bars(count=3, start_hour=1)
        row_count = store.write_bars(batch2, exchange="kraken", timeframe="1h")

        # Should have 4 unique timestamps: hours 0, 1, 2, 3
        assert row_count == 4
        bars = store.read_bars("kraken", "BTC/USD", "1h")
        assert len(bars) == 4

    def test_write_bars_dedup_keeps_last(self, tmp_path):
        store = MarketDataStore(tmp_path)

        ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        bar_v1 = Bar(
            symbol="BTC/USD", timestamp=ts,
            open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0,
        )
        store.write_bars([bar_v1], exchange="kraken", timeframe="1h")

        # Write same timestamp with different close price
        bar_v2 = Bar(
            symbol="BTC/USD", timestamp=ts,
            open=100.0, high=110.0, low=90.0, close=999.0, volume=2000.0,
        )
        store.write_bars([bar_v2], exchange="kraken", timeframe="1h")

        bars = store.read_bars("kraken", "BTC/USD", "1h")
        assert len(bars) == 1
        # keep="last" means the newer write wins
        assert bars[0].close == 999.0
        assert bars[0].volume == 2000.0

    def test_write_bars_sorted_by_timestamp(self, tmp_path):
        store = MarketDataStore(tmp_path)

        # Write bars in reverse order
        bars_reversed = list(reversed(_make_bars(count=5)))
        store.write_bars(bars_reversed, exchange="kraken", timeframe="1h")

        result = store.read_bars("kraken", "BTC/USD", "1h")
        timestamps = [b.timestamp for b in result]
        assert timestamps == sorted(timestamps)
