from abc import ABC, abstractmethod

from models.account import Account
from models.instrument import Instrument
from models.order import Order
from models.position import Position


class Broker(ABC):
    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        """Submit an order for execution. Returns the order with updated status."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> Order:
        """Cancel an open order. Returns the order with updated status."""
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Order:
        """Get an order by ID."""
        ...

    @abstractmethod
    def get_open_orders(self, instrument: Instrument | None = None) -> list[Order]:
        """Get all open orders, optionally filtered by instrument."""
        ...

    @abstractmethod
    def get_position(self, instrument: Instrument) -> Position | None:
        """Get the current position for an instrument, or None if flat."""
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Get all open positions."""
        ...

    @abstractmethod
    def get_account(self) -> Account:
        """Get the current account state."""
        ...
