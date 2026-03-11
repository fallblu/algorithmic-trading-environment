"""Monte Carlo fan chart with confidence bands."""

from typing import Dict, List

import numpy as np
import plotly.graph_objects as go

from .common import default_layout


def fan_chart(
    paths: np.ndarray,
    confidence_intervals: Dict[str, float],
) -> go.Figure:
    """Build a fan chart showing simulation paths with percentile bands.

    Parameters
    ----------
    paths : 2-D array of shape (num_paths, num_steps) with simulated equity values
    confidence_intervals : dict mapping label to percentile width, e.g.
        {"50%": 50, "90%": 90, "99%": 99}

    Returns
    -------
    go.Figure
    """
    paths = np.asarray(paths, dtype=float)
    num_steps = paths.shape[1]
    x = list(range(num_steps))

    median = np.median(paths, axis=0)

    # Colour palette for bands (inner to outer)
    band_colors = [
        "rgba(0, 212, 170, 0.35)",
        "rgba(0, 212, 170, 0.20)",
        "rgba(0, 212, 170, 0.10)",
    ]

    fig = go.Figure()

    # Sort intervals narrowest-first so narrower bands draw on top
    sorted_ci = sorted(confidence_intervals.items(), key=lambda kv: kv[1])

    for idx, (label, pct) in enumerate(reversed(sorted_ci)):
        lower_p = (100 - pct) / 2
        upper_p = 100 - lower_p
        lower = np.percentile(paths, lower_p, axis=0)
        upper = np.percentile(paths, upper_p, axis=0)

        color = band_colors[idx % len(band_colors)]

        # Upper bound (invisible line)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=upper.tolist(),
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        # Lower bound with fill to previous trace
        fig.add_trace(
            go.Scatter(
                x=x,
                y=lower.tolist(),
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor=color,
                name=f"{label} CI",
            )
        )

    # Median line
    fig.add_trace(
        go.Scatter(
            x=x,
            y=median.tolist(),
            mode="lines",
            line=dict(color="#00d4aa", width=2),
            name="Median",
        )
    )

    layout = default_layout("Monte Carlo Simulation")
    layout.update(
        xaxis=dict(title="Step", gridcolor="rgba(255,255,255,0.06)"),
        yaxis=dict(title="Equity", gridcolor="rgba(255,255,255,0.06)"),
    )
    fig.update_layout(**layout)

    return fig
