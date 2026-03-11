# Configuration Reference

Complete reference for all environment variables, `persistra.toml` settings, process parameters, simulated broker configuration, and exchange defaults.

## Environment Variables

### Exchange Credentials

| Variable | Exchange | Required | Description |
|----------|----------|----------|-------------|
| `KRAKEN_API_KEY` | Kraken Spot | For live trading/data | Kraken spot API key |
| `KRAKEN_API_SECRET` | Kraken Spot | For live trading/data | Kraken spot API secret |
| `KRAKEN_FUTURES_API_KEY` | Kraken Futures | For live futures trading/data | Kraken Futures API key |
| `KRAKEN_FUTURES_API_SECRET` | Kraken Futures | For live futures trading/data | Kraken Futures API secret |
| `OANDA_API_TOKEN` | OANDA | For forex trading/data | OANDA v20 API token |
| `OANDA_ACCOUNT_ID` | OANDA | For forex trading/data | OANDA account ID |
| `OANDA_ENVIRONMENT` | OANDA | No (default: `"practice"`) | `"practice"` or `"live"` |

Credentials are loaded by functions in `lib/config.py`. A `ConfigError` is raised at runtime if required credentials are missing when an exchange operation is attempted.

**Note:** Credentials are not needed for backtesting with already-stored data.

### Setting Credentials

```bash
# Kraken Spot
export KRAKEN_API_KEY="your-api-key"
export KRAKEN_API_SECRET="your-api-secret"

# Kraken Futures (separate account)
export KRAKEN_FUTURES_API_KEY="your-futures-key"
export KRAKEN_FUTURES_API_SECRET="your-futures-secret"

# OANDA
export OANDA_API_TOKEN="your-api-token"
export OANDA_ACCOUNT_ID="your-account-id"
export OANDA_ENVIRONMENT="practice"  # or "live"
```

## persistra.toml Schema

The `persistra.toml` file in the project root defines the environment, dependencies, and state schema.

### `[environment]`

```toml
[environment]
name = "trading"
description = "Systematic/quantitative backtesting and trading environment"
python = "3.12"
```

| Key | Description |
|-----|-------------|
| `name` | Environment name |
| `description` | Human-readable description |
| `python` | Required Python version |

### `[dependencies]`

```toml
[dependencies]
packages = [
    "pandas>=2.0",
    "pyarrow>=14.0",
    "requests>=2.31",
    "numpy>=1.26",
    "websockets>=16.0",
    "httpx>=0.27",
    "scipy>=1.12",
    "fastapi>=0.109",
    "uvicorn>=0.27",
    "jinja2>=3.1",
    "plotly>=5.18",
    "pytest>=8.0",
    "pytest-cov>=4.1",
]

optional_packages = [
    "hmmlearn>=0.3",
]
```

### `[state.schema]`

The state schema defines persistent key-value pairs with types, defaults, and optional history depth.

```toml
[state.schema]
# Account state
account_balances = { type = "dict", default = {}, history = 100 }
account_equity = { type = "float", default = 0.0, history = 1000 }

# Portfolio-level
total_exposure = { type = "float", default = 0.0 }
daily_pnl = { type = "float", default = 0.0, history = 365 }
max_drawdown = { type = "float", default = 0.0 }

# Execution mode
execution_mode = { type = "str", default = "backtest" }

# Backtest universe
backtest_symbols = { type = "str", default = "BTC/USD" }

# Data ingestor
last_update = { type = "str", default = "" }

# Analysis
analysis_symbol = { type = "str", default = "BTC/USD" }
analysis_timeframe = { type = "str", default = "1h" }
analysis_exchange = { type = "str", default = "kraken" }

# Scanning
scan_symbols = { type = "str", default = "BTC/USD,ETH/USD" }
scan_timeframe = { type = "str", default = "1h" }
scan_exchange = { type = "str", default = "kraken" }

# Correlation
correlation_symbols = { type = "str", default = "BTC/USD,ETH/USD" }
correlation_timeframe = { type = "str", default = "1h" }
correlation_exchange = { type = "str", default = "kraken" }
```

**State entry fields:**

| Field | Description |
|-------|-------------|
| `type` | Data type: `str`, `float`, `int`, `dict`, `list` |
| `default` | Default value when not set |
| `history` | Number of historical values to retain (optional) |

## Process Parameters

### `data_ingestor`

Fetches OHLCV bars from an exchange and stores in Parquet.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbols` | `str` | `"BTC/USD"` | Comma-separated symbol list |
| `timeframe` | `str` | `"1h"` | Bar timeframe (`1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`) |
| `backfill_days` | `int` | `365` | Days to backfill on first run |
| `exchange` | `str` | `"kraken"` | Exchange: `kraken`, `kraken_futures`, `oanda` |

```bash
persistra process start data_ingestor \
  -p symbols="BTC/USD,ETH/USD" \
  -p timeframe=1h \
  -p backfill_days=365 \
  -p exchange=kraken
```

### `sma_crossover`

Runs the SMA crossover strategy in backtest mode (job).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbols` | `str` | `"BTC/USD"` | Comma-separated symbol list |
| `timeframe` | `str` | `"1h"` | Bar timeframe |
| `fast_period` | `int` | `10` | Fast SMA period |
| `slow_period` | `int` | `30` | Slow SMA period |
| `quantity` | `str` | `"0.01"` | Trade quantity per signal |
| `initial_cash` | `str` | `"10000"` | Starting equity |
| `fee_rate` | `str` | `"0.0026"` | Fee rate per trade |
| `slippage_pct` | `str` | `"0.0001"` | Slippage percentage |
| `max_position_size` | `str` | `"1.0"` | Maximum position size |
| `start` | `str` | `""` | Start date (ISO format). Empty = `2024-01-01` |
| `end` | `str` | `""` | End date (ISO format). Empty = now |

```bash
persistra process start sma_crossover \
  -p symbols=BTC/USD \
  -p fast_period=10 \
  -p slow_period=30 \
  -p initial_cash=10000
```

### `batch_backtest`

Runs parameter sweep backtesting.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `strategy` | `str` | `"sma_crossover"` | Registered strategy name |
| `symbols` | `str` | `"BTC/USD"` | Comma-separated symbol list |
| `timeframe` | `str` | `"1h"` | Bar timeframe |
| `grid` | `str` | `'{"fast_period": [5,10,15,20], "slow_period": [20,30,40,50]}'` | JSON parameter grid |
| `initial_cash` | `str` | `"10000"` | Starting equity per run |
| `n_workers` | `int` | `0` | Number of parallel workers (0 = auto) |
| `start` | `str` | `""` | Start date (ISO format) |
| `end` | `str` | `""` | End date (ISO format) |

The `grid` parameter defines a Cartesian product of parameter values. Each combination runs as a separate backtest.

```bash
persistra process start batch_backtest \
  -p strategy=sma_crossover \
  -p symbols="BTC/USD,ETH/USD" \
  -p grid='{"fast_period": [5, 10, 15, 20, 25], "slow_period": [20, 30, 40, 50, 60]}'
```

### `dashboard`

Starts the interactive web dashboard (daemon).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `port` | `int` | `8050` | HTTP port |
| `host` | `str` | `"127.0.0.1"` | Bind address |

```bash
persistra process start dashboard -p port=8050
```

### `risk_monitor`

Runs as a daemon to monitor risk limits in real time.

```bash
persistra process start risk_monitor
```

## Simulated Broker Configuration

The `SimulatedBroker` (`lib/broker/simulated.py`) is used by `BacktestContext` and `PaperContext`. It supports spot, futures (margin mode), and forex (spread-based) simulation.

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `initial_cash` | `Decimal` | `10000` | Starting equity in quote currency |
| `quote_currency` | `str` | `"USD"` | Quote currency for the account |
| `fee_rate` | `Decimal` | `0.0026` | Fee rate per trade (proportion of notional) |
| `slippage_pct` | `Decimal` | `0.0001` | Slippage as percentage of price (1 bps) |
| `margin_mode` | `bool` | `False` | Enable margin/leverage simulation |
| `leverage` | `Decimal` | `1` | Leverage multiplier (only when `margin_mode=True`) |
| `spread_pips` | `Decimal` | `0` | Spread in pips (for forex simulation) |

### BacktestContext Parameters

`BacktestContext` wraps `SimulatedBroker` and auto-detects exchange settings:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `universe` | `Universe` | (required) | Trading universe |
| `start` | `datetime \| None` | `None` | Backtest start date |
| `end` | `datetime \| None` | `None` | Backtest end date |
| `initial_cash` | `Decimal` | `10000` | Starting equity |
| `fee_rate` | `Decimal` | `0.0026` | Fee rate |
| `slippage_pct` | `Decimal` | `0.0001` | Slippage percentage |
| `max_position_size` | `Decimal` | `1.0` | Risk manager position limit |
| `data_dir` | `Path \| None` | `.persistra/market_data` | Market data directory |
| `exchange` | `str \| None` | auto-detect | Exchange name |
| `margin_mode` | `bool \| None` | auto-detect | Auto-detected from `FuturesInstrument` |
| `leverage` | `Decimal` | `1` | Leverage for futures |
| `spread_pips` | `Decimal` | `0` | Spread for forex |

Auto-detection behavior:
- `exchange` is inferred from the first instrument in the universe
- `margin_mode` is set to `True` if any instrument is a `FuturesInstrument`

## Default Values Per Exchange

Defined in `lib/config.py` as `EXCHANGE_DEFAULTS`:

### Kraken Spot

| Parameter | Default | Description |
|-----------|---------|-------------|
| `fee_rate` | `0.0026` | Taker fee (0.26%) |
| `slippage_pct` | `0.0001` | 1 basis point |
| `quote_currency` | `USD` | Quote currency |

### Kraken Futures

| Parameter | Default | Description |
|-----------|---------|-------------|
| `fee_rate` | `0.0005` | Taker fee (0.05%) |
| `slippage_pct` | `0.0001` | 1 basis point |
| `quote_currency` | `USD` | Quote currency |
| `default_leverage` | `10` | Default leverage multiplier |

### OANDA (Forex)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `fee_rate` | `0` | No commission (spread-based) |
| `slippage_pct` | `0` | No additional slippage |
| `spread_pips` | `1.5` | Simulated bid-ask spread |
| `quote_currency` | `USD` | Quote currency |
| `default_leverage` | `50` | Default leverage multiplier |

Access defaults programmatically:

```python
from config import get_exchange_defaults

defaults = get_exchange_defaults("kraken")
# {"fee_rate": Decimal("0.0026"), "slippage_pct": Decimal("0.0001"), "quote_currency": "USD"}
```

## Risk Defaults

Defined in `lib/config.py` as `RISK_DEFAULTS`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_position_size` | `1.0` | Maximum position size per instrument |
| `max_order_value` | `100000` | Maximum single order value |
| `daily_loss_limit` | `-500` | Daily loss limit (triggers risk event) |
| `max_drawdown_limit` | `0.20` | Maximum drawdown limit (20%) |

## Dashboard Defaults

Defined in `lib/config.py` as `DASHBOARD_DEFAULTS`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `host` | `127.0.0.1` | Bind address |
| `port` | `8050` | HTTP port |

## State Namespaces

State is organized into namespaces accessed via `env.state.ns("namespace")`:

### `backtest.*`

| Key | Type | Set by |
|-----|------|--------|
| `results` | `dict` | `sma_crossover` process |
| `equity_curve_path` | `str` | `sma_crossover` process |
| `fills_path` | `str` | `sma_crossover` process |
| `universe` | `str` | `sma_crossover` process |

### `strategy.<name>.*`

| Key | Type | Set by |
|-----|------|--------|
| `params` | `dict` | Strategy process |
| `metrics` | `dict` | Strategy process |

### `batch.*`

| Key | Type | Set by |
|-----|------|--------|
| `best_params` | `dict` | `batch_backtest` process |
| `best_metrics` | `dict` | `batch_backtest` process |
| `total_runs` | `int` | `batch_backtest` process |
| `successful_runs` | `int` | `batch_backtest` process |

### `data.*`

| Key | Type | Set by |
|-----|------|--------|
| `last_update` | `str` (ISO datetime) | `data_ingestor` process |
| `{symbol}_{timeframe}_bars` | `int` | `data_ingestor` process |

### Global State

These keys are defined at the top level of `[state.schema]`:

| Key | Type | Default | History |
|-----|------|---------|---------|
| `account_balances` | `dict` | `{}` | 100 |
| `account_equity` | `float` | `0.0` | 1000 |
| `total_exposure` | `float` | `0.0` | -- |
| `daily_pnl` | `float` | `0.0` | 365 |
| `max_drawdown` | `float` | `0.0` | -- |
| `execution_mode` | `str` | `"backtest"` | -- |
| `backtest_symbols` | `str` | `"BTC/USD"` | -- |
| `analysis_symbol` | `str` | `"BTC/USD"` | -- |
| `analysis_timeframe` | `str` | `"1h"` | -- |
| `analysis_exchange` | `str` | `"kraken"` | -- |
| `scan_symbols` | `str` | `"BTC/USD,ETH/USD"` | -- |
| `scan_timeframe` | `str` | `"1h"` | -- |
| `scan_exchange` | `str` | `"kraken"` | -- |
| `correlation_symbols` | `str` | `"BTC/USD,ETH/USD"` | -- |
| `correlation_timeframe` | `str` | `"1h"` | -- |
| `correlation_exchange` | `str` | `"kraken"` | -- |

## Further Reading

- [Getting Started](getting-started.md) — Installation and environment setup
- [Architecture](architecture.md) — How configuration flows into the system
- [Data Management](data-management.md) — Data ingestion parameters in detail
- [Strategies](strategies.md) — Strategy parameters and broker interaction
