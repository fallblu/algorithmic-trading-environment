"""Candlestick chart with buy/sell signal markers."""

from typing import List, Dict

import pandas as pd
import plotly.graph_objects as go

from .common import default_layout


def signal_chart(
    bars_df: pd.DataFrame,
    signals: List[Dict],
) -> go.Figure:
    """Build a candlestick chart overlaid with buy/sell markers.

    Parameters
    ----------
    bars_df : DataFrame with columns: open, high, low, close
              Index should be datetime or contain a 'timestamp'/'date' column.
    signals : list of dicts, each with keys:
              - timestamp : datetime matching x-axis
              - price     : price level for the marker
              - side      : "buy" or "sell"

    Returns
    -------
    go.Figure
    """
    df = bars_df.copy()

    if "timestamp" in df.columns:
        x = df["timestamp"]
    elif "date" in df.columns:
        x = df["date"]
    else:
        x = df.index

    fig = go.Figure()

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=x,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            increasing_line_color="#00d4aa",
            decreasing_line_color="#ff4b4b",
            name="Price",
        )
    )

    # Separate buy / sell signals
    buys = [s for s in signals if s.get("side") == "buy"]
    sells = [s for s in signals if s.get("side") == "sell"]

    if buys:
        fig.add_trace(
            go.Scatter(
                x=[s["timestamp"] for s in buys],
                y=[s["price"] for s in buys],
                mode="markers",
                marker=dict(
                    symbol="triangle-up",
                    size=12,
                    color="#00d4aa",
                    line=dict(color="white", width=1),
                ),
                name="Buy",
            )
        )

    if sells:
        fig.add_trace(
            go.Scatter(
                x=[s["timestamp"] for s in sells],
                y=[s["price"] for s in sells],
                mode="markers",
                marker=dict(
                    symbol="triangle-down",
                    size=12,
                    color="#ff4b4b",
                    line=dict(color="white", width=1),
                ),
                name="Sell",
            )
        )

    layout = default_layout("Price & Signals")
    layout.update(
        xaxis_rangeslider_visible=False,
        yaxis=dict(title="Price", gridcolor="rgba(255,255,255,0.06)"),
    )
    fig.update_layout(**layout)

    return fig
