"""ChartBuilder — compose Plotly figures from chart configuration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from charts.registry import ChartRegistry, ChartSeriesInfo
from charts.series import (
    close_series,
    drawdown_series,
    equity_series,
    fills_series,
    price_series,
    volume_series,
)
from models.fill import Fill

log = logging.getLogger(__name__)


@dataclass
class ChartConfig:
    """Configuration for building a chart."""

    symbol: str = "BTC/USD"
    timeframe: str = "1h"
    date_range: tuple[datetime, datetime] | None = None
    main_chart: str = "candlestick"
    overlays: list[str] = field(default_factory=list)
    subplots: list[str] = field(default_factory=list)
    name: str | None = None
    portfolio_id: str | None = None


class ChartBuilder:
    """Builds Plotly figures from chart configuration."""

    def __init__(self, registry: ChartRegistry) -> None:
        self._registry = registry

    def build(
        self,
        config: ChartConfig,
        df: pd.DataFrame,
        equity_curve: list[tuple[datetime, float]] | None = None,
        fills: list[Fill] | None = None,
    ) -> str:
        """Build a Plotly chart and return HTML div string."""
        n_subplots = len(config.subplots) + 1
        row_heights = [0.6] + [0.4 / max(len(config.subplots), 1)] * len(config.subplots)

        fig = make_subplots(
            rows=n_subplots,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=row_heights[:n_subplots],
        )

        # Main chart
        if config.main_chart == "candlestick":
            fig.add_trace(
                go.Candlestick(
                    x=df.index,
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                    name="Price",
                ),
                row=1, col=1,
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=df.index, y=df["close"], mode="lines", name="Close"
                ),
                row=1, col=1,
            )

        # Overlays on main chart
        for overlay_key in config.overlays:
            self._add_overlay(fig, overlay_key, df, equity_curve, fills)

        # Subplots
        for i, subplot_key in enumerate(config.subplots, start=2):
            self._add_subplot(fig, subplot_key, df, equity_curve, fills, row=i)

        # Styling
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#1a1a2e",
            plot_bgcolor="#16213e",
            xaxis_rangeslider_visible=False,
            height=400 + 200 * len(config.subplots),
            margin=dict(l=50, r=20, t=30, b=30),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )

        return fig.to_html(full_html=False, include_plotlyjs="cdn")

    def _add_overlay(
        self,
        fig: go.Figure,
        key: str,
        df: pd.DataFrame,
        equity_curve: list | None,
        fills: list | None,
    ) -> None:
        """Add an overlay series to the main chart."""
        if key == "fills" and fills:
            fills_df = fills_series(fills)
            buys = fills_df[fills_df["side"] == "buy"]
            sells = fills_df[fills_df["side"] == "sell"]
            if not buys.empty:
                fig.add_trace(go.Scatter(
                    x=buys["timestamp"], y=buys["price"],
                    mode="markers", name="Buy",
                    marker=dict(symbol="triangle-up", size=10, color="#00ff88"),
                ), row=1, col=1)
            if not sells.empty:
                fig.add_trace(go.Scatter(
                    x=sells["timestamp"], y=sells["price"],
                    mode="markers", name="Sell",
                    marker=dict(symbol="triangle-down", size=10, color="#ff4444"),
                ), row=1, col=1)
            return

        # Custom module series
        series_info = self._registry.get_series(key)
        if series_info and series_info.compute:
            try:
                result = series_info.compute(df, **series_info.params)
                fig.add_trace(go.Scatter(
                    x=result.index, y=result, mode="lines", name=series_info.name,
                ), row=1, col=1)
            except Exception as e:
                log.warning("Failed to compute overlay %s: %s", key, e)

    def _add_subplot(
        self,
        fig: go.Figure,
        key: str,
        df: pd.DataFrame,
        equity_curve: list | None,
        fills: list | None,
        row: int = 2,
    ) -> None:
        """Add a subplot series."""
        if key == "volume":
            colors = [
                "#00ff88" if c >= o else "#ff4444"
                for o, c in zip(df["open"], df["close"])
            ]
            fig.add_trace(go.Bar(
                x=df.index, y=df["volume"], name="Volume",
                marker_color=colors, opacity=0.7,
            ), row=row, col=1)
            return

        if key == "equity" and equity_curve:
            eq = equity_series(equity_curve)
            fig.add_trace(go.Scatter(
                x=eq.index, y=eq, mode="lines", name="Equity",
                line=dict(color="#00ff88"),
            ), row=row, col=1)
            return

        if key == "drawdown" and equity_curve:
            dd = drawdown_series(equity_curve)
            fig.add_trace(go.Scatter(
                x=dd.index, y=dd, mode="lines", name="Drawdown",
                fill="tozeroy", line=dict(color="#ff4444"),
            ), row=row, col=1)
            return

        # Custom module series
        series_info = self._registry.get_series(key)
        if series_info and series_info.compute:
            try:
                result = series_info.compute(df, **series_info.params)
                fig.add_trace(go.Scatter(
                    x=result.index, y=result, mode="lines", name=series_info.name,
                ), row=row, col=1)
            except Exception as e:
                log.warning("Failed to compute subplot %s: %s", key, e)
