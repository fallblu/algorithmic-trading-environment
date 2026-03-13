"""Built-in chart data series — compute data for standard chart types."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from analytics.metrics import compute_drawdown_series
from models.fill import Fill
from models.order import OrderSide


def price_series(df: pd.DataFrame) -> pd.DataFrame:
    """Return OHLCV DataFrame for price charting."""
    return df[["open", "high", "low", "close", "volume"]].copy()


def close_series(df: pd.DataFrame) -> pd.Series:
    """Return close price series."""
    return df["close"]


def volume_series(df: pd.DataFrame) -> pd.Series:
    """Return volume series."""
    return df["volume"]


def equity_series(
    equity_curve: list[tuple[datetime, float]],
) -> pd.Series:
    """Convert equity curve to pandas Series."""
    if not equity_curve:
        return pd.Series(dtype=float)
    timestamps, values = zip(*equity_curve)
    return pd.Series(values, index=pd.DatetimeIndex(timestamps), name="equity")


def drawdown_series(
    equity_curve: list[tuple[datetime, float]],
) -> pd.Series:
    """Compute drawdown series from equity curve."""
    dd = compute_drawdown_series(equity_curve)
    if not dd:
        return pd.Series(dtype=float)
    timestamps, values = zip(*dd)
    return pd.Series(values, index=pd.DatetimeIndex(timestamps), name="drawdown")


def fills_series(fills: list[Fill]) -> pd.DataFrame:
    """Convert fills to a DataFrame for scatter plot markers."""
    if not fills:
        return pd.DataFrame(columns=["timestamp", "price", "side", "quantity"])
    rows = []
    for f in fills:
        rows.append({
            "timestamp": f.timestamp,
            "price": f.price,
            "side": "buy" if f.side == OrderSide.BUY else "sell",
            "quantity": f.quantity,
        })
    return pd.DataFrame(rows)
