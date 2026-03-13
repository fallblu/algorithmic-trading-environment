from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest

from charts.registry import ChartRegistry, BUILT_IN_SERIES
from charts.series import close_series, equity_series, drawdown_series, fills_series
from models.fill import Fill
from models.order import OrderSide


# ---------------------------------------------------------------------------
# Chart Registry
# ---------------------------------------------------------------------------

class TestChartRegistry:
    def test_built_in_series_present(self):
        registry = ChartRegistry()
        series = registry.discover_all()
        assert "price.candlestick" in series
        assert "volume" in series
        assert "equity" in series
        assert "drawdown" in series
        assert "fills" in series

    def test_list_overlays(self):
        registry = ChartRegistry()
        registry.discover_all()
        overlays = registry.list_overlays()
        assert any(s.key == "price.candlestick" for s in overlays)
        assert all(not s.subplot for s in overlays)

    def test_list_subplots(self):
        registry = ChartRegistry()
        registry.discover_all()
        subplots = registry.list_subplots()
        assert any(s.key == "volume" for s in subplots)
        assert all(s.subplot for s in subplots)

    def test_discover_with_user_module(self, tmp_path):
        # Create a fake user module
        mod_dir = tmp_path / "my_signals"
        mod_dir.mkdir()
        (mod_dir / "__init__.py").write_text("")
        (mod_dir / "indicators.py").write_text("""
import pandas as pd

def my_indicator(bars, window=20):
    return bars["close"].rolling(window).mean()

__charts__ = {
    "my_sma": {
        "type": "line",
        "subplot": False,
        "description": "Custom SMA",
        "compute": my_indicator,
        "params": {"window": 20},
    },
}
""")

        registry = ChartRegistry(lib_dir=tmp_path)
        series = registry.discover_all()
        assert "my_signals.my_sma" in series
        assert series["my_signals.my_sma"].series_type == "line"
        assert series["my_signals.my_sma"].source == "my_signals"


# ---------------------------------------------------------------------------
# Series helpers
# ---------------------------------------------------------------------------

class TestSeriesHelpers:
    def _make_df(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=5, freq="h", tz=timezone.utc)
        return pd.DataFrame({
            "open": [100, 102, 101, 103, 104],
            "high": [105, 106, 104, 107, 108],
            "low": [99, 100, 99, 101, 102],
            "close": [102, 101, 103, 104, 106],
            "volume": [1000, 1100, 900, 1200, 1300],
        }, index=dates)

    def test_close_series(self):
        df = self._make_df()
        result = close_series(df)
        assert len(result) == 5
        assert result.iloc[-1] == 106

    def test_equity_series(self):
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        curve = [(ts + timedelta(hours=i), 10000 + i * 100) for i in range(5)]
        result = equity_series(curve)
        assert len(result) == 5
        assert result.iloc[-1] == 10400

    def test_drawdown_series(self):
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        curve = [
            (ts, 10000),
            (ts + timedelta(hours=1), 12000),
            (ts + timedelta(hours=2), 9000),
        ]
        result = drawdown_series(curve)
        assert len(result) == 3
        assert result.iloc[2] == pytest.approx(0.25)

    def test_fills_series_empty(self):
        result = fills_series([])
        assert len(result) == 0

    def test_fills_series(self):
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        fills = [
            Fill(order_id="o1", symbol="BTC/USD", side=OrderSide.BUY,
                 quantity=1.0, price=100.0, fee=0.1, timestamp=ts),
            Fill(order_id="o2", symbol="BTC/USD", side=OrderSide.SELL,
                 quantity=1.0, price=110.0, fee=0.1, timestamp=ts + timedelta(hours=1)),
        ]
        result = fills_series(fills)
        assert len(result) == 2
        assert result.iloc[0]["side"] == "buy"
        assert result.iloc[1]["side"] == "sell"
