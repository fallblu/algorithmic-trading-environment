import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from data.price_panel import PricePanel
from data.universe import Universe
from models.bar import Bar


def _make_bar(symbol: str, ts: datetime, price: float) -> Bar:
    p = Decimal(str(price))
    return Bar(
        instrument_symbol=symbol,
        timestamp=ts,
        open=p,
        high=p + Decimal("1"),
        low=p - Decimal("1"),
        close=p,
        volume=Decimal("100"),
        trades=5,
        vwap=p,
    )


def test_append_bars_and_is_ready():
    universe = Universe.from_symbols(["BTC/USD", "ETH/USD"], timeframe="1h")
    panel = PricePanel(universe, lookback=10)

    assert panel.is_ready is False

    ts = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    panel.append_bar(_make_bar("BTC/USD", ts, 40000.0))
    # Only one symbol has data — not ready yet
    assert panel.is_ready is False

    panel.append_bar(_make_bar("ETH/USD", ts, 2000.0))
    assert panel.is_ready is True


def test_get_window_returns_correct_structure():
    universe = Universe.from_symbols(["BTC/USD"], timeframe="1h")
    panel = PricePanel(universe, lookback=10)

    for i in range(3):
        ts = datetime(2024, 1, 1, i, 0, tzinfo=timezone.utc)
        panel.append_bar(_make_bar("BTC/USD", ts, 40000.0 + i * 100))

    window = panel.get_window()
    assert not window.empty
    expected_cols = {"open", "high", "low", "close", "volume", "trades", "vwap"}
    assert expected_cols.issubset(set(window.columns))
    assert window.index.names == ["timestamp", "symbol"]
    assert len(window) == 3


def test_lookback_window_size():
    universe = Universe.from_symbols(["BTC/USD"], timeframe="1h")
    lookback = 5
    panel = PricePanel(universe, lookback=lookback)

    # Append more bars than the lookback window
    for i in range(10):
        ts = datetime(2024, 1, 1, i, 0, tzinfo=timezone.utc)
        panel.append_bar(_make_bar("BTC/USD", ts, 40000.0 + i * 100))

    window = panel.get_window()
    # Only the last `lookback` bars should be retained
    assert len(window) == lookback
