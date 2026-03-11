"""Generic heatmap chart."""

import pandas as pd
import plotly.graph_objects as go

from .common import default_layout


def heatmap_chart(
    pivot_df: pd.DataFrame,
    title: str = "Heatmap",
    x_label: str = "",
    y_label: str = "",
) -> go.Figure:
    """Build a heatmap from a pivot DataFrame.

    Parameters
    ----------
    pivot_df : DataFrame where index = y-axis, columns = x-axis, values = z
    title    : chart title
    x_label  : x-axis label
    y_label  : y-axis label

    Returns
    -------
    go.Figure
    """
    fig = go.Figure(
        go.Heatmap(
            z=pivot_df.values,
            x=[str(c) for c in pivot_df.columns],
            y=[str(i) for i in pivot_df.index],
            colorscale="Viridis",
            colorbar=dict(title="Value"),
        )
    )

    layout = default_layout(title)
    layout.update(
        xaxis=dict(title=x_label, gridcolor="rgba(255,255,255,0.06)"),
        yaxis=dict(title=y_label, gridcolor="rgba(255,255,255,0.06)", autorange="reversed"),
    )
    fig.update_layout(**layout)

    return fig
