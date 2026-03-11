"""Strategy ABC — base class for all trading strategies."""

from abc import ABC, abstractmethod

from execution.context import ExecutionContext
from models.bar import Bar
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
    def on_bar(self, bar: Bar) -> list[Order]:
        """Called on each new bar. Return a list of orders to submit."""
        ...

    def on_fill(self, fill: Fill) -> None:
        """Called when an order is filled. Override for custom handling."""
        pass

    def on_stop(self) -> None:
        """Called when the strategy is stopped. Override for cleanup."""
        pass
