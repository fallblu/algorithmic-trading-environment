# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Commands

```bash
# Tests
pytest                                          # all tests
pytest tests/test_models.py                     # one file
pytest tests/test_models.py::test_order_creation  # one test
pytest -v --tb=short                            # verbose, compact tracebacks

# Run dashboard
persistra process start dashboard

# Run backtest
persistra process run backtest -p strategy=sma_crossover -p symbols=BTC/USD

# Fetch data
persistra process run data_ingestor -p symbols=BTC/USD -p exchange=kraken -p timeframe=1h
```

## Architecture

Dashboard-first portfolio management platform built on Persistra. All trading
workflows are driven through the web dashboard, not the CLI.

### Layer Dependency (top → bottom)

```
Persistra processes (backtest, data_ingestor, dashboard, paper_trader, live_trader)
  → Dashboard (FastAPI + Jinja2 + HTMX + Plotly + Monaco)
    → Charts (ChartRegistry, ChartBuilder) + Modules (discovery, loader)
    → Portfolio (model, orchestrator, storage)
      → Execution (backtest, paper, live contexts)
        → Risk (manager, rules)
        → Strategy (ABC, registry, function adapter)
          → Broker (simulated, kraken, oanda)
            → Data (store, feeds, API clients, WebSocket)
              → Models (Bar, Order, Fill, Position, Instrument)
```

### Key Concepts

- **Portfolio**: Container of strategies with capital allocations + risk rules.
  Promotes through modes: Backtest → Paper → Live.
- **Strategy**: Generates orders via `on_bar(bars, positions, params) -> list[Order]`.
  Written in Monaco editor (function-based) or as class-based plugins in `strategies/`.
- **Portfolio Orchestration**: Optional `manage_portfolio()` function that adjusts
  strategy allocations dynamically.
- **Modules**: User-created packages under `lib/<name>/`. Can export `__charts__`
  for visualization in the chart builder.
- **Numeric types**: `float` internally for speed/pandas compatibility. `Decimal`
  at exchange API boundary (in KrakenBroker/OandaBroker) for precision.

### Code Organization

```
lib/
  models/       — Data classes (Bar, Order, Fill, Position, Instrument)
  broker/       — Broker ABC + SimulatedBroker + KrakenBroker + OandaBroker
  data/         — MarketDataStore (Parquet) + API clients + WebSocket feeds
  strategy/     — Strategy ABC + FunctionStrategy adapter + registry + templates
  portfolio/    — Portfolio model + orchestrator + storage
  execution/    — ExecutionContext ABC + Backtest/Paper/Live contexts
  risk/         — RiskManager + enforced rules (position, drawdown, exposure)
  analytics/    — Performance metrics (Sharpe, drawdown, win rate, etc.)
  charts/       — ChartRegistry + ChartBuilder + built-in series
  modules/      — Module discovery + loader for user-created packages
  dashboard/    — FastAPI app + routes + templates + static assets
```

## Conventions

- All modules use `from __future__ import annotations` (PEP 563).
- Line length: 99. Target: Python 3.12.
- Use `float` for prices/quantities in models and computation.
- Use `Decimal` only at the exchange API boundary (broker/kraken.py, broker/oanda.py).
- Strategies dir (`strategies/`) is for user class-based plugins. Don't put core code there.
- User-created modules go under `lib/<name>/`. Core packages are not editable from dashboard.
