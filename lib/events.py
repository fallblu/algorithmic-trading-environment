"""Event bus — simple publish/subscribe for decoupled communication."""

import logging
from collections import defaultdict, deque
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
    def __init__(self, symbol: str, side: str, quantity: Decimal, price: Decimal, **kwargs):
        super().__init__(
            type=EventType.FILL,
            data={"symbol": symbol, "side": side, "quantity": str(quantity), "price": str(price), **kwargs},
        )


@dataclass
class SignalEvent(Event):
    """Emitted when a strategy generates a signal."""
    def __init__(self, symbol: str, signal: str, strength: float = 1.0, **kwargs):
        super().__init__(
            type=EventType.SIGNAL,
            data={"symbol": symbol, "signal": signal, "strength": strength, **kwargs},
        )


@dataclass
class RiskEvent(Event):
    """Emitted when a risk limit is breached or an order is rejected."""
    def __init__(self, reason: str, **kwargs):
        super().__init__(
            type=EventType.RISK,
            data={"reason": reason, **kwargs},
        )


@dataclass
class EquityUpdate(Event):
    """Emitted when equity changes."""
    def __init__(self, equity: Decimal, **kwargs):
        super().__init__(
            type=EventType.EQUITY_UPDATE,
            data={"equity": str(equity), **kwargs},
        )


# Callback type
EventCallback = type(lambda event: None)


class EventBus:
    """Simple in-process event bus with ring buffer for recent history.

    Subscribers register callbacks for specific event types.
    Events are stored in a ring buffer for recent history access.
    """

    def __init__(self, max_history: int = 1000):
        self._subscribers: dict[EventType, list] = defaultdict(list)
        self._history: deque[Event] = deque(maxlen=max_history)

    def subscribe(self, event_type: EventType, callback) -> None:
        """Register a callback for a specific event type."""
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback) -> None:
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


# Global event bus instance
event_bus = EventBus()
