# Web Dashboard

The web dashboard provides an interactive interface for viewing backtest results, batch sweeps, stress tests, market data, portfolio positions, and analysis results. It runs as a FastAPI web application served by uvicorn.

## Starting the Dashboard

The dashboard runs as a Persistra daemon process:

```bash
persistra process start dashboard -p host=127.0.0.1 -p port=8050
```

Then open `http://localhost:8050` in your browser.

**Process parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `host` | `127.0.0.1` | Bind address. Use `0.0.0.0` to accept connections from other machines. |
| `port` | `8050` | HTTP port |

**Requirements:** The dashboard requires `fastapi`, `jinja2`, and `uvicorn`. Install with:

```bash
pip install fastapi[all] jinja2 uvicorn
```

The dashboard process (`processes/dashboard.py`) adds the project's `lib/` directory to `sys.path`, creates the FastAPI application via `create_app()`, and starts uvicorn. The data directory is set to `.persistra/market_data` within the project root.

API documentation is available at `/api/docs` (Swagger UI).

## Pages

### Overview Page

**Route:** `/`

The landing page shows a system-level summary:

- **Total backtests**: Count of stored backtest results.
- **Total batch runs**: Count of completed batch parameter sweeps.
- **Total stress tests**: Count of stress test results.
- **Recent results**: The 5 most recent results across all types, sorted by timestamp.
- **Data directory status**: Whether market data has been ingested.

This page gives a quick health check of your system and links to detailed views.

### Backtest Browser

**Route:** `/backtests`

Lists all completed backtest results loaded from the result store. Click a result to open the detail view.

**Detail view** (`/backtests/{result_id}`):
- Full performance metrics from the backtest.
- Interactive equity curve chart (rendered from stored equity curve data).
- Charts support zoom, hover tooltips, and pan.

### Batch Results

**Route:** `/batch`

Lists all completed batch backtest runs.

**Detail view** (`/batch/{result_id}`):
- Batch metadata (total runs, successful runs, elapsed time, grid parameters).
- Interactive heatmap showing a performance metric (e.g., Sharpe ratio) across the 2D parameter grid.
- The heatmap is rendered from stored heatmap data and helps identify optimal parameter regions and sensitivity.

### Portfolio View

**Route:** `/portfolio`

Displays current portfolio state for paper and live trading:

- **Positions table**: Open positions with instrument, side, quantity, entry price, and unrealized PnL. Loaded from `{data_dir}/state/positions.parquet`.
- **Account summary**: Balance, equity, margin used, margin available. Loaded from `{data_dir}/state/account.json`.

This page reads persisted state files, so it reflects the last saved snapshot rather than real-time values.

### Market Data Explorer

**Route:** `/data`

Browse and inspect stored market data:

- **Symbol browser**: Scans the market data directory to discover all available exchange/symbol/timeframe combinations. The directory structure is `{data_dir}/market/{exchange}/{symbol}/{timeframe}.parquet`.
- **Data summary**: Select an exchange, symbol, and timeframe to see the available date range (start and end timestamps).

Use query parameters to pre-select: `/data?exchange=kraken&symbol=BTC/USD&timeframe=1h`.

### Signal Viewer

**Route:** `/signals`

Displays detected trading signals:

- Loads signals from the result store (entries with type `"signal"`).
- Falls back to reading `{data_dir}/state/signals.json` if no result store entries exist.
- Shows up to 50 most recent signals with their type, direction, strength, and timestamp.

### Stress Test Viewer

**Route:** `/stress`

Lists all completed stress test results.

**Detail view** (`/stress/{result_id}`):
- Summary statistics for each simulation method (bootstrap, GBM).
- Fan chart visualization showing confidence bands across simulated paths.
- Key metrics: mean return, VaR, CVaR, probability of ruin.

### Data Analysis Viewer

**Route:** `/analysis`

Displays results from data analysis runs:

- Lists all analysis results from the result store (entries with type `"analysis"`).
- Statistical reports, correlation matrices, and scanning results.

## Configuration

The dashboard is configured through process parameters and the `create_app()` factory function:

```python
from dashboard.app import create_app

app = create_app(env=env, data_dir=Path("/path/to/data"))
```

The `data_dir` parameter determines where the dashboard looks for results, market data, and state files. If not provided, it defaults to `{env.data_dir}` or `{cwd}/data`.

The application title is "Trader Dashboard". Static files are served from `lib/dashboard/static/` (if the directory exists), and HTML templates are loaded from `lib/dashboard/templates/`.

### Route Modules

The dashboard is organized into route modules under `lib/dashboard/routes/`:

| Module | Prefix | Description |
|--------|--------|-------------|
| `overview.py` | `/` | System overview and stats |
| `backtests.py` | `/backtests` | Backtest result browser |
| `batch.py` | `/batch` | Batch sweep results |
| `portfolio.py` | `/portfolio` | Positions and account |
| `market_data.py` | `/data` | Market data explorer |
| `signals.py` | `/signals` | Signal viewer |
| `stress_test.py` | `/stress` | Stress test results |
| `analysis.py` | `/analysis` | Data analysis results |

## Troubleshooting

- **Port already in use**: Another process is using the port. Either stop it or use a different port: `-p port=8051`.
- **"No results found"**: Results are loaded from the result store at `{data_dir}/results/`. Make sure you have run backtests, batch tests, or analyses and that results were saved.
- **Import errors**: Ensure `fastapi`, `jinja2`, and `uvicorn` are installed. The dashboard will raise an `ImportError` with installation instructions if these are missing.
- **Empty market data explorer**: Market data must be ingested first. Run the data ingestor process to populate `.persistra/market_data/`.
