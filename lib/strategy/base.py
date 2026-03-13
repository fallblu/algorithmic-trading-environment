"""Strategy ABC — base class for trading strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from models.order import Order


class Strategy(ABC):
    """Base class for trading strategies.

    Strategies implement on_bar() to produce orders based on market data.
    Two usage modes:
    - Class-based: subclass Strategy and place in strategies/ directory
    - Function-based: write an on_bar() function in the editor, wrapped via FunctionStrategy
    """

    def __init__(self, params: dict | None = None) -> None:
        self.params = params or {}

    @abstractmethod
    def universe(self) -> list[str]:
        """Return the list of symbols this strategy trades."""
        ...

    @abstractmethod
    def lookback(self) -> int:
        """Number of bars of history needed for indicator computation."""
        ...

    @abstractmethod
    def on_bar(
        self,
        bars: pd.DataFrame,
        positions: dict[str, float],
    ) -> list[Order]:
        """Called on each new bar.

        Args:
            bars: DataFrame with columns [open, high, low, close, volume],
                  indexed by timestamp. Contains the last lookback() rows.
                  For multi-symbol, MultiIndex (timestamp, symbol).
            positions: Current position sizes {symbol: quantity}.
                       Positive = long, negative = short.

        Returns:
            List of orders to submit.
        """
        ...
