# Getting Started

This guide walks you through setting up the Trader platform and running your first backtest.

## Prerequisites

- Python 3.12 or later
- pip or a compatible package manager

## Installation

1. **Clone the repository:**

```bash
git clone <repo-url> trader
cd trader
```

2. **Install dependencies:**

The project uses Persistra for process management. Dependencies are defined in `persistra.toml`:

```bash
pip install pandas pyarrow numpy requests websockets httpx scipy
pip install fastapi uvicorn jinja2 plotly
pip install pytest pytest-cov
```

Optional (for regime detection):

```bash
pip install hmmlearn
```

3. **Set up your Python path:**

```bash
export PYTHONPATH="$PWD/lib:$PYTHONPATH"
```

## Environment Variables

For paper and live trading, set exchange credentials:

**Kraken (crypto):**

```bash
export KRAKEN_API_KEY="your-api-key"
export KRAKEN_API_SECRET="your-api-secret"
```

**OANDA (forex):**

```bash
export OANDA_API_TOKEN="your-api-token"
export OANDA_ACCOUNT_ID="your-account-id"
export OANDA_ENVIRONMENT="practice"   # or "live"
```

These are not needed for backtesting with local data.

## Project Structure

```
trader/
  lib/                    # Core library
    analytics/            # Indicators, performance metrics, statistics
    broker/               # Broker implementations (simulated, Kraken, OANDA)
    dashboard/            # FastAPI web dashboard
    data/                 # Data feeds, storage, price panel
    execution/            # Backtest, paper, and live execution contexts
    models/               # Data models (Bar, Order, Fill, Position, etc.)
    risk/                 # Risk management, exposure limits, position sizing
    strategy/             # Strategy ABC and built-in strategies
    config.py             # Configuration and defaults
    constants.py          # Shared constants and enums
    events.py             # Event bus (pub/sub)
    exceptions.py         # Exception hierarchy
    helpers.py            # Utility functions
  processes/              # Persistra process definitions
  workflows/              # Persistra workflow DAGs
  data/                   # Market data storage (Parquet files)
  docs/                   # Documentation
```

## Running Your First Backtest

### Step 1: Prepare Market Data

Before backtesting, you need historical market data. Ingest data from an exchange:

```python
from pathlib import Path
from data.store import MarketDataStore
from data.exchange import get_exchange

store = MarketDataStore(base_dir=Path(".persistra/market_data"))
exchange = get_exchange("kraken")

# Fetch 1-hour BTC/USD bars
bars = exchange.fetch_ohlcv("BTC/USD", timeframe="1h")
store.write_bars(bars, exchange="kraken", timeframe="1h")
```

Or use the data ingestor process if configured with Persistra.

### Step 2: Set Up the Universe

A `Universe` defines the instruments and timeframe for your backtest:

```python
from data.universe import Universe

universe = Universe.from_symbols(
    symbols=["BTC/USD"],
    timeframe="1h",
    exchange="kraken",
)
```

For forex:

```python
universe = Universe.from_forex_symbols(
    symbols=["EUR/USD", "GBP/USD"],
    timeframe="1h",
    exchange="oanda",
)
```

### Step 3: Configure and Run

```python
from decimal import Decimal
from datetime import datetime
from execution.backtest import BacktestContext
from strategy.sma_crossover import SmaCrossover

# Create execution context
ctx = BacktestContext(
    universe=universe,
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31),
    initial_cash=Decimal("10000"),
    fee_rate=Decimal("0.0026"),      # 0.26% per trade
    slippage_pct=Decimal("0.0001"),  # 0.01% slippage
)

# Create strategy
strategy = SmaCrossover(ctx, params={
    "fast_period": 10,
    "slow_period": 30,
    "quantity": "0.01",
    "symbols": ["BTC/USD"],
})

# Run backtest
results = ctx.run(strategy)
```

### Step 4: Examine Results

The `results` dictionary contains:

```python
print(f"Initial equity: {results['initial_equity']}")
print(f"Final equity:   {results['final_equity']}")
print(f"Bars processed: {results['bars_processed']}")
print(f"Total fills:    {len(results['fills'])}")
```

Compute performance metrics:

```python
from analytics.performance import compute_performance

metrics = compute_performance(
    equity_curve=results["equity_curve"],
    fills=results["fills"],
)

print(f"Total return:   {metrics['total_return']:.2%}")
print(f"Sharpe ratio:   {metrics['sharpe_ratio']:.2f}")
print(f"Max drawdown:   {metrics['max_drawdown']:.2%}")
print(f"Win rate:       {metrics['win_rate']:.2%}")
print(f"Profit factor:  {metrics['profit_factor']:.2f}")
```

### Step 5: View Results in Dashboard

Start the web dashboard to visualize your backtest:

```bash
# Via Persistra process
persistra run dashboard

# Or directly
python -c "
from dashboard.app import create_app
import uvicorn
app = create_app()
uvicorn.run(app, host='127.0.0.1', port=8050)
"
```

Open `http://127.0.0.1:8050` in your browser. Navigate to the **Backtests** tab to see equity curves, trade markers, and performance statistics.

## Next Steps

- [Writing a Custom Strategy](writing-strategies.md) — build your own strategy from scratch
- [Running Backtests](backtesting.md) — batch testing, parameter sweeps, stress tests
- [Paper & Live Trading](paper-and-live-trading.md) — transition from backtest to real markets
- [Risk Management](risk-management.md) — configure risk limits and position sizing
- [Portfolio Optimization](portfolio-optimization.md) — multi-asset allocation strategies
