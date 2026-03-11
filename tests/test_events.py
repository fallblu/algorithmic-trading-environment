from decimal import Decimal

from events import (
    EquityUpdate,
    Event,
    EventBus,
    EventType,
    FillEvent,
    RiskEvent,
    SignalEvent,
    event_bus,
)


# ---------------------------------------------------------------------------
# EventBus subscribe / publish
# ---------------------------------------------------------------------------

class TestEventBusSubscribePublish:
    def test_subscribe_and_receive(self):
        bus = EventBus()
        received = []
        bus.subscribe(EventType.FILL, lambda e: received.append(e))

        event = FillEvent(symbol="BTC/USD", side="BUY", quantity=Decimal("1"), price=Decimal("42000"))
        bus.publish(event)

        assert len(received) == 1
        assert received[0] is event
        assert received[0].type == EventType.FILL
        assert received[0].data["symbol"] == "BTC/USD"

    def test_publish_without_subscribers(self):
        bus = EventBus()
        # Should not raise
        event = SignalEvent(symbol="ETH/USD", signal="long", strength=0.9)
        bus.publish(event)
        # Event still stored in history
        assert len(bus.get_history()) == 1

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        callback = lambda e: received.append(e)
        bus.subscribe(EventType.RISK, callback)

        bus.publish(RiskEvent(reason="max drawdown exceeded"))
        assert len(received) == 1

        bus.unsubscribe(EventType.RISK, callback)
        bus.publish(RiskEvent(reason="position limit exceeded"))
        assert len(received) == 1  # no new events received

    def test_callback_exception_does_not_stop_others(self):
        bus = EventBus()
        results = []

        def bad_callback(e):
            raise ValueError("boom")

        def good_callback(e):
            results.append(e.data["symbol"])

        bus.subscribe(EventType.FILL, bad_callback)
        bus.subscribe(EventType.FILL, good_callback)

        event = FillEvent(symbol="SOL/USD", side="SELL", quantity=Decimal("10"), price=Decimal("100"))
        bus.publish(event)

        # good_callback should still have been called
        assert results == ["SOL/USD"]


# ---------------------------------------------------------------------------
# Ring buffer size limit
# ---------------------------------------------------------------------------

class TestRingBuffer:
    def test_max_history_limit(self):
        bus = EventBus(max_history=5)
        for i in range(10):
            bus.publish(SignalEvent(symbol=f"SYM{i}", signal="long"))

        history = bus.get_history()
        assert len(history) == 5
        # Newest first — most recent symbol should be SYM9
        assert history[0].data["symbol"] == "SYM9"
        # Oldest kept should be SYM5
        assert history[4].data["symbol"] == "SYM5"

    def test_default_max_history(self):
        bus = EventBus()
        # Default is 1000; just verify it stores events
        for i in range(50):
            bus.publish(Event(type=EventType.EQUITY_UPDATE, data={"i": i}))
        assert len(bus.get_history()) == 50


# ---------------------------------------------------------------------------
# get_history filtering
# ---------------------------------------------------------------------------

class TestGetHistory:
    def test_filter_by_event_type(self):
        bus = EventBus()
        bus.publish(FillEvent(symbol="BTC/USD", side="BUY", quantity=Decimal("1"), price=Decimal("40000")))
        bus.publish(SignalEvent(symbol="ETH/USD", signal="short"))
        bus.publish(FillEvent(symbol="SOL/USD", side="SELL", quantity=Decimal("5"), price=Decimal("100")))
        bus.publish(RiskEvent(reason="test"))

        fills = bus.get_history(event_type=EventType.FILL)
        assert len(fills) == 2
        assert all(e.type == EventType.FILL for e in fills)

        signals = bus.get_history(event_type=EventType.SIGNAL)
        assert len(signals) == 1
        assert signals[0].data["symbol"] == "ETH/USD"

    def test_filter_returns_newest_first(self):
        bus = EventBus()
        bus.publish(FillEvent(symbol="FIRST", side="BUY", quantity=Decimal("1"), price=Decimal("1")))
        bus.publish(FillEvent(symbol="SECOND", side="BUY", quantity=Decimal("1"), price=Decimal("2")))

        fills = bus.get_history(event_type=EventType.FILL)
        assert fills[0].data["symbol"] == "SECOND"
        assert fills[1].data["symbol"] == "FIRST"

    def test_limit(self):
        bus = EventBus()
        for i in range(10):
            bus.publish(SignalEvent(symbol=f"SYM{i}", signal="long"))

        limited = bus.get_history(limit=3)
        assert len(limited) == 3
        # Should be the 3 newest
        assert limited[0].data["symbol"] == "SYM9"
        assert limited[1].data["symbol"] == "SYM8"
        assert limited[2].data["symbol"] == "SYM7"

    def test_filter_and_limit_combined(self):
        bus = EventBus()
        bus.publish(FillEvent(symbol="F1", side="BUY", quantity=Decimal("1"), price=Decimal("1")))
        bus.publish(SignalEvent(symbol="S1", signal="long"))
        bus.publish(FillEvent(symbol="F2", side="SELL", quantity=Decimal("2"), price=Decimal("2")))
        bus.publish(FillEvent(symbol="F3", side="BUY", quantity=Decimal("3"), price=Decimal("3")))

        result = bus.get_history(event_type=EventType.FILL, limit=2)
        assert len(result) == 2
        assert result[0].data["symbol"] == "F3"
        assert result[1].data["symbol"] == "F2"

    def test_no_events_returns_empty(self):
        bus = EventBus()
        assert bus.get_history() == []
        assert bus.get_history(event_type=EventType.RISK) == []


# ---------------------------------------------------------------------------
# Multiple subscribers
# ---------------------------------------------------------------------------

class TestMultipleSubscribers:
    def test_multiple_subscribers_same_event_type(self):
        bus = EventBus()
        results_a = []
        results_b = []
        results_c = []

        bus.subscribe(EventType.SIGNAL, lambda e: results_a.append(e.data["symbol"]))
        bus.subscribe(EventType.SIGNAL, lambda e: results_b.append(e.data["signal"]))
        bus.subscribe(EventType.SIGNAL, lambda e: results_c.append(e.data["strength"]))

        bus.publish(SignalEvent(symbol="BTC/USD", signal="long", strength=0.75))

        assert results_a == ["BTC/USD"]
        assert results_b == ["long"]
        assert results_c == [0.75]

    def test_subscribers_for_different_event_types(self):
        bus = EventBus()
        fill_results = []
        signal_results = []

        bus.subscribe(EventType.FILL, lambda e: fill_results.append(e))
        bus.subscribe(EventType.SIGNAL, lambda e: signal_results.append(e))

        bus.publish(FillEvent(symbol="BTC/USD", side="BUY", quantity=Decimal("1"), price=Decimal("42000")))
        bus.publish(SignalEvent(symbol="ETH/USD", signal="short"))

        assert len(fill_results) == 1
        assert len(signal_results) == 1
        assert fill_results[0].type == EventType.FILL
        assert signal_results[0].type == EventType.SIGNAL


# ---------------------------------------------------------------------------
# Global event_bus instance
# ---------------------------------------------------------------------------

class TestGlobalEventBus:
    def test_global_instance_exists(self):
        assert isinstance(event_bus, EventBus)

    def test_global_instance_is_functional(self):
        # Clear to avoid pollution from other tests
        event_bus.clear()
        received = []
        event_bus.subscribe(EventType.EQUITY_UPDATE, lambda e: received.append(e))

        event_bus.publish(EquityUpdate(equity=Decimal("50000")))
        assert len(received) == 1
        assert received[0].data["equity"] == "50000"

        # Clean up
        event_bus.clear()

    def test_clear_resets_history_and_subscribers(self):
        bus = EventBus()
        bus.subscribe(EventType.FILL, lambda e: None)
        bus.publish(FillEvent(symbol="X", side="BUY", quantity=Decimal("1"), price=Decimal("1")))

        assert len(bus.get_history()) == 1
        bus.clear()
        assert len(bus.get_history()) == 0
        # After clear, subscribers dict is also cleared
        assert len(bus._subscribers) == 0
