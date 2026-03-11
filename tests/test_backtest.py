"""Tests for BacktestContext."""

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import pandas as pd
import pytest

from data.store import MarketDataStore
from data.universe import Universe
from execution.backtest import BacktestContext
from models.bar import Bar
from models.instrument import FuturesInstrument, Instrument
from models.order import Order
from strategy.base import Strategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bars(symbol: str, n: int, start: datetime, interval_minutes: int = 60):
    """Generate *n* synthetic OHLCV bars with a simple upward drift."""
    bars = []
    price = Decimal("100")
    for i in range(n):
        ts = start + timedelta(minutes=interval_minutes * i)
        o = price
        h = price + Decimal("2")
        l = price - Decimal("1")
        c = price + Decimal("1")
        bars.append(
            Bar(
                instrument_symbol=symbol,
                timestamp=ts,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=Decimal("10"),
                trades=5,
            )
        )
        price = c  # drift upward
    return bars


class DummyStrategy(Strategy):
    """A no-op strategy that returns no orders on every bar."""

    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        return []

    def universe(self) -> list[str]:
        return self.params.get("symbols", ["BTC/USD"])

    def lookback(self) -> int:
        return 1


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBacktestContextInstantiation:
    def test_basic_instantiation(self, tmp_path):
        """BacktestContext can be created with a Universe and data_dir."""
        uni = Universe.from_symbols(["BTC/USD"], "1h")
        ctx = BacktestContext(universe=uni, data_dir=tmp_path)
        assert ctx.get_universe() is uni

    def test_mode_is_backtest(self, tmp_path):
        """The mode property must be 'backtest'."""
        uni = Universe.from_symbols(["ETH/USD"], "1h")
        ctx = BacktestContext(universe=uni, data_dir=tmp_path)
        assert ctx.mode == "backtest"


class TestBacktestRun:
    def test_run_with_dummy_strategy(self, tmp_path):
        """Run a full backtest with synthetic bars and a no-op strategy."""
        symbol = "BTC/USD"
        exchange = "kraken"
        timeframe = "1h"
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        n_bars = 20

        # Write synthetic bars to the store
        store = MarketDataStore(tmp_path)
        bars = _make_bars(symbol, n_bars, start)
        store.write_bars(bars, exchange=exchange, timeframe=timeframe)

        # Build universe and context
        uni = Universe.from_symbols([symbol], timeframe, exchange=exchange)
        ctx = BacktestContext(
            universe=uni,
            start=start,
            end=start + timedelta(hours=n_bars),
            initial_cash=Decimal("10000"),
            data_dir=tmp_path,
            exchange=exchange,
        )

        strategy = DummyStrategy(ctx, params={"symbols": [symbol]})
        result = ctx.run(strategy)

        # Verify result structure
        assert "equity_curve" in result
        assert "bars_processed" in result
        assert result["bars_processed"] == n_bars

        # Equity curve should have entries (initial + one per bar processed)
        assert len(result["equity_curve"]) > 0

        # Each equity point is (datetime, Decimal)
        ts, eq = result["equity_curve"][0]
        assert isinstance(ts, datetime)
        assert isinstance(eq, Decimal)

        # No orders submitted, so equity should remain at initial cash
        assert result["equity_curve"][-1][1] == Decimal("10000")


class TestExchangeAutoDetection:
    def test_exchange_from_universe(self, tmp_path):
        """Exchange should be auto-detected from the first instrument."""
        uni = Universe.from_symbols(["BTC/USD"], "1h", exchange="binance")
        ctx = BacktestContext(universe=uni, data_dir=tmp_path)
        assert ctx._exchange == "binance"

    def test_default_exchange_empty_universe(self, tmp_path):
        """With an empty universe the exchange falls back to 'kraken'."""
        uni = Universe(instruments={}, timeframe="1h")
        ctx = BacktestContext(universe=uni, data_dir=tmp_path)
        assert ctx._exchange == "kraken"


class TestMarginModeAutoDetection:
    def test_margin_mode_false_for_spot(self, tmp_path):
        """Spot instruments should result in margin_mode=False."""
        uni = Universe.from_symbols(["BTC/USD"], "1h")
        ctx = BacktestContext(universe=uni, data_dir=tmp_path)
        assert ctx._broker.margin_mode is False

    def test_margin_mode_true_for_futures(self, tmp_path):
        """FuturesInstrument in the universe should trigger margin mode."""
        uni = Universe.from_futures_symbols(["BTC-PERP"], "1h")
        ctx = BacktestContext(universe=uni, data_dir=tmp_path)
        assert ctx._broker.margin_mode is True
