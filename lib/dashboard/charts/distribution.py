"""Return distribution histogram with normal overlay."""

import numpy as np
import plotly.graph_objects as go

from .common import default_layout


def distribution_chart(
    returns: np.ndarray,
    title: str = "Return Distribution",
) -> go.Figure:
    """Build a histogram of returns with a fitted normal curve overlay.

    Parameters
    ----------
    returns : array-like of return values
    title   : chart title

    Returns
    -------
    go.Figure
    """
    returns = np.asarray(returns, dtype=float)
    mu = float(np.mean(returns))
    sigma = float(np.std(returns))

    fig = go.Figure()

    # Histogram
    fig.add_trace(
        go.Histogram(
            x=returns,
            nbinsx=50,
            histnorm="probability density",
            marker_color="rgba(0, 212, 170, 0.6)",
            marker_line=dict(color="#00d4aa", width=1),
            name="Returns",
        )
    )

    # Normal overlay
    if sigma > 0:
        x_range = np.linspace(mu - 4 * sigma, mu + 4 * sigma, 200)
        pdf = (
            1.0
            / (sigma * np.sqrt(2.0 * np.pi))
            * np.exp(-0.5 * ((x_range - mu) / sigma) ** 2)
        )
        fig.add_trace(
            go.Scatter(
                x=x_range,
                y=pdf,
                mode="lines",
                line=dict(color="#ff9f1c", width=2),
                name=f"Normal (mu={mu:.4f}, sigma={sigma:.4f})",
            )
        )

    layout = default_layout(title)
    layout.update(
        xaxis=dict(title="Return", gridcolor="rgba(255,255,255,0.06)"),
        yaxis=dict(title="Density", gridcolor="rgba(255,255,255,0.06)"),
        bargap=0.02,
    )
    fig.update_layout(**layout)

    return fig
