"""Tests for PricePanel — rolling window MultiIndex DataFrame builder."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from data.price_panel import PricePanel
from data.universe import Universe
from tests.conftest import make_bar


@pytest.fixture
def btc_universe():
    return Universe.from_symbols(["BTC/USD"], "1h", "kraken")


@pytest.fixture
def multi_universe():
    return Universe.from_symbols(["BTC/USD", "ETH/USD"], "1h", "kraken")


class TestAppendAndWindow:
    def test_single_bar(self, btc_universe):
        panel = PricePanel(btc_universe, lookback=10)
        bar = make_bar("BTC/USD", close=50000)
        panel.append_bar(bar)

        df = panel.get_window()
        assert not df.empty
        assert "close" in df.columns
        assert float(df["close"].iloc[0]) == 50000.0

    def test_lookback_limit(self, btc_universe):
        panel = PricePanel(btc_universe, lookback=5)
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)

        for i in range(10):
            bar = make_bar("BTC/USD", timestamp=base + timedelta(hours=i),
                           close=50000 + i * 100)
            panel.append_bar(bar)

        df = panel.get_window()
        # Only the last 5 bars should be in the window
        assert len(df) == 5

    def test_empty_panel(self, btc_universe):
        panel = PricePanel(btc_universe, lookback=10)
        df = panel.get_window()
        assert df.empty

    def test_unknown_symbol_ignored(self, btc_universe):
        panel = PricePanel(btc_universe, lookback=10)
        bar = make_bar("ETH/USD", close=3000)
        panel.append_bar(bar)  # Should be silently ignored
        df = panel.get_window()
        assert df.empty


class TestMultiSymbol:
    def test_inner_join_timestamps(self, multi_universe):
        panel = PricePanel(multi_universe, lookback=10)
        ts1 = datetime(2024, 1, 1, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 1, 1, 1, tzinfo=timezone.utc)

        # Both symbols at ts1
        panel.append_bar(make_bar("BTC/USD", timestamp=ts1, close=50000))
        panel.append_bar(make_bar("ETH/USD", timestamp=ts1, close=3000))

        # Only BTC at ts2
        panel.append_bar(make_bar("BTC/USD", timestamp=ts2, close=51000))

        df = panel.get_window()
        # ts2 should be excluded because ETH is missing
        timestamps = df.index.get_level_values("timestamp").unique()
        assert len(timestamps) == 1
        assert timestamps[0] == ts1

    def test_append_bars_bulk(self, multi_universe):
        panel = PricePanel(multi_universe, lookback=10)
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        bars = [
            make_bar("BTC/USD", timestamp=ts, close=50000),
            make_bar("ETH/USD", timestamp=ts, close=3000),
        ]
        panel.append_bars(bars)
        df = panel.get_window()
        symbols = df.index.get_level_values("symbol").unique().tolist()
        assert "BTC/USD" in symbols
        assert "ETH/USD" in symbols


class TestProperties:
    def test_is_ready(self, multi_universe):
        panel = PricePanel(multi_universe, lookback=10)
        assert not panel.is_ready

        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        panel.append_bar(make_bar("BTC/USD", timestamp=ts))
        assert not panel.is_ready  # ETH still missing

        panel.append_bar(make_bar("ETH/USD", timestamp=ts))
        assert panel.is_ready

    def test_latest_timestamp(self, btc_universe):
        panel = PricePanel(btc_universe, lookback=10)
        assert panel.latest_timestamp is None

        ts = datetime(2024, 1, 1, 5, tzinfo=timezone.utc)
        panel.append_bar(make_bar("BTC/USD", timestamp=ts))
        assert panel.latest_timestamp == ts
