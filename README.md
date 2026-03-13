# Algorithmic Trading Environment

A Python 3.12 quantitative trading platform supporting backtesting, paper trading, and live trading across Kraken (crypto) and OANDA (forex).

## Features

- **Backtesting** — replay historical data with configurable fees, slippage, and margin
- **Batch parameter sweeps** — parallel grid search across strategy parameters
- **Paper trading** — live data feeds with simulated execution
- **Live trading** — real order execution via Kraken and OANDA APIs
- **Risk management** — pre-trade checks, position limits, daily loss limits, drawdown circuit breakers
- **Portfolio optimization** — mean-variance, minimum variance, risk parity, and equal weight allocation
- **Web dashboard** — interactive FastAPI dashboard to configure, launch, and monitor all workflows
- **10 built-in strategies** — SMA crossover, Bollinger reversion, RSI, MACD, breakout, pairs trading, regime-adaptive, and more

## Quick Start

```bash
# Clone and install
git clone <repo-url> algorithmic-trading-environment
cd algorithmic-trading-environment
pip install pandas pyarrow numpy requests websockets httpx scipy
pip install fastapi uvicorn jinja2 plotly pytest pytest-cov

# Set Python path
export PYTHONPATH="$PWD/lib:$PYTHONPATH"

# Ingest market data
persistra process run data_ingestor -p symbols=BTC/USD -p timeframe=1h -p exchange=kraken

# Run a backtest
persistra process run backtest -p strategy=sma_crossover -p symbols=BTC/USD -p timeframe=1h

# Start the dashboard
persistra process start dashboard
# Open http://127.0.0.1:8050
```

## Project Structure

```
lib/
  analytics/       Indicators, performance metrics, statistics
  broker/          Broker implementations (simulated, Kraken, OANDA)
  dashboard/       FastAPI web dashboard
  data/            Data feeds, storage, price panel
  execution/       Backtest, paper, and live execution contexts
  models/          Data models (Bar, Order, Fill, Position, Account)
  risk/            Risk management, exposure limits, position sizing
  strategy/        Strategy ABC and built-in strategies
processes/         Persistra process definitions
workflows/         Persistra workflow DAGs
docs/              Documentation
```

## Documentation

- [Getting Started](docs/getting-started.md) — installation, first backtest
- [Architecture](docs/architecture.md) — system design and module reference
- [Writing Strategies](docs/writing-strategies.md) — custom strategy development
- [Backtesting](docs/backtesting.md) — single and batch backtests, analytics
- [Paper & Live Trading](docs/paper-and-live-trading.md) — real-market execution
- [Risk Management](docs/risk-management.md) — risk limits and position sizing
- [Portfolio Optimization](docs/portfolio-optimization.md) — multi-asset allocation
