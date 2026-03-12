"""Tests for performance metrics computation."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from analytics.performance import compute_performance
from models.fill import Fill
from models.order import OrderSide


class TestComputePerformance:
    def _make_equity_curve(self, values):
        """Build equity curve from a list of float values."""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return [(base + timedelta(hours=i), Decimal(str(v))) for i, v in enumerate(values)]

    def test_basic_metrics(self, btc_instrument):
        # Simple upward equity curve
        values = [10000 + i * 10 for i in range(100)]
        curve = self._make_equity_curve(values)

        metrics = compute_performance(curve, fills=[], periods_per_year=8760)
        assert metrics["total_return"] > 0
        assert "sharpe_ratio" in metrics
        assert "max_drawdown" in metrics

    def test_flat_equity(self):
        values = [10000] * 100
        curve = self._make_equity_curve(values)
        metrics = compute_performance(curve, fills=[])
        assert metrics["total_return"] == pytest.approx(0, abs=1e-10)

    def test_drawdown(self):
        # Peak at 12000, trough at 9000 → drawdown = 3000/12000 = 25%
        values = list(range(10000, 12001, 100)) + list(range(12000, 8999, -100))
        curve = self._make_equity_curve(values)
        metrics = compute_performance(curve, fills=[])
        assert metrics["max_drawdown"] >= 0.20

    def test_with_fills(self, btc_instrument):
        curve = self._make_equity_curve([10000, 10100, 10200, 10150, 10300])
        fills = [
            Fill(order_id="1", instrument=btc_instrument, side=OrderSide.BUY,
                 quantity=Decimal("0.1"), price=Decimal("50000"),
                 fee=Decimal("5"), fee_currency="USD",
                 timestamp=datetime(2024, 1, 1, 1, tzinfo=timezone.utc)),
            Fill(order_id="2", instrument=btc_instrument, side=OrderSide.SELL,
                 quantity=Decimal("0.1"), price=Decimal("51000"),
                 fee=Decimal("5"), fee_currency="USD",
                 timestamp=datetime(2024, 1, 1, 3, tzinfo=timezone.utc)),
        ]
        metrics = compute_performance(curve, fills=fills)
        assert metrics["num_trades"] >= 1
        assert "total_fees" in metrics

    def test_negative_return(self):
        values = [10000, 9500, 9000, 8500, 8000]
        curve = self._make_equity_curve(values)
        metrics = compute_performance(curve, fills=[])
        assert metrics["total_return"] < 0

    def test_single_point_curve(self):
        curve = self._make_equity_curve([10000])
        metrics = compute_performance(curve, fills=[])
        # Should not crash
        assert "total_return" in metrics

    def test_empty_curve(self):
        metrics = compute_performance([], fills=[])
        assert "total_return" in metrics
