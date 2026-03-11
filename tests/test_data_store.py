import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from data.store import MarketDataStore
from models.bar import Bar


def _make_bar(symbol: str, ts: datetime, price: float, volume: float = 100.0) -> Bar:
    p = Decimal(str(price))
    return Bar(
        instrument_symbol=symbol,
        timestamp=ts,
        open=p,
        high=p + Decimal("1"),
        low=p - Decimal("1"),
        close=p,
        volume=Decimal(str(volume)),
        trades=10,
        vwap=p,
    )


def test_write_and_read_bars_roundtrip(tmp_path):
    store = MarketDataStore(tmp_path)
    ts1 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)
    bars = [
        _make_bar("BTC/USD", ts1, 40000.0),
        _make_bar("BTC/USD", ts2, 40100.0),
    ]
    store.write_bars(bars, exchange="kraken", timeframe="1h")
    result = store.read_bars("kraken", "BTC/USD", "1h")

    assert len(result) == 2
    assert result[0].instrument_symbol == "BTC/USD"
    assert result[0].close == Decimal("40000")
    assert result[1].close == Decimal("40100")
    assert result[0].timestamp < result[1].timestamp


def test_get_date_range(tmp_path):
    store = MarketDataStore(tmp_path)
    ts1 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc)
    bars = [
        _make_bar("ETH/USD", ts1, 2000.0),
        _make_bar("ETH/USD", ts2, 2100.0),
    ]
    store.write_bars(bars, exchange="kraken", timeframe="1h")
    date_range = store.get_date_range("kraken", "ETH/USD", "1h")

    assert date_range is not None
    start, end = date_range
    assert start == ts1
    assert end == ts2


def test_read_bars_empty_store(tmp_path):
    store = MarketDataStore(tmp_path)
    result = store.read_bars("kraken", "BTC/USD", "1h")
    assert result == []


def test_append_bars(tmp_path):
    store = MarketDataStore(tmp_path)
    ts1 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)
    ts3 = datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc)

    store.write_bars([_make_bar("BTC/USD", ts1, 40000.0)], exchange="kraken", timeframe="1h")
    store.write_bars(
        [_make_bar("BTC/USD", ts2, 40100.0), _make_bar("BTC/USD", ts3, 40200.0)],
        exchange="kraken",
        timeframe="1h",
    )
    result = store.read_bars("kraken", "BTC/USD", "1h")

    assert len(result) == 3
    assert result[0].close == Decimal("40000")
    assert result[1].close == Decimal("40100")
    assert result[2].close == Decimal("40200")
