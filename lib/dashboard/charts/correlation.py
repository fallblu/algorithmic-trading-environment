"""Annotated correlation heatmap chart."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .common import default_layout


def correlation_chart(corr_matrix: pd.DataFrame) -> go.Figure:
    """Build an annotated heatmap from a correlation matrix.

    Parameters
    ----------
    corr_matrix : square DataFrame of correlation coefficients

    Returns
    -------
    go.Figure
    """
    labels = [str(c) for c in corr_matrix.columns]
    z = corr_matrix.values

    # Build annotation text
    annotations = []
    for i, row in enumerate(z):
        for j, val in enumerate(row):
            annotations.append(
                dict(
                    x=labels[j],
                    y=labels[i],
                    text=f"{val:.2f}",
                    font=dict(
                        color="white" if abs(val) > 0.5 else "#a0a0b0",
                        size=11,
                    ),
                    showarrow=False,
                )
            )

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=labels,
            y=labels,
            zmin=-1,
            zmax=1,
            colorscale="RdBu_r",
            colorbar=dict(title="Corr"),
        )
    )

    layout = default_layout("Correlation Matrix")
    layout.update(
        annotations=annotations,
        yaxis=dict(autorange="reversed", gridcolor="rgba(255,255,255,0.06)"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
    )
    fig.update_layout(**layout)

    return fig
