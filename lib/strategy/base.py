"""Strategy ABC — base class for all trading strategies."""

from abc import ABC, abstractmethod

import pandas as pd

from execution.context import ExecutionContext
from models.fill import Fill
from models.order import Order


class Strategy(ABC):
    """Base class for trading strategies.

    Strategies implement on_bar() to produce orders based on new market data.
    The execution context handles order submission through broker and risk manager.
    """

    def __init__(self, ctx: ExecutionContext, params: dict | None = None):
        self.ctx = ctx
        self.params = params or {}

    @abstractmethod
    def on_bar(self, panel: pd.DataFrame) -> list[Order]:
        """Called on each new bar group.

        Args:
            panel: MultiIndex DataFrame with (timestamp, symbol) index and
                   columns [open, high, low, close, volume, trades, vwap].
                   Contains the last `lookback()` bars for all symbols.

        Returns:
            List of orders to submit.
        """
        ...

    @abstractmethod
    def universe(self) -> list[str]:
        """Return the list of symbols this strategy trades."""
        ...

    @abstractmethod
    def lookback(self) -> int:
        """Number of bars of history needed for indicator computation."""
        ...

    def on_fill(self, fill: Fill) -> None:
        """Called when an order is filled. Override for custom handling."""
        pass

    def on_stop(self) -> None:
        """Called when the strategy is stopped. Override for cleanup."""
        pass
