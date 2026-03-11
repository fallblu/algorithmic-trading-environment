"""Event bus — simple publish/subscribe for decoupled communication."""

import logging
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

log = logging.getLogger(__name__)


class EventType(Enum):
    FILL = "fill"
    SIGNAL = "signal"
    RISK = "risk"
    EQUITY_UPDATE = "equity_update"


@dataclass
class Event:
    """Base event with type, timestamp, and payload."""
    type: EventType
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict = field(default_factory=dict)


@dataclass
class FillEvent(Event):
    """Emitted when an order is filled."""
    symbol: str = ""
    side: str = ""
    quantity: Decimal = Decimal("0")
    price: Decimal = Decimal("0")

    def __init__(self, symbol: str, side: str, quantity: Decimal, price: Decimal, **kwargs):
        super().__init__(
            type=EventType.FILL,
            data={"symbol": symbol, "side": side, "quantity": str(quantity), "price": str(price), **kwargs},
        )
        self.symbol = symbol
        self.side = side
        self.quantity = quantity
        self.price = price


@dataclass
class SignalEvent(Event):
    """Emitted when a strategy generates a signal."""
    symbol: str = ""
    signal: str = ""
    strength: float = 1.0

    def __init__(self, symbol: str, signal: str, strength: float = 1.0, **kwargs):
        super().__init__(
            type=EventType.SIGNAL,
            data={"symbol": symbol, "signal": signal, "strength": strength, **kwargs},
        )
        self.symbol = symbol
        self.signal = signal
        self.strength = strength


@dataclass
class RiskEvent(Event):
    """Emitted when a risk limit is breached or an order is rejected."""
    reason: str = ""

    def __init__(self, reason: str, **kwargs):
        super().__init__(
            type=EventType.RISK,
            data={"reason": reason, **kwargs},
        )
        self.reason = reason


@dataclass
class EquityUpdate(Event):
    """Emitted when equity changes."""
    equity: Decimal = Decimal("0")

    def __init__(self, equity: Decimal, **kwargs):
        super().__init__(
            type=EventType.EQUITY_UPDATE,
            data={"equity": str(equity), **kwargs},
        )
        self.equity = equity


EventCallback = Callable[[Event], None]


class EventBus:
    """Simple in-process event bus with ring buffer for recent history.

    Subscribers register callbacks for specific event types.
    Events are stored in a ring buffer for recent history access.
    """

    def __init__(self, max_history: int = 1000):
        self._subscribers: dict[EventType, list[EventCallback]] = defaultdict(list)
        self._history: deque[Event] = deque(maxlen=max_history)

    def subscribe(self, event_type: EventType, callback: EventCallback) -> None:
        """Register a callback for a specific event type."""
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback: EventCallback) -> None:
        """Remove a callback."""
        subs = self._subscribers.get(event_type, [])
        if callback in subs:
            subs.remove(callback)

    def publish(self, event: Event) -> None:
        """Publish an event to all subscribers and store in history."""
        self._history.append(event)

        for callback in self._subscribers.get(event.type, []):
            try:
                callback(event)
            except Exception:
                log.exception("Error in event callback for %s", event.type)

    def get_history(
        self,
        event_type: EventType | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        """Get recent events from the ring buffer.

        Args:
            event_type: Filter by type (None = all).
            limit: Max number of events to return.

        Returns:
            Events sorted newest-first.
        """
        events = list(self._history)

        if event_type is not None:
            events = [e for e in events if e.type == event_type]

        events.reverse()

        if limit is not None:
            events = events[:limit]

        return events

    def clear(self) -> None:
        """Clear all history and subscribers."""
        self._history.clear()
        self._subscribers.clear()


# Default event bus instance
_default_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance (created on first call)."""
    global _default_event_bus
    if _default_event_bus is None:
        _default_event_bus = EventBus()
    return _default_event_bus


def set_event_bus(bus: EventBus) -> None:
    """Replace the global event bus (useful for testing)."""
    global _default_event_bus
    _default_event_bus = bus


# Backwards-compatible module-level reference
event_bus = get_event_bus()
