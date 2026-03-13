"""ExecutionContext ABC — interface for backtest, paper, and live execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from broker.base import Broker
from models.fill import Fill


@dataclass
class BacktestResult:
    """Result of a completed backtest."""

    portfolio_id: str
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    bars_processed: int = 0
    total_bars: int = 0


class ExecutionContext(ABC):
    """Abstract execution context for all trading modes."""

    @property
    @abstractmethod
    def mode(self) -> str:
        """Return 'backtest', 'paper', or 'live'."""
        ...

    @abstractmethod
    def get_broker(self) -> Broker:
        ...

    @abstractmethod
    def current_time(self) -> datetime:
        ...
