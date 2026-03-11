"""ExecutionContext ABC — the central abstraction for mode-agnostic strategy execution."""

from abc import ABC, abstractmethod
from datetime import datetime

from broker.base import Broker
from data.universe import Universe
from risk.manager import RiskManager


class ExecutionContext(ABC):
    """Base class for all execution contexts (backtest, paper, live).

    Strategies interact with this interface only — never directly with
    broker, feed, or risk manager implementations.
    """

    mode: str  # "backtest" | "paper" | "live"

    @abstractmethod
    def get_universe(self) -> Universe:
        """Get the universe of instruments being traded."""
        ...

    @abstractmethod
    def get_broker(self) -> Broker:
        """Get the broker for order execution."""
        ...

    @abstractmethod
    def get_risk_manager(self) -> RiskManager:
        """Get the risk manager for pre-trade checks."""
        ...

    @abstractmethod
    def current_time(self) -> datetime:
        """Current time — simulated in backtest, real in paper/live."""
        ...
