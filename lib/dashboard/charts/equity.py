"""Equity curve chart with drawdown shading."""

from typing import List, Tuple
from datetime import datetime

import plotly.graph_objects as go

from .common import default_layout


def equity_chart(equity_curve: List[Tuple[datetime, float]]) -> go.Figure:
    """Build a line chart of equity with drawdown shading.

    Parameters
    ----------
    equity_curve : list of (timestamp, equity) tuples

    Returns
    -------
    go.Figure
    """
    timestamps = [t for t, _ in equity_curve]
    equities = [e for _, e in equity_curve]

    # Compute running max and drawdown
    running_max = []
    peak = equities[0]
    for e in equities:
        peak = max(peak, e)
        running_max.append(peak)

    drawdowns = [e - rm for e, rm in zip(equities, running_max)]

    fig = go.Figure()

    # Drawdown fill (plotted on secondary y-axis)
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=drawdowns,
            fill="tozeroy",
            fillcolor="rgba(255, 75, 75, 0.15)",
            line=dict(color="rgba(255, 75, 75, 0.4)", width=1),
            name="Drawdown",
            yaxis="y2",
        )
    )

    # Equity line
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=equities,
            line=dict(color="#00d4aa", width=2),
            name="Equity",
        )
    )

    layout = default_layout("Equity Curve")
    layout.update(
        yaxis2=dict(
            title="Drawdown",
            overlaying="y",
            side="right",
            gridcolor="rgba(255,255,255,0.04)",
            zerolinecolor="rgba(255,255,255,0.1)",
        ),
        yaxis=dict(
            title="Equity",
            gridcolor="rgba(255,255,255,0.06)",
            zerolinecolor="rgba(255,255,255,0.1)",
        ),
    )
    fig.update_layout(**layout)

    return fig
