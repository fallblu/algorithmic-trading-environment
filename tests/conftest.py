"""Shared fixtures and sys.path setup for trader tests."""

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

# Add lib/ to sys.path so imports like `from broker.simulated import ...` work.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from data.store import MarketDataStore
from data.universe import Universe
from models.bar import Bar
from models.instrument import FuturesInstrument, Instrument


@pytest.fixture
def sample_instrument() -> Instrument:
    return Instrument(
        symbol="BTC/USD",
        base="BTC",
        quote="USD",
        exchange="kraken",
        asset_class="crypto",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.00001"),
        min_notional=Decimal("5"),
    )


@pytest.fixture
def futures_instrument() -> FuturesInstrument:
    return FuturesInstrument(
        symbol="BTC-PERP",
        base="BTC",
        quote="USD",
        exchange="kraken_futures",
        asset_class="crypto_futures",
        tick_size=Decimal("0.5"),
        lot_size=Decimal("0.001"),
        min_notional=Decimal("5"),
        contract_type="perpetual",
        max_leverage=Decimal("50"),
        initial_margin_rate=Decimal("0.02"),
        maintenance_margin_rate=Decimal("0.01"),
        funding_interval_hours=8,
        expiry=None,
    )


@pytest.fixture
def sample_bar() -> Bar:
    return Bar(
        instrument_symbol="BTC/USD",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        open=Decimal("42000.00"),
        high=Decimal("42500.00"),
        low=Decimal("41800.00"),
        close=Decimal("42300.00"),
        volume=Decimal("150.5"),
        trades=1200,
        vwap=Decimal("42150.00"),
    )


@pytest.fixture
def sample_universe() -> Universe:
    return Universe.from_symbols(
        symbols=["BTC/USD", "ETH/USD"],
        timeframe="1h",
        exchange="kraken",
    )


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for market data storage."""
    data_dir = tmp_path / "market_data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def market_data_store(tmp_data_dir: Path) -> MarketDataStore:
    return MarketDataStore(base_dir=tmp_data_dir)
