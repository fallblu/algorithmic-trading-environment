# Testing

This guide covers running the test suite, understanding its structure, using available fixtures, and writing new tests.

## Running Tests

### Basic Usage

Run the full test suite from the project root:

```bash
pytest
```

Run with verbose output:

```bash
pytest -v
```

### Coverage

Generate a coverage report for the `lib/` package:

```bash
pytest --cov=lib
```

For an HTML coverage report:

```bash
pytest --cov=lib --cov-report=html
```

### Running Specific Tests

Run a single test file:

```bash
pytest tests/test_indicators.py
```

Run a single test function:

```bash
pytest tests/test_indicators.py::test_sma_basic
```

Run tests matching a keyword expression:

```bash
pytest -k "backtest"
```

## Test Structure

Tests are located in the `tests/` directory:

```
tests/
    conftest.py              # Shared fixtures and sys.path setup
    test_backtest.py         # Backtest execution tests
    test_batch.py            # Batch backtesting tests
    test_batch_results.py    # BatchResults API tests
    test_config.py           # Configuration tests
    test_data_store.py       # MarketDataStore tests
    test_exchange.py         # Exchange abstraction tests
    test_indicators.py       # Technical indicator tests
    test_models.py           # Data model tests
    test_monte_carlo.py      # Monte Carlo simulation tests
    test_performance.py      # Performance metric tests
    test_price_panel.py      # PricePanel DataFrame tests
    test_result_store.py     # ResultStore tests
    test_risk_manager.py     # Risk manager tests
    test_simulated_broker.py # Simulated broker tests
    test_strategy.py         # Strategy ABC tests
    test_tick_store.py       # Tick data storage tests
    test_universe.py         # Universe/symbol tests
```

The `conftest.py` module adds `lib/` to `sys.path` so that imports like `from broker.simulated import ...` work without installing the package.

## Available Fixtures

The following fixtures are defined in `tests/conftest.py` and available to all tests:

### `sample_instrument`

A standard `Instrument` instance for BTC/USD on Kraken:

```python
def test_something(sample_instrument):
    assert sample_instrument.symbol == "BTC/USD"
    assert sample_instrument.exchange == "kraken"
    assert sample_instrument.asset_class == "crypto"
    assert sample_instrument.tick_size == Decimal("0.01")
    assert sample_instrument.lot_size == Decimal("0.00001")
    assert sample_instrument.min_notional == Decimal("5")
```

### `futures_instrument`

A `FuturesInstrument` instance for BTC-PERP on Kraken Futures:

```python
def test_futures(futures_instrument):
    assert futures_instrument.symbol == "BTC-PERP"
    assert futures_instrument.exchange == "kraken_futures"
    assert futures_instrument.contract_type == "perpetual"
    assert futures_instrument.max_leverage == Decimal("50")
    assert futures_instrument.initial_margin_rate == Decimal("0.02")
    assert futures_instrument.maintenance_margin_rate == Decimal("0.01")
    assert futures_instrument.funding_interval_hours == 8
    assert futures_instrument.expiry is None
```

### `sample_bar`

A single `Bar` instance for BTC/USD:

```python
def test_bar(sample_bar):
    assert sample_bar.instrument_symbol == "BTC/USD"
    assert sample_bar.open == Decimal("42000.00")
    assert sample_bar.high == Decimal("42500.00")
    assert sample_bar.low == Decimal("41800.00")
    assert sample_bar.close == Decimal("42300.00")
    assert sample_bar.volume == Decimal("150.5")
    assert sample_bar.trades == 1200
    assert sample_bar.vwap == Decimal("42150.00")
```

### `sample_universe`

A `Universe` instance with BTC/USD and ETH/USD at 1-hour timeframe on Kraken:

```python
def test_universe(sample_universe):
    assert sample_universe.symbols == ["BTC/USD", "ETH/USD"]
    assert sample_universe.timeframe == "1h"
```

### `tmp_data_dir`

A temporary directory for market data storage, created fresh for each test using pytest's `tmp_path`:

```python
def test_storage(tmp_data_dir):
    # tmp_data_dir is a Path object pointing to a temporary "market_data" directory
    assert tmp_data_dir.exists()
```

### `market_data_store`

A `MarketDataStore` instance backed by `tmp_data_dir`:

```python
def test_store(market_data_store):
    # Ready-to-use store with a clean temporary directory
    market_data_store.write_bars("kraken", "BTC/USD", "1h", bars)
```

## Writing New Tests

### General Patterns

Tests should be placed in `tests/` with filenames matching `test_*.py`. Test functions should start with `test_`.

```python
# tests/test_my_feature.py

from decimal import Decimal

def test_my_feature(sample_instrument):
    """Test description."""
    # Arrange
    expected = Decimal("100")

    # Act
    result = some_function(sample_instrument)

    # Assert
    assert result == expected
```

### Testing with Market Data

Use `market_data_store` and `tmp_data_dir` to test components that need stored data:

```python
from models.bar import Bar
from datetime import datetime
from decimal import Decimal

def test_with_data(market_data_store):
    bars = [
        Bar(
            instrument_symbol="BTC/USD",
            timestamp=datetime(2024, 1, 1, i, 0, 0),
            open=Decimal("42000"),
            high=Decimal("42500"),
            low=Decimal("41800"),
            close=Decimal("42300"),
            volume=Decimal("100"),
        )
        for i in range(24)
    ]
    market_data_store.write_bars("kraken", "BTC/USD", "1h", bars)

    loaded = market_data_store.read_bars("kraken", "BTC/USD", "1h")
    assert len(loaded) == 24
```

### Testing Strategies

Instantiate a `BacktestContext` with your data and run the strategy:

```python
from execution.backtest import BacktestContext
from strategy.sma_crossover import SmaCrossoverStrategy
from data.universe import Universe
from decimal import Decimal
from datetime import datetime, timezone

def test_strategy(tmp_data_dir):
    # Set up market data first...
    universe = Universe.from_symbols(["BTC/USD"], "1h")
    ctx = BacktestContext(
        universe=universe,
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 31, tzinfo=timezone.utc),
        initial_cash=Decimal("10000"),
        data_dir=tmp_data_dir,
    )

    strategy = SmaCrossoverStrategy(ctx, {"fast_period": "10", "slow_period": "30"})
    results = ctx.run(strategy)

    assert "equity_curve" in results
    assert len(results["equity_curve"]) > 0
```

### Testing Indicators

Indicators are pure functions that take numpy arrays and return numpy arrays:

```python
import numpy as np
from analytics.indicators import sma, rsi

def test_sma():
    prices = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=float)
    result = sma(prices, period=3)
    assert len(result) == 3
    assert result[0] == 2.0  # (1+2+3)/3
    assert result[1] == 3.0  # (2+3+4)/3
    assert result[2] == 4.0  # (3+4+5)/3

def test_rsi():
    prices = np.array([44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10,
                       45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
                       46.28, 46.00], dtype=float)
    result = rsi(prices, period=14)
    assert len(result) > 0
    assert 0 <= result[-1] <= 100
```

### Testing Monte Carlo

```python
import numpy as np
from analytics.monte_carlo import bootstrap_equity_paths, gbm_equity_paths

def test_bootstrap():
    returns = np.random.default_rng(42).normal(0.001, 0.02, 100)
    paths = bootstrap_equity_paths(returns, n_simulations=50, seed=42)
    assert paths.shape == (50, 100)
    assert np.all(paths > 0)

def test_gbm():
    paths = gbm_equity_paths(mu=0.1, sigma=0.2, dt=1/252,
                             n_simulations=50, path_length=100, seed=42)
    assert paths.shape == (50, 100)
    assert np.all(paths > 0)
```

### Mocking External APIs

For tests that involve exchange APIs (Kraken, OANDA), mock the HTTP layer:

```python
from unittest.mock import patch, MagicMock

def test_oanda_broker():
    with patch("broker.oanda.requests") as mock_requests:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"account": {"balance": "10000", "NAV": "10000",
                                                    "marginUsed": "0", "unrealizedPL": "0"}}
        mock_resp.status_code = 200
        mock_requests.get.return_value = mock_resp

        # Now test the broker...
```
