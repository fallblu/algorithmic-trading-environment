"""Tests for EventBus pub/sub system."""

from decimal import Decimal

import pytest

from events import (
    EventBus, EventType, Event, FillEvent, SignalEvent, RiskEvent,
    EquityUpdate, get_event_bus, set_event_bus,
)


class TestEventBus:
    def test_subscribe_and_publish(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.FILL, handler)
        event = Event(type=EventType.FILL)
        bus.publish(event)

        assert len(received) == 1
        assert received[0] is event

    def test_unsubscribe(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.FILL, handler)
        bus.unsubscribe(EventType.FILL, handler)
        bus.publish(Event(type=EventType.FILL))

        assert len(received) == 0

    def test_multiple_subscribers(self):
        bus = EventBus()
        results = {"a": 0, "b": 0}

        def handler_a(event):
            results["a"] += 1

        def handler_b(event):
            results["b"] += 1

        bus.subscribe(EventType.FILL, handler_a)
        bus.subscribe(EventType.FILL, handler_b)
        bus.publish(Event(type=EventType.FILL))

        assert results["a"] == 1
        assert results["b"] == 1

    def test_different_event_types_isolated(self):
        bus = EventBus()
        fill_count = [0]
        risk_count = [0]

        bus.subscribe(EventType.FILL, lambda e: fill_count.__setitem__(0, fill_count[0] + 1))
        bus.subscribe(EventType.RISK, lambda e: risk_count.__setitem__(0, risk_count[0] + 1))

        bus.publish(Event(type=EventType.FILL))
        bus.publish(Event(type=EventType.FILL))
        bus.publish(Event(type=EventType.RISK))

        assert fill_count[0] == 2
        assert risk_count[0] == 1


class TestEventHistory:
    def test_history_recorded(self):
        bus = EventBus(max_history=100)
        bus.publish(Event(type=EventType.FILL))
        bus.publish(Event(type=EventType.RISK))

        history = bus.get_history()
        assert len(history) == 2

    def test_history_filtered_by_type(self):
        bus = EventBus()
        bus.publish(Event(type=EventType.FILL))
        bus.publish(Event(type=EventType.RISK))
        bus.publish(Event(type=EventType.FILL))

        fill_history = bus.get_history(EventType.FILL)
        assert len(fill_history) == 2

    def test_history_limit(self):
        bus = EventBus()
        for _ in range(10):
            bus.publish(Event(type=EventType.FILL))

        limited = bus.get_history(limit=3)
        assert len(limited) == 3

    def test_clear(self):
        bus = EventBus()
        bus.publish(Event(type=EventType.FILL))
        bus.clear()
        assert len(bus.get_history()) == 0


class TestTypedEvents:
    def test_fill_event(self):
        event = FillEvent(
            symbol="BTC/USD",
            side="BUY",
            quantity=Decimal("0.1"),
            price=Decimal("50000"),
        )
        assert event.type == EventType.FILL
        assert event.symbol == "BTC/USD"
        assert event.quantity == Decimal("0.1")

    def test_signal_event(self):
        event = SignalEvent(
            symbol="BTC/USD",
            signal="buy",
            strength=0.8,
        )
        assert event.type == EventType.SIGNAL
        assert event.signal == "buy"
        assert event.strength == 0.8

    def test_risk_event(self):
        event = RiskEvent(reason="Position limit exceeded")
        assert event.type == EventType.RISK
        assert event.reason == "Position limit exceeded"

    def test_equity_update(self):
        event = EquityUpdate(equity=Decimal("105000"))
        assert event.type == EventType.EQUITY_UPDATE
        assert event.equity == Decimal("105000")


class TestEventBusGlobal:
    def test_get_set_event_bus(self):
        original = get_event_bus()
        new_bus = EventBus()
        set_event_bus(new_bus)
        assert get_event_bus() is new_bus
        set_event_bus(original)  # restore


class TestErrorIsolation:
    def test_error_in_subscriber_doesnt_break_others(self):
        bus = EventBus()
        results = []

        def bad_handler(event):
            raise ValueError("oops")

        def good_handler(event):
            results.append("ok")

        bus.subscribe(EventType.FILL, bad_handler)
        bus.subscribe(EventType.FILL, good_handler)

        # Should not raise
        bus.publish(Event(type=EventType.FILL))
        assert "ok" in results
