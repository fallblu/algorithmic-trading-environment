# Getting Started

This guide walks you through setting up the trader project, fetching market data, running your first backtest, and understanding the project layout.

## Prerequisites

- **Python 3.12** (specified in `persistra.toml`)
- **Persistra** CLI installed and available on your `PATH`
- A terminal with `bash` or `zsh`

### Exchange accounts (optional, only for live data / trading)

| Exchange | What you need |
|----------|---------------|
| Kraken Spot | API key + secret from [kraken.com](https://www.kraken.com) |
| Kraken Futures | Separate API key + secret from Kraken Futures |
| OANDA | API token + account ID from [oanda.com](https://www.oanda.com) |

Backtesting with already-stored data does not require any API credentials.

## Installation

```bash
# 1. Clone the repository
git clone <repo-url> trader
cd trader

# 2. Let Persistra create the environment from persistra.toml
persistra env create

# 3. Verify the environment
persistra env info
```

Persistra reads `persistra.toml` and installs all required packages:

| Category | Packages |
|----------|----------|
| Data & numerics | `pandas>=2.0`, `pyarrow>=14.0`, `numpy>=1.26`, `scipy>=1.12` |
| HTTP / WebSocket | `requests>=2.31`, `httpx>=0.27`, `websockets>=16.0` |
| Dashboard | `fastapi>=0.109`, `uvicorn>=0.27`, `jinja2>=3.1`, `plotly>=5.18` |
| Testing | `pytest>=8.0`, `pytest-cov>=4.1` |
| Optional | `hmmlearn>=0.3` (regime detection) |

### Environment variables

Set credentials for the exchanges you plan to use:

```bash
# Kraken Spot
export KRAKEN_API_KEY="..."
export KRAKEN_API_SECRET="..."

# Kraken Futures
export KRAKEN_FUTURES_API_KEY="..."
export KRAKEN_FUTURES_API_SECRET="..."

# OANDA
export OANDA_API_TOKEN="..."
export OANDA_ACCOUNT_ID="..."
export OANDA_ENVIRONMENT="practice"   # or "live"
```

See [Configuration Reference](configuration-reference.md) for the full table.

## Quick start

### 1. Fetch market data

Ingest one year of hourly BTC/USD bars from Kraken:

```bash
persistra process start data_ingestor \
  -p symbols=BTC/USD \
  -p timeframe=1h \
  -p backfill_days=365 \
  -p exchange=kraken
```

Multiple symbols:

```bash
persistra process start data_ingestor \
  -p symbols="BTC/USD,ETH/USD,SOL/USD" \
  -p timeframe=1h \
  -p exchange=kraken
```

Data is stored in `.persistra/market_data/{exchange}/{symbol}/{timeframe}.parquet`.

### 2. Run a backtest

Run the built-in SMA crossover strategy:

```bash
persistra process start sma_crossover \
  -p symbols=BTC/USD \
  -p timeframe=1h \
  -p fast_period=10 \
  -p slow_period=30 \
  -p initial_cash=10000
```

The process logs key metrics when it completes: total return, Sharpe ratio, max drawdown, number of trades, and win rate. Results are persisted to the `backtest` state namespace.

### 3. View results

Check stored state:

```bash
persistra state get backtest.results
persistra state get strategy.sma_crossover.metrics
```

Or start the dashboard:

```bash
persistra process start dashboard -p port=8050
# Open http://127.0.0.1:8050
```

### 4. Run a parameter sweep

Sweep over fast and slow period combinations:

```bash
persistra process start batch_backtest \
  -p strategy=sma_crossover \
  -p symbols=BTC/USD \
  -p timeframe=1h \
  -p grid='{"fast_period": [5, 10, 15, 20], "slow_period": [20, 30, 40, 50]}'
```

### 5. Run a workflow

Workflows chain multiple steps (ingest, backtest, analyze) into a DAG:

```bash
persistra workflow run backtest \
  --param symbols=BTC/USD \
  --param timeframe=1h
```

## Project structure

```
trader/
├── persistra.toml            # Environment config, dependencies, state schema
├── docs/                     # Documentation
│   ├── getting-started.md    # This file
│   ├── architecture.md       # Technical architecture reference
│   ├── strategies.md         # Writing custom strategies
│   ├── data-management.md    # Data ingestion and storage
│   └── configuration-reference.md  # All configuration in one place
│
├── lib/                      # Core library code
│   ├── analytics/            # Performance metrics, indicators, statistical analysis
│   │   └── indicators.py     # SMA, EMA, RSI, MACD, Bollinger Bands, ATR, ADX, etc.
│   ├── broker/               # Broker ABC and implementations
│   │   ├── base.py           # Broker ABC (submit_order, get_position, etc.)
│   │   ├── simulated.py      # SimulatedBroker for backtest/paper
│   │   ├── kraken.py         # Kraken spot broker
│   │   ├── kraken_futures.py # Kraken futures broker
│   │   └── oanda.py          # OANDA broker
│   ├── config.py             # Centralized credentials & exchange defaults
│   ├── dashboard/            # Web dashboard (FastAPI + Plotly)
│   ├── data/                 # Data feeds, storage, universe, price panel
│   │   ├── exchange.py       # Exchange ABC and registry
│   │   ├── feed.py           # DataFeed ABC
│   │   ├── store.py          # MarketDataStore (Parquet OHLCV)
│   │   ├── tick_store.py     # TickStore (daily Parquet tick files)
│   │   ├── result_store.py   # ResultStore (UUID-indexed results)
│   │   ├── price_panel.py    # PricePanel (rolling MultiIndex DataFrame)
│   │   └── universe.py       # Universe (symbol + timeframe + instruments)
│   ├── events.py             # Event bus (publish/subscribe)
│   ├── execution/            # Execution contexts
│   │   ├── context.py        # ExecutionContext ABC
│   │   ├── backtest.py       # BacktestContext (bar-by-bar replay)
│   │   └── batch.py          # BatchBacktest (parameter sweeps)
│   ├── models/               # Data models (Bar, Order, Fill, Instrument, etc.)
│   ├── risk/                 # Risk manager
│   └── strategy/             # Strategy ABC, registry, built-in strategies
│       ├── base.py           # Strategy ABC
│       ├── registry.py       # @register decorator + get_strategy()
│       └── sma_crossover.py  # Built-in SMA crossover strategy
│
├── processes/                # Persistra process entry points (jobs/daemons)
│   ├── data_ingestor.py      # Fetch & store OHLCV data
│   ├── sma_crossover.py      # Backtest SMA crossover (job)
│   ├── sma_crossover_live.py # Paper/live SMA crossover (daemon)
│   ├── batch_backtest.py     # Parameter sweep (job)
│   ├── risk_monitor.py       # Risk monitoring (daemon)
│   └── dashboard.py          # Web dashboard (daemon)
│
├── workflows/                # Persistra workflow DAGs
│   ├── backtest.py           # Ingest -> backtest -> analyze
│   ├── batch_backtest.py     # Ingest -> batch sweep -> rank
│   ├── analyze.py            # Statistical analysis pipeline
│   └── stress_test.py        # Monte Carlo stress testing
│
└── tests/                    # Test suite (pytest)
    ├── conftest.py           # Shared fixtures
    ├── test_backtest.py
    ├── test_indicators.py
    ├── test_simulated_broker.py
    └── ...
```

## What to read next

| Topic | Document |
|-------|----------|
| System architecture and ABC hierarchy | [Architecture](architecture.md) |
| Writing your own strategy | [Strategies](strategies.md) |
| Data ingestion, storage, and querying | [Data Management](data-management.md) |
| Environment variables, defaults, process parameters | [Configuration Reference](configuration-reference.md) |
