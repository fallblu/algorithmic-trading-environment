from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from analytics.metrics import compute_metrics, compute_drawdown_series
from models.fill import Fill
from models.order import OrderSide


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_equity_curve(values: list[float], start_ts: datetime | None = None):
    """Build an equity curve from a list of values."""
    if start_ts is None:
        start_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [(start_ts + timedelta(hours=i), v) for i, v in enumerate(values)]


def _make_fill(
    symbol: str = "BTC/USD",
    side: OrderSide = OrderSide.BUY,
    quantity: float = 1.0,
    price: float = 100.0,
    fee: float = 0.0,
    ts: datetime | None = None,
) -> Fill:
    if ts is None:
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return Fill(
        order_id="test",
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        fee=fee,
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def test_empty_equity_curve(self):
        m = compute_metrics([], [])
        assert m["total_return"] == 0.0
        assert m["num_bars"] == 0

    def test_single_bar(self):
        curve = _make_equity_curve([10000.0])
        m = compute_metrics(curve, [])
        assert m["total_return"] == 0.0

    def test_positive_return(self):
        curve = _make_equity_curve([10000.0, 10500.0, 11000.0])
        m = compute_metrics(curve, [], initial_cash=10000.0)
        assert m["total_return"] == pytest.approx(0.1)
        assert m["final_equity"] == 11000.0
        assert m["initial_equity"] == 10000.0
        assert m["num_bars"] == 3

    def test_negative_return(self):
        curve = _make_equity_curve([10000.0, 9500.0, 9000.0])
        m = compute_metrics(curve, [], initial_cash=10000.0)
        assert m["total_return"] == pytest.approx(-0.1)

    def test_sharpe_ratio_nonzero(self):
        # Steadily increasing equity -> positive Sharpe
        values = [10000 + i * 10 for i in range(100)]
        curve = _make_equity_curve(values)
        m = compute_metrics(curve, [], initial_cash=10000.0)
        assert m["sharpe_ratio"] > 0

    def test_max_drawdown(self):
        curve = _make_equity_curve([10000.0, 12000.0, 9000.0, 11000.0])
        m = compute_metrics(curve, [], initial_cash=10000.0)
        # Peak is 12000, trough is 9000 -> drawdown = 3000/12000 = 0.25
        assert m["max_drawdown"] == pytest.approx(0.25)

    def test_trade_analysis_with_fills(self):
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        fills = [
            _make_fill(side=OrderSide.BUY, price=100.0, quantity=1.0, ts=ts),
            _make_fill(
                side=OrderSide.SELL, price=110.0, quantity=1.0,
                ts=ts + timedelta(hours=1),
            ),
        ]
        curve = _make_equity_curve([10000.0, 10100.0, 10200.0])
        m = compute_metrics(curve, fills, initial_cash=10000.0)
        assert m["total_trades"] >= 1
        assert m["win_rate"] == 1.0

    def test_fees_tracked(self):
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        fills = [
            _make_fill(side=OrderSide.BUY, price=100.0, fee=5.0, ts=ts),
            _make_fill(
                side=OrderSide.SELL, price=110.0, fee=5.5,
                ts=ts + timedelta(hours=1),
            ),
        ]
        curve = _make_equity_curve([10000.0, 10100.0])
        m = compute_metrics(curve, fills, initial_cash=10000.0)
        assert m["total_fees"] == pytest.approx(10.5)


# ---------------------------------------------------------------------------
# compute_drawdown_series
# ---------------------------------------------------------------------------

class TestDrawdownSeries:
    def test_empty(self):
        assert compute_drawdown_series([]) == []

    def test_no_drawdown(self):
        curve = _make_equity_curve([100.0, 110.0, 120.0])
        dd = compute_drawdown_series(curve)
        assert all(v == 0.0 for _, v in dd)

    def test_drawdown_values(self):
        curve = _make_equity_curve([100.0, 120.0, 90.0, 110.0])
        dd = compute_drawdown_series(curve)
        # At 90: peak=120, dd = 30/120 = 0.25
        assert dd[2][1] == pytest.approx(0.25)
        # At 110: peak still 120, dd = 10/120
        assert dd[3][1] == pytest.approx(10 / 120)
