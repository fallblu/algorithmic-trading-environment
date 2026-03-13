"""Broker ABC — interface for order execution and position management."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from models.fill import Fill
from models.order import Order
from models.position import Position


@dataclass
class Account:
    cash: float = 10_000.0
    equity: float = 10_000.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class Broker(ABC):
    """Abstract broker interface for order execution."""

    @abstractmethod
    def submit_order(self, order: Order) -> str:
        """Submit an order. Returns order ID."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return all open positions."""
        ...

    @abstractmethod
    def get_open_orders(self) -> list[Order]:
        """Return all pending/open orders."""
        ...

    @abstractmethod
    def get_account(self) -> Account:
        """Return current account state."""
        ...

    @abstractmethod
    def get_fills(self, since: datetime | None = None) -> list[Fill]:
        """Return fills, optionally since a given time."""
        ...
