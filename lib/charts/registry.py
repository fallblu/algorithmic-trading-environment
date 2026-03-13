"""ChartRegistry — discovers and manages available chart series."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from modules.discovery import discover_user_modules

log = logging.getLogger(__name__)


@dataclass
class ChartSeriesInfo:
    """Metadata about an available chart series."""

    key: str
    name: str
    series_type: str  # "line", "area", "bar", "scatter"
    subplot: bool = False
    description: str = ""
    source: str = "built-in"
    compute: Callable | None = None
    params: dict = field(default_factory=dict)


# Built-in series
BUILT_IN_SERIES = {
    "price.candlestick": ChartSeriesInfo(
        key="price.candlestick",
        name="Candlestick",
        series_type="candlestick",
        description="OHLC candlestick chart",
    ),
    "price.line": ChartSeriesInfo(
        key="price.line",
        name="Close Price",
        series_type="line",
        description="Close price line",
    ),
    "volume": ChartSeriesInfo(
        key="volume",
        name="Volume",
        series_type="bar",
        subplot=True,
        description="Trading volume bars",
    ),
    "equity": ChartSeriesInfo(
        key="equity",
        name="Equity Curve",
        series_type="line",
        subplot=True,
        description="Portfolio equity over time",
    ),
    "drawdown": ChartSeriesInfo(
        key="drawdown",
        name="Drawdown",
        series_type="area",
        subplot=True,
        description="Drawdown percentage from peak",
    ),
    "fills": ChartSeriesInfo(
        key="fills",
        name="Trade Fills",
        series_type="scatter",
        description="Buy/sell fill markers on price chart",
    ),
}


class ChartRegistry:
    """Registry of all available chart series (built-in + user modules)."""

    def __init__(self, lib_dir: Path | None = None) -> None:
        self._lib_dir = lib_dir or Path("lib")
        self._series: dict[str, ChartSeriesInfo] = dict(BUILT_IN_SERIES)

    def discover_all(self) -> dict[str, ChartSeriesInfo]:
        """Discover all series from built-in + user modules."""
        self._series = dict(BUILT_IN_SERIES)

        if self._lib_dir.is_dir():
            modules = discover_user_modules(self._lib_dir)
            for mod in modules:
                for key, config in mod.charts.items():
                    self._series[key] = ChartSeriesInfo(
                        key=key,
                        name=config.get("name", key),
                        series_type=config.get("type", "line"),
                        subplot=config.get("subplot", False),
                        description=config.get("description", ""),
                        source=mod.name,
                        compute=config.get("compute"),
                        params=config.get("params", {}),
                    )

        return self._series

    def get_series(self, key: str) -> ChartSeriesInfo | None:
        return self._series.get(key)

    def list_overlays(self) -> list[ChartSeriesInfo]:
        """Return series suitable for overlaying on main chart."""
        return [s for s in self._series.values() if not s.subplot]

    def list_subplots(self) -> list[ChartSeriesInfo]:
        """Return series suitable for subplots."""
        return [s for s in self._series.values() if s.subplot]
