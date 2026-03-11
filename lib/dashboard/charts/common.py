"""Shared chart utilities for Plotly figure generation."""

import json
import plotly.graph_objects as go
import plotly.utils


def default_layout(title: str) -> dict:
    """Return a Plotly layout dict with dark theme and consistent styling."""
    return dict(
        title=dict(text=title, font=dict(size=18, color="#e1e1e1")),
        template="plotly_dark",
        paper_bgcolor="#1e1e2f",
        plot_bgcolor="#1e1e2f",
        font=dict(family="Inter, sans-serif", size=12, color="#a0a0b0"),
        margin=dict(l=60, r=30, t=50, b=50),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(255,255,255,0.1)",
            borderwidth=1,
        ),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.06)",
            zerolinecolor="rgba(255,255,255,0.1)",
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.06)",
            zerolinecolor="rgba(255,255,255,0.1)",
        ),
    )


def to_json(fig: go.Figure) -> str:
    """Convert a Plotly figure to JSON for embedding in HTML."""
    return json.dumps(fig.to_dict(), cls=plotly.utils.PlotlyJSONEncoder)
