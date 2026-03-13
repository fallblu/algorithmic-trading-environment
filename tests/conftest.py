"""Shared fixtures for the Algorithmic Trading Environment test suite."""

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure lib is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from models.bar import Bar
from models.fill import Fill
from models.instrument import Instrument
from models.order import Order, OrderSide, OrderType
from models.position import Position
from models.account import Account
from broker.simulated import SimulatedBroker
from data.universe import Universe


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

@pytest.fixture
def btc_instrument():
    return Instrument(
        symbol="BTC/USD",
        base="BTC",
        quote="USD",
        exchange="kraken",
        asset_class="crypto",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.00001"),
        min_notional=Decimal("10"),
    )


@pytest.fixture
def eth_instrument():
    return Instrument(
        symbol="ETH/USD",
        base="ETH",
        quote="USD",
        exchange="kraken",
        asset_class="crypto",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.0001"),
        min_notional=Decimal("10"),
    )


@pytest.fixture
def eur_usd_instrument():
    return Instrument(
        symbol="EUR/USD",
        base="EUR",
        quote="USD",
        exchange="oanda",
        asset_class="forex",
        tick_size=Decimal("0.00001"),
        lot_size=Decimal("1"),
        min_notional=Decimal("1"),
    )


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------

def make_bar(symbol="BTC/USD", timestamp=None, open_=50000, high=50500,
             low=49500, close=50200, volume=100):
    """Create a Bar with convenient defaults."""
    if timestamp is None:
        timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return Bar(
        instrument_symbol=symbol,
        timestamp=timestamp,
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )


def make_bar_series(symbol="BTC/USD", n=100, start_price=50000.0,
                    volatility=0.02, start_time=None):
    """Generate a series of synthetic bars with random walk prices."""
    if start_time is None:
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rng = np.random.default_rng(42)
    bars = []
    price = start_price
    for i in range(n):
        ret = rng.normal(0, volatility)
        open_ = price
        close = price * (1 + ret)
        high = max(open_, close) * (1 + abs(rng.normal(0, volatility * 0.3)))
        low = min(open_, close) * (1 - abs(rng.normal(0, volatility * 0.3)))
        vol = abs(rng.normal(100, 30))
        ts = datetime(
            start_time.year, start_time.month, start_time.day,
            tzinfo=timezone.utc,
        )
        ts = ts.replace(hour=i % 24, day=start_time.day + i // 24)
        try:
            bars.append(make_bar(
                symbol=symbol, timestamp=ts,
                open_=round(open_, 2), high=round(high, 2),
                low=round(low, 2), close=round(close, 2),
                volume=round(vol, 2),
            ))
        except ValueError:
            # Day overflow — just stop
            break
        price = close
    return bars


@pytest.fixture
def sample_bars(btc_instrument):
    return make_bar_series("BTC/USD", n=60)


@pytest.fixture
def sample_closes():
    """100 synthetic close prices with upward trend + noise."""
    rng = np.random.default_rng(42)
    prices = 50000 + np.cumsum(rng.normal(10, 500, 100))
    return prices.astype(float)


@pytest.fixture
def sample_ohlcv():
    """Synthetic OHLCV arrays (100 bars)."""
    rng = np.random.default_rng(42)
    n = 100
    closes = 50000 + np.cumsum(rng.normal(10, 500, n))
    opens = closes + rng.normal(0, 100, n)
    highs = np.maximum(opens, closes) + np.abs(rng.normal(200, 50, n))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(200, 50, n))
    volumes = np.abs(rng.normal(100, 30, n))
    return opens, highs, lows, closes, volumes


# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------

@pytest.fixture
def broker():
    return SimulatedBroker(
        initial_cash=Decimal("100000"),
        fee_rate=Decimal("0.001"),
        slippage_pct=Decimal("0"),
    )


@pytest.fixture
def margin_broker():
    return SimulatedBroker(
        initial_cash=Decimal("100000"),
        fee_rate=Decimal("0.001"),
        slippage_pct=Decimal("0"),
        margin_mode=True,
        leverage=Decimal("10"),
    )


# ---------------------------------------------------------------------------
# DataFrame helpers
# ---------------------------------------------------------------------------

def make_panel_df(symbols_data: dict[str, np.ndarray], n_bars=60):
    """Build a MultiIndex DataFrame mimicking PricePanel output.

    symbols_data: {symbol: closes_array}
    """
    rows = []
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for symbol, closes in symbols_data.items():
        for i, c in enumerate(closes[:n_bars]):
            ts = base_time.replace(hour=i % 24, day=1 + i // 24)
            try:
                rows.append({
                    "timestamp": ts,
                    "symbol": symbol,
                    "open": float(c) * 0.999,
                    "high": float(c) * 1.005,
                    "low": float(c) * 0.995,
                    "close": float(c),
                    "volume": 100.0,
                    "trades": 50,
                    "vwap": float(c),
                })
            except ValueError:
                break
    df = pd.DataFrame(rows)
    df = df.set_index(["timestamp", "symbol"])
    df = df.sort_index()
    return df
