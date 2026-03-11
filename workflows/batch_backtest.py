"""Batch backtest workflow — parameter sweeps with multiprocessing."""

import json
import logging
import sys
from pathlib import Path

from persistra import Workflow

log = logging.getLogger(__name__)


def _ensure_lib_path(env):
    lib_path = str(Path(env.path) / "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def validate_data(env):
    """Validate data availability for all symbols."""
    _ensure_lib_path(env)
    from data.store import MarketDataStore

    data_dir = Path(env.path) / ".persistra" / "market_data"
    store = MarketDataStore(data_dir)

    symbols_str = env.state.get("batch_symbols", "BTC/USD")
    symbol_list = [s.strip() for s in symbols_str.split(",")]
    timeframe = env.state.get("batch_timeframe", "1h")
    exchange = env.state.get("batch_exchange", "kraken")

    for symbol in symbol_list:
        if not store.has_data(exchange, symbol, timeframe):
            raise RuntimeError(
                f"No data for {symbol} {timeframe} on {exchange}. "
                "Run data_ingestor first."
            )
    log.info("Data validated for %s", symbols_str)
    return {"symbols": symbol_list, "timeframe": timeframe}


def run_batch(env, **kwargs):
    """Run the batch backtest."""
    _ensure_lib_path(env)
    from datetime import datetime, timezone
    from decimal import Decimal

    from data.universe import Universe
    from execution.batch import BatchBacktest, ParameterGrid
    from strategy.registry import get_strategy

    strategy_name = env.state.get("batch_strategy", "sma_crossover")
    strategy_class = get_strategy(strategy_name)

    symbols_str = env.state.get("batch_symbols", "BTC/USD")
    symbol_list = [s.strip() for s in symbols_str.split(",")]
    timeframe = env.state.get("batch_timeframe", "1h")

    universe = Universe.from_symbols(symbol_list, timeframe)

    grid_json = env.state.get("batch_grid", '{"fast_period": [5, 10, 15], "slow_period": [20, 30, 50]}')
    if isinstance(grid_json, str):
        grid_params = json.loads(grid_json)
    else:
        grid_params = grid_json

    grid = ParameterGrid(params=grid_params)

    start_str = env.state.get("batch_start", "")
    end_str = env.state.get("batch_end", "")
    start = datetime.fromisoformat(start_str) if start_str else datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_str) if end_str else datetime.now(timezone.utc)

    n_workers = int(env.state.get("batch_workers", 0)) or None

    batch = BatchBacktest(
        strategy_class=strategy_class,
        universe=universe,
        start=start,
        end=end,
        base_params={"symbols": symbol_list, "quantity": "0.01"},
        grid=grid,
        initial_cash=Decimal(env.state.get("batch_initial_cash", "10000")),
        n_workers=n_workers,
        data_dir=Path(env.path) / ".persistra" / "market_data",
    )

    results = batch.run()

    # Save results
    result_dir = Path(env.path) / ".persistra" / "batch_results" / strategy_name
    results.save(result_dir)

    # Save summary to state
    ns = env.state.ns("batch")
    best = results.best_by("sharpe_ratio")
    if best:
        ns.set("best_params", best["params"])
        ns.set("best_metrics", best["metrics"])

    ns.set("total_runs", len(results.runs))
    ns.set("successful_runs", results.n_successful)
    ns.set("elapsed_seconds", results.elapsed_seconds)

    log.info("=== Batch Backtest Results ===")
    log.info("Total runs: %d (%d successful)", len(results.runs), results.n_successful)
    log.info("Elapsed: %.1fs", results.elapsed_seconds)
    if best:
        log.info("Best params: %s", best["params"])
        log.info("Best Sharpe: %.4f", best["metrics"].get("sharpe_ratio", 0))

    return results


def build(env) -> Workflow:
    """Build the batch backtest workflow DAG."""
    w = Workflow("batch_backtest")
    w.add("validate_data", validate_data)
    w.add("run_batch", run_batch, depends_on=["validate_data"])
    return w
