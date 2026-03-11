"""Tests for analytics/performance.py metric functions."""

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import isclose, sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from analytics.performance import (
    _max_drawdown,
    _sharpe_ratio,
    _trade_analysis,
    compute_performance,
)
from models.fill import Fill
from models.instrument import Instrument
from models.order import OrderSide


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _equity_curve(equities: list[float], start: datetime | None = None):
    """Build an equity curve list[(datetime, Decimal)] from raw floats."""
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        (start + timedelta(hours=i), Decimal(str(e)))
        for i, e in enumerate(equities)
    ]


def _dummy_instrument():
    return Instrument(
        symbol="BTC/USD",
        base="BTC",
        quote="USD",
        exchange="kraken",
        asset_class="crypto",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.00001"),
        min_notional=Decimal("5"),
    )


# ---------------------------------------------------------------------------
# Sharpe ratio
# ---------------------------------------------------------------------------

class TestSharpeRatio:
    def test_known_values(self):
        """Sharpe with known returns should be computable and match manual calc."""
        # Returns: +1%, -1% alternating => mean = 0, so sharpe should be ~0
        returns = [0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01]
        sharpe = _sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=252)
        # Mean excess return is 0 => sharpe == 0
        assert isclose(sharpe, 0.0, abs_tol=1e-9)

    def test_positive_sharpe(self):
        """A mix of positive and negative returns should give a finite Sharpe."""
        returns = [0.02, -0.01, 0.03, -0.005, 0.015, -0.002, 0.01, 0.005, -0.01, 0.02]
        sharpe = _sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=252)
        assert sharpe > 0

    def test_empty_returns(self):
        assert _sharpe_ratio([], 0.0, 252) == 0.0


# ---------------------------------------------------------------------------
# Max drawdown
# ---------------------------------------------------------------------------

class TestMaxDrawdown:
    def test_simple_drawdown(self):
        """Peak 120, trough 90 => dd = 30/120 = 0.25."""
        equities = [100.0, 110.0, 120.0, 100.0, 90.0, 95.0]
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        timestamps = [start + timedelta(hours=i) for i in range(len(equities))]

        dd, duration = _max_drawdown(equities, timestamps)
        assert isclose(dd, 0.25, rel_tol=1e-9)
        assert duration == timedelta(hours=2)  # index 2 -> index 4

    def test_no_drawdown(self):
        """Monotonically increasing equity has zero drawdown."""
        equities = [100.0, 110.0, 120.0, 130.0]
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        timestamps = [start + timedelta(hours=i) for i in range(len(equities))]

        dd, duration = _max_drawdown(equities, timestamps)
        assert dd == 0.0


# ---------------------------------------------------------------------------
# Win rate (via _trade_analysis)
# ---------------------------------------------------------------------------

class TestWinRate:
    def test_win_rate_calculation(self):
        """Two wins and one loss should give win_rate = 2/3."""
        inst = _dummy_instrument()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

        fills = [
            # Trade 1: buy 100, sell 110 => win
            Fill("o1", inst, OrderSide.BUY, Decimal("1"), Decimal("100"),
                 Decimal("0"), "USD", start),
            Fill("o2", inst, OrderSide.SELL, Decimal("1"), Decimal("110"),
                 Decimal("0"), "USD", start + timedelta(hours=1)),
            # Trade 2: buy 100, sell 105 => win
            Fill("o3", inst, OrderSide.BUY, Decimal("1"), Decimal("100"),
                 Decimal("0"), "USD", start + timedelta(hours=2)),
            Fill("o4", inst, OrderSide.SELL, Decimal("1"), Decimal("105"),
                 Decimal("0"), "USD", start + timedelta(hours=3)),
            # Trade 3: buy 100, sell 90 => loss
            Fill("o5", inst, OrderSide.BUY, Decimal("1"), Decimal("100"),
                 Decimal("0"), "USD", start + timedelta(hours=4)),
            Fill("o6", inst, OrderSide.SELL, Decimal("1"), Decimal("90"),
                 Decimal("0"), "USD", start + timedelta(hours=5)),
        ]
        stats = _trade_analysis(fills)

        assert stats["num_trades"] == 3
        assert isclose(stats["win_rate"], 2 / 3, rel_tol=1e-4)

    def test_no_fills(self):
        stats = _trade_analysis([])
        assert stats["win_rate"] == 0.0
        assert stats["num_trades"] == 0


# ---------------------------------------------------------------------------
# Total return (via compute_performance)
# ---------------------------------------------------------------------------

class TestTotalReturn:
    def test_total_return_positive(self):
        """10000 -> 12000 should give total_return = 0.2."""
        curve = _equity_curve([10000.0, 10500.0, 11000.0, 12000.0])
        metrics = compute_performance(curve, fills=[])
        assert isclose(metrics["total_return"], 0.2, rel_tol=1e-6)

    def test_total_return_negative(self):
        """10000 -> 8000 should give total_return = -0.2."""
        curve = _equity_curve([10000.0, 9000.0, 8000.0])
        metrics = compute_performance(curve, fills=[])
        assert isclose(metrics["total_return"], -0.2, rel_tol=1e-6)

    def test_total_return_zero(self):
        """Flat equity should give total_return = 0."""
        curve = _equity_curve([10000.0, 10000.0, 10000.0])
        metrics = compute_performance(curve, fills=[])
        assert metrics["total_return"] == 0.0
