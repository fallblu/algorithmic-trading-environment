# Trading Platform Major Refactor — Implementation Plan

## Current State Summary

The platform is a ~2,800 line Python trading system built on Persistra, with clean ABC-driven architecture:

- **Exchange support**: Kraken spot only (REST + WebSocket v2)
- **Execution modes**: Backtest, paper trading (simulated broker + live feed), live trading (real Kraken broker)
- **Strategy framework**: ABC-based with `on_bar()` receiving a MultiIndex DataFrame price panel; one example strategy (SMA crossover)
- **Data**: Parquet-based OHLCV storage, historical backfill via Kraken REST, live data via Kraken WebSocket
- **Analytics**: Performance metrics (Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor)
- **Models**: Instrument (with FuturesInstrument subclass), Bar, FundingRate, Order, Fill, Position, Account
- **Risk**: Pre-trade validation (max position size, max order value, kill switch)
- **No dashboard/visualization layer exists**

### Key Architecture Patterns
- `DataFeed` ABC → `HistoricalFeed`, `LiveFeed`
- `Broker` ABC → `SimulatedBroker`, `KrakenBroker`
- `ExecutionContext` ABC → `BacktestContext`, `PaperContext`, `LiveContext`
- `Strategy` ABC → `SmaCrossover`
- `Universe` from symbol lists; `PricePanel` for rolling window management
- Persistra processes (job/daemon) as entry points; workflows for DAG orchestration

---

## Phase 1: Kraken Derivatives (Perpetual Futures)

### Goal
Add perpetual futures trading on Kraken Futures (`futures.kraken.com`) across all three execution modes (backtest, paper, live).

### Key Design Decisions
- Kraken Futures has a **separate API** from Kraken spot (`futures.kraken.com` vs `api.kraken.com`), with different auth, endpoints, and WebSocket URLs.
- The existing `FuturesInstrument` model already exists with leverage/margin fields — we extend it.
- The `SimulatedBroker` needs margin accounting for futures; currently it does spot-style cash accounting.

### New/Modified Files

#### `lib/data/kraken_futures_api.py` (new)
REST client for `futures.kraken.com`:
- `fetch_ohlcv_futures()` — OHLCV candle data from `/api/charts/v1/trade/...`
- `backfill_ohlcv_futures()` — paginated historical backfill
- `fetch_funding_rate()` — current and historical funding rates from `/derivatives/api/v3/tickers`
- `fetch_instruments()` — available perpetual contracts from `/derivatives/api/v3/instruments`
- Symbol mapping: e.g. `"BTC-PERP"` → Kraken's `"PF_XBTUSD"`

#### `lib/data/kraken_futures_auth.py` (new)
Authentication for the Kraken Futures API:
- Uses `KRAKEN_FUTURES_API_KEY` and `KRAKEN_FUTURES_API_SECRET` env vars
- Different signing scheme from spot (still HMAC-based but different nonce/path handling)
- `private_futures_request()` for authenticated endpoints

#### `lib/data/live_futures.py` (new)
WebSocket feed for Kraken Futures (`wss://futures.kraken.com/ws/v1`):
- Subclass of `DataFeed`
- Subscribes to `candles_trade_{interval}` channel
- Subscribes to `ticker` channel for real-time mark price, funding rate, open interest
- Same daemon thread + asyncio pattern as existing `LiveFeed`
- Also publishes `FundingRate` objects alongside `Bar` objects

#### `lib/broker/kraken_futures.py` (new)
Live broker for Kraken Futures:
- Subclass of `Broker`
- Order submission via `/derivatives/api/v3/sendorder`
- Position management via `/derivatives/api/v3/openpositions` (Kraken Futures has native position tracking, unlike spot)
- Account/margin queries via `/derivatives/api/v3/accounts`
- Leverage setting via `/derivatives/api/v3/leveragepreferences`
- Order types: market, limit, stop, take-profit

#### `lib/broker/simulated.py` (modify)
Extend `SimulatedBroker` to support margin-based futures accounting:
- Add `margin_mode: bool` flag and `leverage: Decimal` parameter
- When `margin_mode=True`:
  - Opening a position requires `notional / leverage` as initial margin (deducted from available balance)
  - Track `margin_used` on Position objects
  - Compute `liquidation_price` based on maintenance margin rate
  - Apply funding rate charges/credits at configured intervals
  - PnL is computed on full notional, not just margin posted
- When `margin_mode=False`: existing spot behavior unchanged
- Add `apply_funding()` method called by backtest engine at funding intervals

#### `lib/data/universe.py` (modify)
- Add `from_futures_symbols()` class method that creates `FuturesInstrument` instances
- Add defaults dict `_KRAKEN_FUTURES_DEFAULTS` for common perp contracts (BTC-PERP, ETH-PERP, SOL-PERP, etc.)
- Set `asset_class="crypto_futures"` to distinguish from spot

#### `lib/execution/backtest.py` (modify)
- Detect whether universe contains `FuturesInstrument` and configure `SimulatedBroker` accordingly (margin mode, leverage)
- During replay loop, call `broker.apply_funding()` at 8-hour intervals when processing futures
- Pass funding rate data alongside bar data

#### `lib/execution/paper.py` and `lib/execution/live.py` (modify)
- Add factory logic: if universe is futures, use `LiveFuturesFeed` and (for live) `KrakenFuturesBroker`
- Paper mode: `LiveFuturesFeed` + `SimulatedBroker(margin_mode=True)`
- Live mode: `LiveFuturesFeed` + `KrakenFuturesBroker`

#### `processes/data_ingestor.py` (modify)
- Add `exchange` parameter support for `"kraken_futures"`
- Route to `kraken_futures_api.backfill_ohlcv_futures()` when exchange is futures

---

## Phase 2: OANDA Forex Integration

### Goal
Add forex trading via OANDA v20 REST API with streaming prices for live data, using `SimulatedBroker` for paper trading (not OANDA's practice account).

### Key Design Decisions
- OANDA REST v20 for historical data, orders, account info
- OANDA streaming API for real-time price updates (sub-second tick data)
- Paper trading uses `SimulatedBroker` with forex-appropriate defaults (pip-based, leverage, typical spreads)
- Tick data recording to Parquet for later analysis
- Forex instruments use pip-based tick sizing (e.g., 0.0001 for EUR/USD, 0.01 for USD/JPY)

### New/Modified Files

#### `lib/data/oanda_api.py` (new)
REST client for OANDA v20:
- `fetch_candles()` — OHLCV from `/v3/instruments/{instrument}/candles`
- `backfill_candles()` — paginated historical backfill with OANDA's 5000-candle limit per request
- `fetch_instruments()` — available forex pairs from `/v3/accounts/{id}/instruments`
- `fetch_pricing()` — current bid/ask from `/v3/accounts/{id}/pricing`
- Granularity mapping: `"1m"` → `"M1"`, `"1h"` → `"H1"`, `"1d"` → `"D"`, etc.
- Symbol format: our `"EUR/USD"` → OANDA's `"EUR_USD"`
- Auth via `OANDA_API_TOKEN` and `OANDA_ACCOUNT_ID` env vars
- Base URL selection: practice (`api-fxpractice.oanda.com`) vs live (`api-fxtrade.oanda.com`) based on `OANDA_ENVIRONMENT` env var

#### `lib/data/oanda_stream.py` (new)
Streaming price feed for OANDA:
- Connects to `stream-fxtrade.oanda.com/v3/accounts/{id}/pricing/stream`
- Parses streaming JSON price ticks (bid/ask/mid)
- Aggregates ticks into OHLCV bars at the configured timeframe
- Background thread with reconnection logic (same pattern as Kraken `LiveFeed`)
- **Tick recording**: optionally writes raw tick data to Parquet files under `.persistra/tick_data/oanda/{pair}/`
  - Schema: `(timestamp, bid, ask, mid, spread, liquidity)`
  - Configurable via `record_ticks=True` parameter
  - Rotates files daily to keep individual files manageable

#### `lib/data/live_oanda.py` (new)
`DataFeed` subclass for OANDA:
- Uses `oanda_stream.py` for real-time bar construction
- Uses `oanda_api.py` for historical bar fetching (warmup)
- Same interface as `LiveFeed` — `subscribe()`, `next_bar()`, `historical_bars()`

#### `lib/broker/oanda.py` (new)
Live broker for OANDA (for live trading mode only):
- Subclass of `Broker`
- Order submission via `/v3/accounts/{id}/orders` (market, limit, stop, trailing stop)
- Position queries via `/v3/accounts/{id}/positions`
- Account info via `/v3/accounts/{id}/summary`
- Native support for:
  - Fractional pip pricing
  - Leverage (OANDA handles margin server-side)
  - Take-profit and stop-loss attached to orders
  - Long/short position netting

#### `lib/data/universe.py` (modify)
- Add `_OANDA_DEFAULTS` dict for common forex pairs with correct tick sizes (pip values):
  - EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, etc.
  - Cross pairs: EUR/GBP, GBP/JPY, etc.
- Add `from_forex_symbols()` class method with `exchange="oanda"`, `asset_class="forex"`
- Forex lot sizes: standard (100,000), mini (10,000), micro (1,000)

#### `lib/broker/simulated.py` (modify)
- For forex paper trading: configure with forex-specific defaults
  - `fee_rate=Decimal("0")` (forex has no commission, cost is in spread)
  - `slippage_pct` models spread widening
  - Add `spread_pips` parameter for fixed simulated spread
- Add spread simulation: buy at ask (mid + half spread), sell at bid (mid - half spread)

#### `lib/execution/paper.py` and `lib/execution/live.py` (modify)
- Factory logic: if `exchange="oanda"`, use `LiveOandaFeed` and (for live) `OandaBroker`
- Paper mode: `LiveOandaFeed` + `SimulatedBroker` with forex config

#### `processes/data_ingestor.py` (modify)
- Route to `oanda_api.backfill_candles()` when `exchange="oanda"`

#### `lib/data/tick_store.py` (new)
Storage for raw tick data:
- Write/read tick DataFrames to Parquet under `.persistra/tick_data/{exchange}/{pair}/YYYY-MM-DD.parquet`
- Schema: `(timestamp_us, bid, ask, mid, spread, volume)`
- Query by date range
- Aggregation helpers: ticks → bars at arbitrary timeframes

---

## Phase 3: Historical Data Analysis Toolkit

### Goal
Provide statistical analysis and technical scanning capabilities on stored market data without running a backtest.

### New Files

#### `lib/analytics/data_analyzer.py` (new)
Core statistical analysis engine:

**Statistical Analysis:**
- `return_distribution(bars, period)` — compute return series, fit normal/t-distribution, compute skewness, kurtosis, JB test for normality
- `volatility_analysis(bars)` — realized vol, rolling vol (multiple windows), vol-of-vol, GARCH(1,1) parameter estimation
- `correlation_matrix(symbol_bars_dict)` — cross-asset return correlation matrix over configurable windows
- `rolling_correlation(bars_a, bars_b, window)` — time-varying correlation between two assets
- `regime_detection(bars, n_regimes=2)` — Hidden Markov Model with 2-3 states (low-vol trending, high-vol mean-reverting, crisis)
  - Uses `hmmlearn` library
  - Outputs regime labels, transition matrix, per-regime statistics
- `autocorrelation_analysis(bars, max_lag)` — ACF/PACF of returns and squared returns (detect mean-reversion vs momentum, and volatility clustering)
- `tail_risk_analysis(bars)` — VaR, CVaR at multiple confidence levels, extreme value theory (GPD fit to tails)

**Technical Scanning:**
- `scan_indicators(bars, indicators)` — compute a batch of technical indicators over a bar series
  - Moving averages (SMA, EMA, WMA), RSI, MACD, Bollinger Bands, ATR, ADX, Stochastic, OBV
  - Returns a DataFrame with all indicator columns aligned to bar timestamps
- `scan_signals(bars, signal_configs)` — detect buy/sell signal events from indicator combinations
  - Signal configs define conditions, e.g.: `{"type": "crossover", "fast": "ema_10", "slow": "sma_30"}`
  - Returns timestamped signal events with strength scores
- `scan_patterns(bars)` — detect candlestick patterns (doji, hammer, engulfing, etc.)
- `support_resistance(bars, method="clustering")` — identify S/R levels using k-means clustering of price levels or pivot points
- `scan_universe(store, exchange, symbols, timeframe, scan_config)` — run scans across multiple symbols, return ranked results

#### `lib/analytics/indicators.py` (new)
Pure indicator computation functions (stateless, NumPy-based):
- `sma(values, period)`, `ema(values, period, alpha)`, `wma(values, period)`
- `rsi(closes, period)`, `macd(closes, fast, slow, signal)`
- `bollinger_bands(closes, period, std_dev)`
- `atr(highs, lows, closes, period)`, `adx(highs, lows, closes, period)`
- `stochastic(highs, lows, closes, k_period, d_period)`
- `obv(closes, volumes)`
- All functions operate on NumPy arrays for performance

#### `workflows/analyze.py` (new)
Persistra workflow for data analysis:
- `analyze_symbol` — run full statistical analysis on a single symbol
- `scan_universe` — scan all symbols in universe for technical signals
- `correlation_report` — compute cross-asset correlations
- `regime_report` — run regime detection and label historical data

#### `persistra.toml` (modify)
- Add state schema fields for analysis results

---

## Phase 4: Monte Carlo Stress Testing

### Goal
Stress-test strategies using both bootstrap resampling and Geometric Brownian Motion simulation to assess robustness.

### New Files

#### `lib/analytics/monte_carlo.py` (new)
Core simulation engine with both methods:

**Bootstrap Resampling:**
- `bootstrap_equity_paths(returns, n_simulations, path_length, block_size=1)` — resample actual strategy returns with replacement
  - Optionally use **block bootstrap** (block_size > 1) to preserve autocorrelation structure
  - Input: return series from a completed backtest
  - Output: array of shape `(n_simulations, path_length)` of simulated equity paths

**Geometric Brownian Motion:**
- `gbm_equity_paths(mu, sigma, dt, n_simulations, path_length, initial_value)` — parametric simulation
  - Estimates drift (μ) and volatility (σ) from historical returns
  - Generates synthetic paths: `S(t+dt) = S(t) * exp((μ - σ²/2)dt + σ√dt * Z)`
  - Output: same shape as bootstrap

**Analysis Functions:**
- `compute_path_statistics(paths)` — for each simulated path compute: total return, max drawdown, Sharpe, final value
- `confidence_intervals(paths, levels=[0.05, 0.25, 0.50, 0.75, 0.95])` — percentile bands across simulations at each time step
- `probability_of_ruin(paths, ruin_threshold)` — probability that equity drops below threshold
- `var_cvar_from_simulations(paths, confidence)` — VaR and CVaR from terminal values
- `expected_shortfall_over_time(paths, threshold)` — time-varying expected shortfall
- `summary_report(paths, method_name)` — consolidated dict of all statistics

#### `lib/analytics/stress_test.py` (new)
High-level stress testing orchestrator:
- `run_stress_test(backtest_results, config)` where config specifies:
  - `n_simulations` (default: 1000)
  - `methods`: list of `["bootstrap", "gbm"]`
  - `block_size` for bootstrap
  - `confidence_levels` for interval computation
  - `ruin_threshold` for P(ruin) calculation
- Runs both methods, computes all statistics, returns structured results
- Saves results to Parquet under `.persistra/stress_tests/{strategy}_{timestamp}/`
  - `bootstrap_paths.parquet` — full path matrix
  - `gbm_paths.parquet` — full path matrix
  - `statistics.json` — summary statistics for both methods

#### `workflows/stress_test.py` (new)
Persistra workflow:
- Step 1: Load backtest results (equity curve, returns)
- Step 2: Run bootstrap simulation
- Step 3: Run GBM simulation
- Step 4: Compute statistics and save

---

## Phase 5: Batch Backtesting with Parameter Sweeps

### Goal
Run batches of backtests over the same timeframe varying one or more strategy parameters, using multiprocessing for parallelism.

### New Files

#### `lib/execution/batch.py` (new)
Batch backtest orchestrator:

```python
@dataclass
class ParameterGrid:
    """Defines parameter sweep space."""
    params: dict[str, list]  # e.g. {"fast_period": [5, 10, 15], "slow_period": [20, 30, 50]}

    def combinations(self) -> list[dict]:
        """Generate all parameter combinations (Cartesian product)."""
        ...

    @property
    def total(self) -> int:
        ...
```

```python
class BatchBacktest:
    """Runs multiple backtests with varying parameters."""

    def __init__(
        self,
        strategy_class: type[Strategy],
        universe: Universe,
        start: datetime,
        end: datetime,
        base_params: dict,        # Fixed params shared across all runs
        grid: ParameterGrid,      # Params to vary
        initial_cash: Decimal = Decimal("10000"),
        n_workers: int | None = None,  # None = cpu_count()
        data_dir: Path | None = None,
    ): ...

    def run(self) -> BatchResults: ...
```

- Uses `multiprocessing.Pool` with `n_workers` processes
- Each worker runs an independent `BacktestContext` + strategy
- **Data sharing**: preload bar data once in the main process, pass via shared memory or pickle to workers (Parquet files are on disk, so each worker reads independently — Parquet is fast enough)
- Progress tracking via `multiprocessing.Value` counter
- Catches exceptions per-run; records failures separately

#### `lib/analytics/batch_results.py` (new)
Results container and comparison:

```python
@dataclass
class BatchResults:
    """Aggregated results from a batch of backtests."""
    runs: list[dict]              # Per-run: {params, metrics, equity_curve_path}
    grid: ParameterGrid
    elapsed_seconds: float

    def as_dataframe(self) -> pd.DataFrame:
        """All runs as a DataFrame with param columns + metric columns."""
        ...

    def best_by(self, metric: str, ascending: bool = False) -> dict:
        """Return the run with the best value for a metric."""
        ...

    def heatmap_data(self, param_x: str, param_y: str, metric: str) -> pd.DataFrame:
        """Pivot table for 2D heatmap visualization of metric vs two params."""
        ...

    def sensitivity(self, param: str, metric: str) -> pd.DataFrame:
        """1D sensitivity: metric vs single param (averaged over other params)."""
        ...

    def save(self, path: Path) -> None:
        """Save all results to Parquet + JSON."""
        ...

    @classmethod
    def load(cls, path: Path) -> "BatchResults": ...
```

#### `workflows/batch_backtest.py` (new)
Persistra workflow:
- Step 1: Validate data availability
- Step 2: Run batch backtest
- Step 3: Compute summary statistics, identify best params
- Step 4: Save results

#### `processes/batch_backtest.py` (new)
Process entry point for batch backtests:
- Accepts parameter grid as JSON string or inline params
- Example: `persistra process start batch_backtest -p strategy=sma_crossover -p grid='{"fast_period":[5,10,15,20],"slow_period":[20,30,40,50]}'`

---

## Phase 6: Interactive HTML Dashboard

### Goal
Build a comprehensive web dashboard using FastAPI + Plotly that provides interactive visualizations of all system data: backtests, portfolios, live data, signals, stress tests, batch results.

### Technology Stack
- **Backend**: FastAPI (async, high-performance)
- **Charts**: Plotly (via `plotly.py` for server-side figure generation)
- **Templates**: Jinja2 for HTML page structure
- **CSS**: Minimal custom CSS + a lightweight CSS framework (Pico CSS or similar, no npm required)
- **Interactivity**: Plotly's built-in zoom/pan/hover + htmx for dynamic page updates without a JS build step
- **No frontend build process** — pure server-rendered HTML with embedded Plotly JSON

### Architecture

The dashboard is a standalone FastAPI application that reads from the same Parquet data store and Persistra state. It does NOT modify any trading state — it is read-only.

```
lib/dashboard/
├── app.py              # FastAPI application factory
├── routes/
│   ├── overview.py     # Main dashboard / overview page
│   ├── backtests.py    # Backtest results browser
│   ├── batch.py        # Batch backtest results + heatmaps
│   ├── portfolio.py    # Paper/live portfolio views
│   ├── market_data.py  # Historical data explorer
│   ├── signals.py      # Strategy signal visualization
│   ├── stress_test.py  # Monte Carlo visualization
│   └── analysis.py     # Data analysis results
├── charts/
│   ├── equity.py       # Equity curve charts
│   ├── candlestick.py  # OHLCV candlestick charts
│   ├── heatmap.py      # Parameter sweep heatmaps
│   ├── distribution.py # Return distribution charts
│   ├── monte_carlo.py  # MC simulation fan charts
│   ├── correlation.py  # Correlation matrices
│   ├── signals.py      # Buy/sell signal overlay charts
│   └── common.py       # Shared chart utilities, theming
├── templates/
│   ├── base.html       # Base template with nav, footer
│   ├── overview.html
│   ├── backtest_detail.html
│   ├── batch_detail.html
│   ├── portfolio.html
│   ├── market_data.html
│   ├── signals.html
│   ├── stress_test.html
│   └── analysis.html
└── static/
    └── style.css       # Minimal custom styles
```

### Pages & Visualizations

#### Overview Page (`/`)
- System status: running processes, data freshness, latest backtest results
- Quick stats cards: total strategies, active paper/live trades, latest Sharpe
- Recent activity feed (last N fills, signals, risk events)
- Navigation to all sub-pages

#### Backtest Browser (`/backtests`)
- List of all completed backtests with key metrics (sortable table)
- Click into detail view:
  - **Equity curve** (interactive Plotly line chart with drawdown shading)
  - **Trade markers** overlaid on price candlestick chart (green triangles = buy, red = sell)
  - **Metrics table**: all performance stats
  - **Per-symbol breakdown** table
  - **Return distribution** histogram with fitted normal overlay
  - **Underwater plot** (drawdown over time)
  - **Monthly returns heatmap** (month × year grid)
  - **Rolling Sharpe** line chart (rolling window Sharpe over time)

#### Batch Backtest Results (`/batch`)
- List of batch runs
- Detail view:
  - **2D parameter heatmap** (e.g., fast_period × slow_period colored by Sharpe)
  - **1D sensitivity plots** (metric vs single parameter, other params averaged)
  - **Top-N runs table** ranked by selected metric
  - **Equity curve overlay** of top-N parameter sets on same chart
  - **Parameter distribution** of top performers

#### Portfolio View (`/portfolio`)
- Current positions table (symbol, side, qty, entry, unrealized PnL, %)
- Account summary (equity, cash, margin, daily PnL)
- Live equity curve (auto-refreshing via htmx polling)
- Recent fills table
- Position history timeline

#### Market Data Explorer (`/data`)
- Symbol selector dropdown
- **Interactive candlestick chart** with volume bars
- Timeframe selector
- Date range picker
- Technical indicator overlays (SMA, EMA, Bollinger, RSI subplot, MACD subplot)
- Data availability heatmap (which symbols/timeframes have data, date ranges)

#### Signal Viewer (`/signals`)
- Select strategy + symbol
- Candlestick chart with buy/sell signal markers
- Signal strength indicators
- Filter by signal type, date range
- Signal statistics (frequency, avg return after signal)

#### Stress Test Viewer (`/stress`)
- Select a stress test run
- **Fan chart**: median path with confidence interval bands (5th/25th/75th/95th percentiles)
- **Terminal value distribution** histogram for bootstrap and GBM side-by-side
- **Probability of ruin** vs threshold level curve
- **Max drawdown distribution** histogram
- **Statistics summary** table comparing bootstrap vs GBM results
- **Individual path spaghetti plot** (showing N random sample paths)

#### Data Analysis Viewer (`/analysis`)
- **Return distribution** with QQ plot
- **Volatility regime chart** (rolling vol with regime labels color-coded)
- **Correlation matrix heatmap** (interactive, shows value on hover)
- **Autocorrelation plots** (ACF/PACF bar charts)
- **Support/resistance levels** overlaid on price chart
- **Regime timeline** with state probabilities over time

### Dashboard Process

#### `processes/dashboard.py` (new)
Persistra daemon process that runs the FastAPI server:
```python
@process("daemon", interval="0s")  # runs once, blocks on server
def run(env, host="127.0.0.1", port=8050):
    import uvicorn
    from dashboard.app import create_app
    app = create_app(env)
    uvicorn.run(app, host=host, port=port)
```

Usage: `persistra process start dashboard -p port=8050`

---

## Phase 7: Cross-Cutting Improvements

### 7a. Exchange Abstraction Layer

Currently, exchange-specific logic is scattered. Introduce a cleaner abstraction:

#### `lib/data/exchange.py` (new)
```python
class Exchange(ABC):
    """Unified interface for exchange-specific operations."""
    name: str

    @abstractmethod
    def fetch_ohlcv(self, symbol, timeframe, start, end) -> list[Bar]: ...

    @abstractmethod
    def create_live_feed(self) -> DataFeed: ...

    @abstractmethod
    def create_broker(self) -> Broker: ...

    @abstractmethod
    def get_instruments(self) -> list[Instrument]: ...
```

Implementations: `KrakenSpotExchange`, `KrakenFuturesExchange`, `OandaExchange`

This allows `Universe.from_symbols()` to auto-resolve the correct exchange adapter and `ExecutionContext` subclasses to be exchange-agnostic.

### 7b. Result Persistence & Registry

#### `lib/data/result_store.py` (new)
Centralized storage and indexing of all results:
- Backtest results, batch results, stress test results, analysis results
- Each result gets a UUID, timestamp, and metadata (strategy name, params, universe)
- Index file (JSON or SQLite) for fast listing/querying
- Parquet files for heavy data (equity curves, paths)
- The dashboard reads from this store

### 7c. Strategy Registry

#### `lib/strategy/registry.py` (new)
```python
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {}

def register(name: str):
    def decorator(cls):
        STRATEGY_REGISTRY[name] = cls
        return cls
    return decorator

def get_strategy(name: str) -> type[Strategy]:
    return STRATEGY_REGISTRY[name]
```

All strategies use `@register("sma_crossover")` decorator. Batch backtests and the dashboard can resolve strategies by name string.

### 7d. Configuration Improvements

#### `lib/config.py` (new)
Centralized configuration loading:
- Exchange credentials from env vars (already done per-exchange, but centralize the pattern)
- Default parameters for each exchange (fee rates, tick sizes, etc.)
- Dashboard settings (port, host, theme)
- Risk defaults

### 7e. Logging & Events

#### `lib/events.py` (new)
Simple event bus for decoupled communication:
- Events: `FillEvent`, `SignalEvent`, `RiskEvent`, `EquityUpdate`
- The dashboard can subscribe to events for real-time updates
- Risk monitor can subscribe to fill events
- Stored in a ring buffer for recent history

---

## Dependency Changes

### New Dependencies (`persistra.toml`)
```toml
[dependencies]
packages = [
    # Existing
    "pandas>=2.0",
    "pyarrow>=14.0",
    "requests>=2.31",
    "numpy>=1.26",
    "websockets>=16.0",
    # New — Dashboard
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "jinja2>=3.1",
    "plotly>=5.24",
    # New — Analysis
    "scipy>=1.14",
    "hmmlearn>=0.3",
    # New — OANDA streaming
    "httpx>=0.28",       # async HTTP for OANDA streaming
]
```

---

## Implementation Order & Phasing

### Recommended sequence (each phase builds on prior):

1. **Phase 7a-7e: Cross-cutting improvements** (foundation)
   - Exchange abstraction, result store, strategy registry, config, events
   - These provide cleaner patterns that phases 1-6 build on
   - ~3-4 new files, moderate modifications

2. **Phase 3: Historical data analysis** (no exchange dependency)
   - Indicators library and data analyzer
   - Tests can run on existing stored Kraken data
   - ~3 new files

3. **Phase 4: Monte Carlo stress testing** (depends on backtest results)
   - Simulation engine and stress test orchestrator
   - Tests run on existing backtest results
   - ~2 new files

4. **Phase 5: Batch backtesting** (depends on backtest engine)
   - Parameter grid, batch runner, results container
   - Uses existing BacktestContext in parallel
   - ~3 new files

5. **Phase 1: Kraken derivatives** (parallel with phases 3-5)
   - Futures API, auth, live feed, broker, model updates
   - ~4 new files, moderate modifications to existing

6. **Phase 2: OANDA forex** (parallel with phase 1)
   - OANDA API, streaming, live feed, broker
   - ~5 new files, moderate modifications to existing

7. **Phase 6: Dashboard** (last — needs all data sources)
   - FastAPI app, routes, chart generators, templates
   - ~20 new files (but mostly thin route/chart files)
   - This is the largest phase by file count but benefits from all prior phases being complete

### Estimated File Impact
- **New files**: ~45
- **Modified files**: ~10
- **New lines of code**: ~6,000-8,000
- **Total phases**: 7 (with sub-phases)

---

## Testing Strategy

The platform currently has no test suite. This refactor introduces comprehensive testing as a first-class concern — every phase includes tests, and a retroactive suite covers the existing codebase. All tests live under `tests/` with a structure mirroring `lib/`.

### Test Infrastructure

#### `tests/conftest.py` (new)
Shared pytest fixtures used across the entire test suite:

- **`sample_instrument`** — a `BTC/USD` `Instrument` with standard Kraken tick/lot/notional sizes
- **`sample_futures_instrument`** — a `BTC-PERP` `FuturesInstrument` with leverage/margin fields
- **`sample_forex_instrument`** — a `EUR/USD` `Instrument` with OANDA pip-based sizing
- **`sample_bar`** / **`sample_bars(n)`** — factory fixtures producing `Bar` objects with realistic OHLCV data at hourly intervals
- **`sample_bar_group(symbols, n)`** — multi-symbol bar groups aligned by timestamp (for multi-symbol tests)
- **`sample_fill`** — a `Fill` with configurable side, price, quantity, fee
- **`sample_equity_curve(n, trend)`** — generates `(timestamp, Decimal)` equity curves with configurable drift and noise
- **`sample_returns(n, mu, sigma)`** — generates return series for Monte Carlo tests
- **`universe_single`** / **`universe_multi`** — `Universe` objects for single and multi-symbol tests
- **`simulated_broker`** — a pre-configured `SimulatedBroker` with standard parameters
- **`simulated_broker_margin`** — a `SimulatedBroker` with `margin_mode=True` for futures tests
- **`tmp_data_dir`** — a `tmp_path` configured as a `MarketDataStore` base directory with pre-written sample Parquet data
- **`tmp_result_store`** — a `tmp_path` configured as a `ResultStore` base directory
- **`mock_kraken_api`** — `responses` or `respx` mock for Kraken REST endpoints returning realistic JSON
- **`mock_kraken_futures_api`** — mock for Kraken Futures REST endpoints
- **`mock_oanda_api`** — mock for OANDA v20 REST endpoints

#### `pyproject.toml` or `pytest.ini` (new)
```ini
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["lib"]
markers = [
    "slow: marks tests as slow (deselect with -m 'not slow')",
    "integration: marks tests requiring external services",
    "network: marks tests that make real network calls",
]
```

#### Test dependencies added to `persistra.toml`:
```toml
[dev-dependencies]
packages = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-asyncio>=0.24",
    "respx>=0.22",         # async HTTP mocking (for OANDA streaming)
    "responses>=0.25",     # sync HTTP mocking (for Kraken REST)
    "hypothesis>=6.100",   # property-based testing
    "pytest-timeout>=2.3", # prevent hung tests
]
```

---

### Retroactive Tests for Existing Code

These tests cover the current codebase that has no test coverage. They are implemented as part of Phase 7 (cross-cutting improvements) and serve as a regression safety net for all subsequent refactor phases.

#### `tests/models/test_bar.py`
- Frozen dataclass properties: verify immutability, default `None` for `trades` and `vwap`
- Construction with all field types (str, datetime, Decimal)

#### `tests/models/test_instrument.py`
- `Instrument` frozen dataclass: verify all fields, immutability
- `FuturesInstrument` inheritance: verify subclass fields (`contract_type`, `max_leverage`, `initial_margin_rate`, `maintenance_margin_rate`, `funding_interval_hours`, `expiry`)
- Default values for futures-specific fields

#### `tests/models/test_order.py`
- `Order` mutable dataclass: verify default `id` is UUID, default status is `PENDING`
- `OrderSide`, `OrderType`, `OrderStatus`, `TimeInForce` enum values
- Metadata dict is independent per instance (no shared mutable default)

#### `tests/models/test_fill.py`
- Frozen dataclass: verify immutability
- Default `slippage` is `Decimal("0")`, default `is_maker` is `False`

#### `tests/models/test_position.py`
- `update_unrealized_pnl()` for long positions: `(current_price - entry_price) * quantity`
- `update_unrealized_pnl()` for short positions: `(entry_price - current_price) * quantity`
- `update_unrealized_pnl()` with zero quantity sets PnL to zero
- `to_dict()` serialization round-trip

#### `tests/models/test_account.py`
- `update_equity()`: sum of balances + unrealized PnL
- `to_dict()` serialization: all Decimal fields become strings

#### `tests/broker/test_simulated.py`
Core test file for the simulated broker — the engine behind both backtesting and paper trading:

**Order submission & management:**
- `submit_order()` sets status to `OPEN`, preserves order in `_orders` dict
- `cancel_order()` sets status to `CANCELLED`, removes from `_open_orders`
- `get_order()` returns correct order by ID
- `get_open_orders()` returns only open orders; filters by instrument when specified
- `get_position()` returns `None` when flat; returns `Position` when held
- `get_positions()` returns only non-zero positions

**Market order fills:**
- Fill at bar open price + slippage (buy) / - slippage (sell)
- Fee = `quantity * fill_price * fee_rate`
- Order status set to `FILLED`, `filled_quantity` and `average_fill_price` populated
- Cash balance decremented by `notional + fee` (buy) or incremented by `notional - fee` (sell)

**Limit order fills:**
- Buy limit fills when `bar.low <= order.price`; fills at limit price (no slippage)
- Sell limit fills when `bar.high >= order.price`; fills at limit price
- Does NOT fill when price is outside range
- `is_maker=True` on resulting fill

**Stop order fills:**
- Buy stop triggers when `bar.high >= stop_price`; fills at stop price + slippage
- Sell stop triggers when `bar.low <= stop_price`; fills at stop price - slippage
- Does NOT trigger when price is outside range

**Position management:**
- Opening a new position: creates `Position` with correct side, quantity, entry price
- Adding to existing position: VWAP entry price recalculation (`(old_cost + new_cost) / total_qty`)
- Partial close: reduces quantity, realized PnL computed correctly
- Full close: quantity goes to zero, realized PnL accumulated on account
- Position reversal: close long → open short in single fill, sizes and PnL correct

**Unrealized PnL & equity:**
- `process_bar()` updates unrealized PnL for matching symbol positions
- Equity = cash + sum(position_value) where position_value = `qty * entry + unrealized_pnl`
- `process_bars()` defers equity update, then calls `update_equity_all()` once

**Multi-symbol scenarios:**
- Two positions in different symbols: fills only affect matching symbol
- Equity reflects sum of all positions
- Orders for symbol A don't interact with orders for symbol B

**Edge cases:**
- Zero-quantity position returns `None` from `get_position()`
- Order with `None` price for limit type returns no fill
- Order with `None` stop_price for stop type returns no fill
- Bar queue full handling (in LiveFeed, tested separately)

#### `tests/broker/test_kraken.py`
Mock-based tests using `responses` library:

- `submit_order()`: correct REST payload construction (pair mapping, order type mapping, volume, price fields)
- `submit_order()` with limit: `price` field populated
- `submit_order()` with stop: `price` field is stop price
- `submit_order()` with stop-limit: `price` is limit, `price2` is stop
- `cancel_order()`: sends correct `txid` to Kraken
- `get_order()`: parses Kraken `QueryOrders` response, maps status correctly
- `get_open_orders()`: parses Kraken `OpenOrders` response, filters by instrument
- `get_position()`: derives position from balance response, checks correct balance keys (`XXBT`, `XETH`, etc.)
- `get_positions()`: returns all non-zero, non-USD balances as positions
- `get_account()`: parses both `Balance` and `TradeBalance` responses
- `_map_order_status()`: maps all Kraken status strings to `OrderStatus` enum
- Error handling: `KrakenAuthError` raised on API errors
- Missing credentials: `KrakenAuthError` raised when env vars not set

#### `tests/data/test_store.py`
- `write_bars()` creates correct directory structure (`{exchange}/{symbol}/{timeframe}.parquet`)
- `write_bars()` with existing file: deduplicates by timestamp, keeps latest
- `read_bars()` returns empty list for nonexistent file
- `read_bars()` with date range: filters correctly with start/end
- `read_bars()` timezone handling: naive timestamps treated as UTC
- `has_data()` returns True/False correctly
- `get_date_range()` returns min/max timestamps
- Round-trip: write bars → read bars → identical data (Decimal precision preserved)
- Schema compliance: all columns present with correct types

#### `tests/data/test_price_panel.py`
- Single symbol: `append_bar()` then `get_window()` returns correct DataFrame shape
- Multi-symbol: inner-join on timestamps filters to shared timestamps only
- `is_ready` returns `False` when any buffer is empty, `True` when all have ≥1 bar
- Lookback windowing: buffer drops oldest bars when exceeding lookback
- `latest_timestamp` returns most recent across all buffers
- Empty panel: `get_window()` returns DataFrame with correct columns, zero rows
- Decimal→float conversion: verify `Decimal("69420.50")` becomes `float` in DataFrame

#### `tests/data/test_historical.py`
- `historical_bars()` reads from `MarketDataStore` with correct exchange/symbol/timeframe
- `load_universe()` groups bars by timestamp across symbols
- `next_bar_group()` returns groups in chronological order, `None` when exhausted
- `reset()` resets both `_index` and `_timeline_index`
- `total_groups` / `remaining_bars` / `total_bars` properties

#### `tests/data/test_live.py`
Testing the WebSocket feed without a real connection:

- `_candle_to_bar()`: parses Kraken WS v2 candle dict into `Bar` with correct types
- `_candle_to_bar()` with malformed data: returns `None`, logs warning
- `_process_candle()` snapshot: caches candle, does NOT enqueue
- `_process_candle()` update with same interval_begin: updates cache, does NOT enqueue
- `_process_candle()` update with new interval_begin: enqueues previous candle as completed bar
- `_handle_message()` ignores non-ohlc channels
- `_handle_message()` ignores non-update/snapshot types
- `next_bar()` returns `None` when queue empty
- Queue full behavior: drops oldest bar, enqueues new one
- `shutdown()` sets shutdown event, clears connected state

#### `tests/data/test_kraken_api.py`
Mock-based tests for Kraken REST OHLCV:

- `fetch_ohlcv()`: correct URL construction, param mapping, bar parsing
- `fetch_ohlcv()` with `since`: timestamp conversion to Unix seconds
- `fetch_ohlcv()` with `limit`: truncates result list
- `fetch_ohlcv()` symbol mapping: `BTC/USD` → `XBTUSD`
- `fetch_ohlcv()` unknown symbol: passes through as-is
- `backfill_ohlcv()`: paginates correctly, deduplicates by timestamp
- `backfill_ohlcv()` with `end`: stops when bars exceed end time
- `backfill_ohlcv()` no progress: breaks when last timestamp doesn't advance
- Error response: raises `KrakenAPIError`

#### `tests/data/test_kraken_auth.py`
- `get_credentials()`: reads from env vars
- `get_credentials()`: raises `KrakenAuthError` when missing
- `_sign_request()`: produces correct HMAC-SHA512 signature (verified against known test vector)
- `private_request()`: sends correct headers (`API-Key`, `API-Sign`), includes nonce

#### `tests/execution/test_backtest.py`
End-to-end backtest engine tests:

- Single-symbol backtest: loads bars, processes through strategy, returns equity curve and fills
- Multi-symbol backtest: bar groups processed together, equity curve has one entry per timestamp
- Empty universe: returns `{equity_curve: [], fills: [], bars_processed: 0}`
- Equity curve starts with initial equity, ends with final equity
- Risk manager integration: orders exceeding max position size are rejected
- `fills` property returns all fills from broker

#### `tests/execution/test_paper.py`
- `warmup()`: feeds historical bars to strategy without broker processing
- `run_once()`: drains bars from feed, processes orders, returns stats dict
- `run_once()` with no bars: returns zero bars_processed, current equity
- `subscribe_all()`: delegates to LiveFeed
- Fill callback: `strategy.on_fill()` called for each fill

#### `tests/execution/test_live.py`
Mock-based (no real Kraken connection):

- `run_once()`: checks open order status via broker before processing new bars
- `run_once()`: catches and logs exceptions from broker calls (doesn't crash daemon)
- `shutdown()`: delegates to LiveFeed shutdown

#### `tests/strategy/test_sma_crossover.py`
- `universe()` returns symbols from params
- `lookback()` returns `slow_period`
- Buy signal: fast SMA crosses above slow SMA, no existing position → BUY order
- Sell signal: fast SMA crosses below slow SMA, existing position → SELL order for full position qty
- No signal: fast SMA still above (or below) slow SMA → no orders
- Warmup: not enough bars for slow SMA → no orders
- Multi-symbol: independent signals per symbol, can buy one and sell another in same bar

#### `tests/risk/test_manager.py`
- Kill switch active: rejects all orders
- Buy order within position limit: approved
- Buy order exceeding position limit: rejected
- Sell order closing position: approved (even if resulting qty is within limits)
- Sell order reversing to short: checks new short quantity against limit
- Market order (no price): skips notional check
- Limit order exceeding max notional: rejected

#### `tests/analytics/test_performance.py`
- `compute_performance()` with known equity curve: verify total return, annualized return
- Sharpe ratio: known return series with known std → verify formula
- Sortino ratio: only downside deviation in denominator
- Max drawdown: known peak-to-trough in synthetic curve
- Max drawdown duration: correct timedelta
- Calmar ratio: annualized return / max drawdown
- Trade analysis: round-trip PnL pairing (buy then sell)
- Win rate: correct fraction of profitable trades
- Profit factor: gross profit / gross loss
- Edge case: fewer than 2 equity points → `_empty_metrics()`
- Edge case: no fills → zero trade stats
- `compute_per_symbol_performance()`: correct grouping by symbol

---

### New Feature Tests

#### `tests/data/test_kraken_futures_api.py` (Phase 1)
- `fetch_ohlcv_futures()`: correct Kraken Futures URL and response parsing
- `backfill_ohlcv_futures()`: pagination and deduplication
- `fetch_funding_rate()`: parses funding rate response, returns `FundingRate` objects
- `fetch_instruments()`: returns list of available perpetual contracts
- Symbol mapping: `BTC-PERP` → `PF_XBTUSD`
- Rate limiting: respects Retry-After headers

#### `tests/data/test_kraken_futures_auth.py` (Phase 1)
- Different signing scheme from spot API
- `private_futures_request()` correct headers
- Credential validation from env vars

#### `tests/data/test_live_futures.py` (Phase 1)
- WebSocket message parsing for futures candle format
- Funding rate message handling
- `FundingRate` objects published alongside `Bar` objects

#### `tests/broker/test_kraken_futures.py` (Phase 1)
Mock-based tests:

- `submit_order()`: correct `/derivatives/api/v3/sendorder` payload
- `cancel_order()`: correct cancel endpoint
- `get_position()`: parses `/derivatives/api/v3/openpositions` response (native position tracking)
- `get_account()`: parses margin, equity, available funds
- Leverage setting: correct `/derivatives/api/v3/leveragepreferences` call

#### `tests/broker/test_simulated_margin.py` (Phase 1)
Margin-mode `SimulatedBroker` for futures:

- **Initial margin**: opening position deducts `notional / leverage` from available balance
- **Position margin tracking**: `Position.margin_used` updated correctly
- **Liquidation price**: computed from maintenance margin rate, entry price, side, leverage
- **Funding rate**: `apply_funding()` charges/credits account at 8-hour intervals
  - Long position with positive funding rate: debit
  - Short position with positive funding rate: credit
  - Verify balance and equity updated
- **PnL computation**: PnL on full notional, not margin posted
  - Long BTC-PERP entry 60000, exit 62000, qty 1, leverage 10: PnL = 2000 (not 200)
- **Margin call**: equity drops below maintenance margin → position auto-liquidated
- **Backward compatibility**: `margin_mode=False` (default) behaves identically to existing spot tests

#### `tests/data/test_oanda_api.py` (Phase 2)
Mock-based tests:

- `fetch_candles()`: correct URL (`/v3/instruments/EUR_USD/candles`), granularity mapping
- `backfill_candles()`: pagination with 5000-candle limit
- `fetch_instruments()`: parses available pairs
- Symbol format translation: `EUR/USD` → `EUR_USD`
- Granularity mapping: `"1m"` → `"M1"`, `"1h"` → `"H1"`, `"1d"` → `"D"`
- Auth header: `Authorization: Bearer {OANDA_API_TOKEN}`
- Base URL selection: practice vs live based on `OANDA_ENVIRONMENT`

#### `tests/data/test_oanda_stream.py` (Phase 2)
- Streaming JSON tick parsing: bid, ask, mid, spread
- Tick → bar aggregation: ticks within timeframe boundary produce correct OHLCV
- Bar completion: new timeframe boundary triggers completed bar emission
- Tick recording: when `record_ticks=True`, ticks written to Parquet with correct schema
- Reconnection: simulated disconnect triggers reconnect logic
- Heartbeat handling: OANDA heartbeat messages don't produce bars

#### `tests/data/test_tick_store.py` (Phase 2)
- Write tick DataFrame → read back identical data
- Daily file rotation: ticks on different dates go to separate files
- Date range query: reads only relevant daily files
- Aggregation: ticks → bars at arbitrary timeframes (1m, 5m, 1h)

#### `tests/broker/test_oanda.py` (Phase 2)
Mock-based tests:

- `submit_order()`: correct `/v3/accounts/{id}/orders` payload for market/limit/stop
- Take-profit and stop-loss attached to orders
- `get_position()`: parses OANDA position response (long/short netting)
- `get_account()`: parses account summary (balance, unrealized PnL, margin)
- Fractional pip pricing preserved

#### `tests/analytics/test_indicators.py` (Phase 3)
Property-based testing with Hypothesis for numerical correctness:

- **SMA**: `sma(values, period)` — verify against `pandas.Series.rolling().mean()` for reference
- **EMA**: `ema(values, period)` — verify first value is SMA, subsequent values follow `alpha * x + (1-alpha) * prev`
- **WMA**: `wma(values, period)` — weighted sum / weight total
- **RSI**: range is always [0, 100]; all-up series → RSI near 100; all-down → near 0
- **MACD**: `macd_line = ema(fast) - ema(slow)`, signal line = ema of macd_line
- **Bollinger Bands**: upper = SMA + k*std, lower = SMA - k*std; close always between low band and high band when k is large enough
- **ATR**: non-negative; increases with higher volatility bars
- **ADX**: range [0, 100]; trending series → high ADX; choppy series → low ADX
- **Stochastic**: %K range [0, 100]; %D is SMA of %K
- **OBV**: cumulative; direction matches close-to-close direction
- **Edge cases**: empty array → empty result; period > len → empty result; constant series → zero std/ATR

#### `tests/analytics/test_data_analyzer.py` (Phase 3)
**Statistical analysis:**

- `return_distribution()`: verify mean, std, skewness, kurtosis against `scipy.stats` for known series
- `volatility_analysis()`: realized vol matches manual `std(returns) * sqrt(periods_per_year)`
- `correlation_matrix()`: diagonal is 1.0; perfectly correlated series → 1.0; independent → near 0
- `rolling_correlation()`: output length = `len - window + 1`; values in [-1, 1]
- `regime_detection()`: with synthetic 2-regime data (low-vol + high-vol segments), detects ≥2 regimes; transition matrix rows sum to 1
- `autocorrelation_analysis()`: white noise → ACF near zero at all lags; AR(1) process → exponential decay
- `tail_risk_analysis()`: VaR at 95% < VaR at 99% (more extreme); CVaR ≤ VaR (more extreme)

**Technical scanning:**

- `scan_indicators()`: returns DataFrame with correct columns for requested indicators
- `scan_signals()`: crossover signal detected at correct timestamp in synthetic SMA-crossing data
- `scan_patterns()`: doji detected when open ≈ close and range is large
- `support_resistance()`: returns levels within price range; levels cluster near price concentrations
- `scan_universe()`: processes multiple symbols, returns results keyed by symbol

#### `tests/analytics/test_monte_carlo.py` (Phase 4)
**Bootstrap resampling:**

- Output shape: `(n_simulations, path_length)`
- All values drawn from actual return series (no synthetic values)
- Block bootstrap with `block_size=5`: consecutive returns in blocks of 5
- Reproducibility: same seed → same paths

**Geometric Brownian Motion:**

- Output shape: `(n_simulations, path_length)`
- All paths start at `initial_value`
- Mean terminal value approximately `initial_value * exp(mu * T)` (law of large numbers)
- Std of log-returns approximately `sigma * sqrt(dt)`
- Paths are always positive (log-normal property)

**Analysis functions:**

- `compute_path_statistics()`: returns dict per path with `total_return`, `max_drawdown`, `sharpe`, `final_value`
- `confidence_intervals()`: 50th percentile is median; 5th < 25th < 50th < 75th < 95th at every timestep
- `probability_of_ruin()`: 0.0 when threshold is far below all terminal values; 1.0 when above all
- `var_cvar_from_simulations()`: CVaR ≤ VaR; both negative for loss-making distributions

#### `tests/analytics/test_stress_test.py` (Phase 4)
- `run_stress_test()` with both methods: returns results for "bootstrap" and "gbm"
- Result saving: Parquet files and `statistics.json` written to correct directory
- Config validation: raises on invalid `n_simulations` (<1), invalid `methods`

#### `tests/execution/test_batch.py` (Phase 5)
**ParameterGrid:**

- `combinations()`: Cartesian product of all param lists
  - `{"a": [1,2], "b": [3,4]}` → `[{a:1,b:3}, {a:1,b:4}, {a:2,b:3}, {a:2,b:4}]`
- `total`: product of all list lengths
- Single parameter: `{"a": [1,2,3]}` → 3 combinations
- Empty grid: 0 combinations

**BatchBacktest:**

- Runs correct number of backtests (= grid total)
- Each run uses correct parameter combination
- Results contain per-run metrics and params
- Failed runs recorded separately (don't crash batch)
- `n_workers=1`: runs sequentially (easier to debug)
- Progress tracking: counter increments correctly

**BatchResults:**

- `as_dataframe()`: one row per run, columns = params + metrics
- `best_by("sharpe_ratio")`: returns run with highest Sharpe
- `heatmap_data(param_x, param_y, metric)`: correct pivot table shape
- `sensitivity(param, metric)`: correct averaging over other params
- `save()` / `load()` round-trip: identical data

#### `tests/dashboard/test_app.py` (Phase 6)
Using FastAPI `TestClient`:

- App creation: `create_app()` returns FastAPI instance
- Static files served correctly

#### `tests/dashboard/test_routes.py` (Phase 6)
Route smoke tests (every route returns 200 or valid error):

- `GET /` → 200, contains "Overview" or similar title
- `GET /backtests` → 200
- `GET /backtests/{id}` with valid/invalid ID → 200/404
- `GET /batch` → 200
- `GET /batch/{id}` → 200/404
- `GET /portfolio` → 200
- `GET /data` → 200
- `GET /data?symbol=BTC/USD&timeframe=1h` → 200, response contains chart data
- `GET /signals` → 200
- `GET /stress` → 200
- `GET /stress/{id}` → 200/404
- `GET /analysis` → 200

#### `tests/dashboard/test_charts.py` (Phase 6)
Chart generation tests (verify Plotly figure structure):

- `equity_chart()`: returns Plotly figure with correct trace count, x/y data
- `candlestick_chart()`: contains OHLC trace and volume bar trace
- `heatmap_chart()`: contains heatmap trace with correct z-values
- `distribution_chart()`: contains histogram trace
- `monte_carlo_fan_chart()`: contains correct number of percentile traces
- `correlation_chart()`: heatmap with correct labels
- `signal_chart()`: candlestick with buy/sell marker overlays
- All charts: valid JSON serialization (no Decimal or datetime serialization errors)

---

### Cross-Cutting Feature Tests

#### `tests/test_exchange.py` (Phase 7a)
- `KrakenSpotExchange.fetch_ohlcv()` delegates to `kraken_api.fetch_ohlcv()`
- `KrakenFuturesExchange.create_broker()` returns `KrakenFuturesBroker`
- `OandaExchange.create_live_feed()` returns `LiveOandaFeed`
- Factory resolution: exchange name string → correct `Exchange` subclass

#### `tests/test_result_store.py` (Phase 7b)
- Save backtest result: UUID assigned, metadata stored, Parquet written
- List results: returns all results sorted by timestamp
- Load result by UUID: retrieves correct data
- Query by strategy name: filters correctly
- Query by date range: filters correctly

#### `tests/test_strategy_registry.py` (Phase 7c)
- `@register("name")` decorator adds to `STRATEGY_REGISTRY`
- `get_strategy("name")` returns correct class
- `get_strategy("unknown")` raises `KeyError`
- All registered strategies are valid `Strategy` subclasses

#### `tests/test_config.py` (Phase 7d)
- Default configuration values for each exchange
- Environment variable override
- Missing required env var: clear error message

#### `tests/test_events.py` (Phase 7e)
- Publish event → subscriber receives it
- Multiple subscribers: all receive
- Ring buffer: oldest events evicted when full
- Event types: `FillEvent`, `SignalEvent`, `RiskEvent`, `EquityUpdate`

---

### Integration Tests

These tests verify correct interaction between multiple components. Marked with `@pytest.mark.slow` for optional exclusion from fast CI runs.

#### `tests/integration/test_backtest_end_to_end.py`
Full backtest pipeline with real (but local) data:

- Write synthetic bars to Parquet → create `BacktestContext` → run SMA crossover → verify performance metrics are reasonable (non-zero trades, return within [-1, +inf])
- Multi-symbol: two symbols, verify per-symbol fill breakdown
- Risk rejection: set `max_position_size` very low, verify some orders rejected

#### `tests/integration/test_batch_end_to_end.py`
- Grid of 4 parameter combinations → 4 completed runs
- Best-by-Sharpe selects correct run
- Results survive save/load round-trip

#### `tests/integration/test_stress_test_end_to_end.py`
- Run backtest → feed results into stress test → verify both bootstrap and GBM produce valid paths
- Statistics are within reasonable bounds

#### `tests/integration/test_data_pipeline.py`
- Write bars to store → read back → feed into `HistoricalFeed` → replay through `BacktestContext` → verify bar count matches
- Tick store: write ticks → aggregate to bars → bars match expected OHLCV

#### `tests/integration/test_dashboard_with_data.py`
- Populate result store with backtest + batch + stress test results
- Start `TestClient` → navigate to each page → verify charts contain data (non-empty traces)

---

### Property-Based Tests (Hypothesis)

Used where numerical correctness is critical and edge cases are hard to enumerate:

#### In `tests/analytics/test_indicators.py`:
- `@given(st.lists(st.floats(min_value=0.01, max_value=1e6), min_size=50))` — SMA of constant series equals that constant
- EMA converges to constant for constant input
- RSI: inject all-positive returns → RSI > 50; all-negative → RSI < 50
- Bollinger: close never outside ±10σ bands

#### In `tests/analytics/test_monte_carlo.py`:
- `@given(n_sim=st.integers(1, 100), path_len=st.integers(10, 500))` — output shape always `(n_sim, path_len)`
- Bootstrap paths only contain values from original returns
- GBM paths always positive

#### In `tests/broker/test_simulated.py`:
- `@given(price=st.decimals(min_value=0.01, max_value=1e6))` — slippage always increases buy price, decreases sell price
- Cash + position value = equity (accounting identity)

---

### Test Organization Summary

```
tests/
├── conftest.py                          # Shared fixtures
├── models/
│   ├── test_bar.py
│   ├── test_instrument.py
│   ├── test_order.py
│   ├── test_fill.py
│   ├── test_position.py
│   └── test_account.py
├── broker/
│   ├── test_simulated.py                # ~40 tests
│   ├── test_simulated_margin.py         # ~15 tests (Phase 1)
│   ├── test_kraken.py                   # ~15 tests
│   ├── test_kraken_futures.py           # ~10 tests (Phase 1)
│   └── test_oanda.py                    # ~10 tests (Phase 2)
├── data/
│   ├── test_store.py                    # ~10 tests
│   ├── test_price_panel.py              # ~10 tests
│   ├── test_historical.py              # ~8 tests
│   ├── test_live.py                     # ~12 tests
│   ├── test_kraken_api.py               # ~10 tests
│   ├── test_kraken_auth.py              # ~5 tests
│   ├── test_kraken_futures_api.py       # ~8 tests (Phase 1)
│   ├── test_kraken_futures_auth.py      # ~4 tests (Phase 1)
│   ├── test_live_futures.py             # ~8 tests (Phase 1)
│   ├── test_oanda_api.py               # ~10 tests (Phase 2)
│   ├── test_oanda_stream.py            # ~10 tests (Phase 2)
│   └── test_tick_store.py              # ~6 tests (Phase 2)
├── execution/
│   ├── test_backtest.py                 # ~8 tests
│   ├── test_paper.py                    # ~6 tests
│   ├── test_live.py                     # ~5 tests
│   └── test_batch.py                    # ~15 tests (Phase 5)
├── strategy/
│   └── test_sma_crossover.py            # ~8 tests
├── risk/
│   └── test_manager.py                  # ~8 tests
├── analytics/
│   ├── test_performance.py              # ~15 tests
│   ├── test_indicators.py               # ~30 tests (Phase 3)
│   ├── test_data_analyzer.py            # ~20 tests (Phase 3)
│   ├── test_monte_carlo.py              # ~15 tests (Phase 4)
│   └── test_stress_test.py             # ~5 tests (Phase 4)
├── dashboard/
│   ├── test_app.py                      # ~3 tests (Phase 6)
│   ├── test_routes.py                   # ~15 tests (Phase 6)
│   └── test_charts.py                   # ~10 tests (Phase 6)
├── integration/
│   ├── test_backtest_end_to_end.py      # ~5 tests
│   ├── test_batch_end_to_end.py         # ~3 tests
│   ├── test_stress_test_end_to_end.py   # ~3 tests
│   ├── test_data_pipeline.py            # ~4 tests
│   └── test_dashboard_with_data.py      # ~3 tests
├── test_exchange.py                     # ~5 tests (Phase 7a)
├── test_result_store.py                 # ~6 tests (Phase 7b)
├── test_strategy_registry.py            # ~4 tests (Phase 7c)
├── test_config.py                       # ~4 tests (Phase 7d)
└── test_events.py                       # ~5 tests (Phase 7e)
```

**Estimated total: ~380 tests** (~130 retroactive for existing code, ~250 for new features)

---

## Documentation Suite

The existing documentation (`docs/backtesting.md`, `docs/paper-trading.md`, `docs/live-trading.md`) covers the current Kraken spot workflow well. The refactor requires a comprehensive documentation overhaul: updating existing docs for multi-exchange support, and adding new docs for every major feature. All docs follow the established patterns: overview → quick start → detailed explanation → parameters → examples → troubleshooting.

### Updated Existing Documentation

#### `docs/backtesting.md` (update)
Expand to cover all exchanges and features:

- **Multi-exchange quick start**: examples for Kraken spot, Kraken futures, and OANDA forex backtests
- **Futures backtesting section**: explain margin mode, leverage, funding rate simulation, liquidation behavior
- **Forex backtesting section**: explain spread simulation, pip-based pricing, weekend gap handling
- **Link to batch backtesting**: cross-reference for parameter sweeps
- **Link to stress testing**: cross-reference for Monte Carlo follow-up
- **Updated data storage section**: show new directory layout with `kraken_futures/` and `oanda/` subdirectories
- **Strategy parameter tables**: generic (not SMA-specific), since batch testing and the registry make strategies pluggable

#### `docs/paper-trading.md` (update)
- **OANDA paper trading section**: explain that OANDA paper trading uses `SimulatedBroker` with `LiveOandaFeed` (not OANDA's practice account), including spread simulation, tick recording, streaming reconnection
- **Futures paper trading section**: explain margin-mode `SimulatedBroker` with `LiveFuturesFeed`, funding rate simulation in real-time
- **Updated architecture diagram**: show exchange-agnostic flow (Exchange → DataFeed → PricePanel → Strategy → SimulatedBroker)
- **Updated monitoring section**: include dashboard link for visual monitoring

#### `docs/live-trading.md` (update)
- **OANDA live trading section**: OANDA API credentials setup (`OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`, `OANDA_ENVIRONMENT`), OANDA-specific order types (trailing stop), position netting behavior
- **Kraken futures live trading section**: Kraken Futures API credentials (`KRAKEN_FUTURES_API_KEY`, `KRAKEN_FUTURES_API_SECRET`), leverage configuration, margin requirements, funding rate charges
- **Updated checklist**: multi-exchange checklist (separate sections for each exchange)
- **Updated differences table**: paper vs live for each exchange

### New Documentation

#### `docs/getting-started.md` (new)
Top-level onboarding guide for new users:

- **What this platform does**: one-paragraph summary
- **Supported exchanges and asset classes**: table (Kraken spot, Kraken futures, OANDA forex)
- **Installation**: `persistra` setup, dependencies, Python version
- **First backtest in 3 commands**: quickest path to seeing results
- **Directory structure**: explain `lib/`, `processes/`, `workflows/`, `docs/`, `.persistra/`
- **Configuration**: environment variables overview (which ones needed for what)
- **Execution modes**: brief explanation of backtest → paper → live progression
- **Next steps**: links to each guide

#### `docs/architecture.md` (new)
Technical architecture reference for contributors and power users:

- **System overview diagram**: full component diagram showing all ABCs, implementations, and data flow
- **ABC layer**: `DataFeed`, `Broker`, `ExecutionContext`, `Strategy`, `Exchange` — what each abstracts, when to subclass
- **Data flow**: bar lifecycle from API/WebSocket → `DataFeed` → `PricePanel` → `Strategy.on_bar()` → `Order` → `Broker` → `Fill`
- **Execution contexts**: how `BacktestContext`, `PaperContext`, `LiveContext` compose feeds, brokers, and risk managers
- **Exchange abstraction**: how `Exchange` unifies per-exchange feed/broker/instrument creation
- **Data storage**: `MarketDataStore` layout, `TickStore` layout, `ResultStore` layout, `ParquetStateStore` for DataFrames
- **State management**: Persistra state namespaces (`backtest.*`, `paper.*`, `live.*`, `risk.*`, `strategy.*`, `data.*`)
- **Process model**: Persistra jobs vs daemons, module-level state persistence for daemons
- **Workflow model**: DAG construction, step dependencies, function nodes vs process nodes
- **Event system**: event bus, event types, subscriber pattern

#### `docs/strategies.md` (new)
Guide to writing custom strategies:

- **Strategy ABC contract**: `on_bar()`, `universe()`, `lookback()`, `on_fill()`, `on_stop()`
- **PricePanel DataFrame format**: MultiIndex `(timestamp, symbol)`, column names, Decimal→float conversion, inner-join behavior
- **Accessing broker state**: `self.ctx.get_broker().get_position()`, `get_account()`, `get_open_orders()`
- **Order construction**: `Order` fields, `OrderSide`, `OrderType`, `TimeInForce`
- **Risk manager interaction**: how orders are checked before submission, what causes rejection
- **Strategy registration**: `@register("my_strategy")` decorator for batch testing and dashboard integration
- **Parameters**: using `self.params` dict, type conversion from string process args
- **Multi-symbol strategies**: iterating over symbols in the panel, cross-symbol signals
- **Futures strategies**: checking `FuturesInstrument` fields, leverage-aware sizing, funding rate awareness
- **Forex strategies**: pip-based calculations, session-aware logic, spread considerations
- **Example strategies**: beyond SMA crossover:
  - Mean reversion (Bollinger band bounce)
  - Momentum (RSI + trend filter)
  - Pairs trading (correlation-based, two symbols)
  - Futures basis trade (spot-perp spread)
- **Testing your strategy**: how to write a unit test using `conftest.py` fixtures

#### `docs/data-management.md` (new)
Comprehensive guide to market data:

- **Data sources**: Kraken REST (spot OHLCV), Kraken Futures REST (perp OHLCV + funding rates), OANDA REST (forex candles), OANDA streaming (tick data)
- **Ingestion**: `data_ingestor` process for each exchange, incremental updates, backfill parameters
- **Storage layout**: full directory tree under `.persistra/market_data/` and `.persistra/tick_data/`
- **Parquet schema**: column types, timestamp handling, Decimal precision
- **Querying stored data**: using `MarketDataStore.read_bars()` and `TickStore` programmatically
- **Tick data**: recording, daily rotation, aggregation to arbitrary timeframes
- **Data quality**: gap detection (especially forex weekends), duplicate handling, timezone normalization
- **Data availability matrix**: how to check what data is available via state and `has_data()`

#### `docs/batch-backtesting.md` (new)
Guide to parameter sweep backtesting:

- **Quick start**: run a 4×4 grid in one command
- **Parameter grid specification**: JSON format, Cartesian product behavior
- **Parallel execution**: `n_workers`, CPU utilization, memory considerations
- **Results**: `BatchResults` API, `as_dataframe()`, `best_by()`, `heatmap_data()`
- **Process entry point**: `processes/batch_backtest.py` parameters
- **Workflow entry point**: `workflows/batch_backtest.py` step sequence
- **Interpreting results**: what Sharpe > 1.0 means, overfitting warnings, out-of-sample validation advice
- **Visualization**: link to dashboard heatmap and sensitivity plot pages
- **Example**: SMA crossover grid over `fast_period=[5,10,15,20,25]` × `slow_period=[20,30,40,50,60]` across `BTC/USD,ETH/USD`

#### `docs/stress-testing.md` (new)
Guide to Monte Carlo stress testing:

- **Why stress test**: limitations of single backtest, uncertainty quantification
- **Quick start**: run stress test on latest backtest results
- **Bootstrap method**: what it is, when to use it, `block_size` parameter for autocorrelation
- **GBM method**: what it is, assumptions (log-normal returns), when it breaks down
- **Configuration**: `n_simulations`, `confidence_levels`, `ruin_threshold`
- **Interpreting results**:
  - Fan chart: what confidence bands mean
  - Probability of ruin: acceptable thresholds
  - VaR/CVaR: what they measure, regulatory context
  - Comparing bootstrap vs GBM: which to trust when they disagree
- **Result storage**: Parquet paths, JSON statistics
- **Visualization**: link to dashboard stress test page
- **Limitations**: bootstrap assumes stationarity, GBM assumes normality, neither captures regime changes

#### `docs/data-analysis.md` (new)
Guide to historical data analysis without backtesting:

- **Quick start**: run full analysis on a symbol
- **Statistical analysis**:
  - Return distributions: interpreting skewness, kurtosis, normality tests
  - Volatility: realized vs implied, rolling windows, GARCH interpretation
  - Regime detection: what HMM states mean, transition matrix interpretation
  - Correlation: cross-asset diversification analysis, rolling correlation for regime awareness
  - Tail risk: VaR/CVaR interpretation, extreme value theory
  - Autocorrelation: mean-reversion (negative ACF) vs momentum (positive ACF) signals
- **Technical scanning**:
  - Available indicators and their parameters
  - Signal detection configuration
  - Candlestick pattern recognition
  - Support/resistance level identification
  - Universe scanning: rank symbols by signal strength
- **Workflow entry points**: `workflows/analyze.py` tasks
- **Visualization**: link to dashboard analysis page

#### `docs/dashboard.md` (new)
Guide to the interactive web dashboard:

- **Quick start**: `persistra process start dashboard -p port=8050`, open `http://localhost:8050`
- **Pages overview**: screenshot-style descriptions of each page with navigation instructions
- **Overview page**: system status, quick stats, activity feed
- **Backtest browser**: how to navigate results, what each chart shows, interactive features (zoom, hover, pan)
- **Batch results**: reading heatmaps, interpreting sensitivity plots, comparing parameter sets
- **Portfolio view**: understanding live/paper positions, equity tracking, auto-refresh
- **Market data explorer**: selecting symbols/timeframes, adding indicator overlays, date range selection
- **Signal viewer**: overlaying strategy signals on price charts, filtering, signal statistics
- **Stress test viewer**: reading fan charts, comparing methods, interpreting statistics
- **Data analysis viewer**: navigating statistical reports, reading correlation matrices
- **Configuration**: host, port, theme options
- **Troubleshooting**: port conflicts, no data available, chart rendering issues

#### `docs/forex-trading.md` (new)
OANDA forex-specific guide:

- **OANDA account setup**: creating an account, practice vs live, API token generation
- **Environment variables**: `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`, `OANDA_ENVIRONMENT`
- **Supported pairs**: major, minor, and exotic pairs with pip values
- **Forex-specific concepts**: pips, lots (standard/mini/micro), spread, leverage, margin, swap/rollover
- **Data ingestion**: OANDA candle timeframes, streaming tick data, tick recording
- **Backtesting forex**: spread simulation, weekend gap handling, session-aware strategies
- **Paper trading forex**: `SimulatedBroker` with spread simulation (not OANDA practice account)
- **Live trading forex**: OANDA v20 order types, position netting, order fill policies
- **Risk considerations**: leverage risk, gap risk, liquidity differences across sessions
- **Example**: EUR/USD SMA crossover with forex-appropriate parameters

#### `docs/futures-trading.md` (new)
Kraken perpetual futures-specific guide:

- **Kraken Futures account setup**: separate from Kraken spot, API key generation
- **Environment variables**: `KRAKEN_FUTURES_API_KEY`, `KRAKEN_FUTURES_API_SECRET`
- **Supported contracts**: BTC-PERP, ETH-PERP, SOL-PERP, etc.
- **Futures-specific concepts**: perpetual swaps, funding rate mechanism, mark price vs index price, margin (initial/maintenance), leverage, liquidation
- **Data ingestion**: futures OHLCV, funding rate history
- **Backtesting futures**: margin simulation, funding rate charges, liquidation simulation
- **Paper trading futures**: `SimulatedBroker(margin_mode=True)` with live futures feed
- **Live trading futures**: order types, leverage selection, position management
- **Risk considerations**: liquidation risk, funding rate drag, basis risk
- **Example**: BTC-PERP momentum strategy with 5x leverage

#### `docs/configuration-reference.md` (new)
Comprehensive reference for all configuration:

- **Environment variables table**: every env var, which exchange/feature it's for, required vs optional
  - `KRAKEN_API_KEY`, `KRAKEN_API_SECRET`
  - `KRAKEN_FUTURES_API_KEY`, `KRAKEN_FUTURES_API_SECRET`
  - `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`, `OANDA_ENVIRONMENT`
- **Persistra state keys**: every state namespace and key with type, default, and description
  - `backtest.*`, `paper.*`, `live.*`, `risk.*`, `strategy.*`, `data.*`
- **Process parameters**: every process with its full parameter table
- **Workflow parameters**: every workflow with its state-based configuration
- **Default values table**: fee rates, slippage, position limits per exchange
- **Simulated broker configuration**: `fee_rate`, `slippage_pct`, `spread_pips`, `margin_mode`, `leverage`

#### `docs/testing.md` (new)
Guide to running and writing tests:

- **Running tests**: `pytest`, `pytest -m "not slow"`, `pytest --cov=lib`
- **Test structure**: directory layout, naming conventions
- **Fixtures**: what's available in `conftest.py`, how to use them
- **Writing new tests**: patterns for mock-based exchange tests, property-based indicator tests, integration tests
- **Coverage goals**: minimum coverage targets per module
- **CI integration**: how tests fit into CI/CD pipeline (if applicable)

### Documentation Structure Summary

```
docs/
├── getting-started.md          # New — onboarding entry point
├── architecture.md             # New — technical architecture reference
├── configuration-reference.md  # New — all config in one place
├── strategies.md               # New — writing custom strategies
├── data-management.md          # New — data ingestion, storage, querying
├── backtesting.md              # Updated — multi-exchange, links to batch/stress
├── batch-backtesting.md        # New — parameter sweep guide
├── stress-testing.md           # New — Monte Carlo guide
├── data-analysis.md            # New — statistical analysis + scanning guide
├── paper-trading.md            # Updated — multi-exchange paper trading
├── live-trading.md             # Updated — multi-exchange live trading
├── forex-trading.md            # New — OANDA-specific guide
├── futures-trading.md          # New — Kraken Futures-specific guide
├── dashboard.md                # New — web dashboard guide
├── testing.md                  # New — running and writing tests
└── refactor-plan.md            # This planning document
```

**3 updated docs, 12 new docs, ~15 total (excluding this plan)**

---

## Risk & Considerations

1. **API rate limits**: Both Kraken Futures and OANDA have rate limits. All API clients should implement rate limiting (sleep between requests for backfill, respect Retry-After headers).

2. **Data consistency**: Forex markets close on weekends; the bar timeline will have gaps. The `PricePanel` and `HistoricalFeed` should handle this gracefully.

3. **Timezone handling**: Forex operates in different sessions (Tokyo, London, New York). All timestamps remain UTC internally, but the dashboard should offer timezone display options.

4. **Decimal precision**: Forex prices need 5 decimal places (for JPY pairs: 3). The existing `Decimal` usage handles this correctly.

5. **Memory for batch backtests**: With large parameter grids (e.g., 100+ combinations), memory usage could be significant. Each worker should only return summary metrics + equity curve file path, not full in-memory data.

6. **Dashboard security**: The dashboard is local-only by default (`127.0.0.1`). If exposed on a network, authentication should be added (out of scope for initial implementation, but the plan accommodates it).
