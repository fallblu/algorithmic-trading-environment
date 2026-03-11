"""Candlestick chart with volume subplot."""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .common import default_layout


def candlestick_chart(bars_df: pd.DataFrame) -> go.Figure:
    """Build a candlestick chart with a volume bars subplot.

    Parameters
    ----------
    bars_df : DataFrame with columns: open, high, low, close, volume
              Index should be datetime or a 'timestamp'/'date' column.

    Returns
    -------
    go.Figure
    """
    df = bars_df.copy()

    # Normalise index to a datetime series for the x-axis
    if "timestamp" in df.columns:
        x = df["timestamp"]
    elif "date" in df.columns:
        x = df["date"]
    else:
        x = df.index

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )

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
        ),
        row=1,
        col=1,
    )

    # Volume bars coloured by direction
    colors = [
        "#00d4aa" if c >= o else "#ff4b4b"
        for c, o in zip(df["close"], df["open"])
    ]

    fig.add_trace(
        go.Bar(
            x=x,
            y=df["volume"],
            marker_color=colors,
            opacity=0.5,
            name="Volume",
        ),
        row=2,
        col=1,
    )

    layout = default_layout("Candlestick")
    layout.update(
        xaxis_rangeslider_visible=False,
        showlegend=False,
    )
    fig.update_layout(**layout)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    return fig
