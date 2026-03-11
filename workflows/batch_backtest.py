"""Batch backtest workflow — parameter sweeps with multiprocessing."""

import json
import logging
from pathlib import Path

from persistra import Workflow

from _common import ensure_lib_path

log = logging.getLogger(__name__)


def build(env) -> Workflow:
    """Build the batch backtest workflow DAG."""
    wf = env.state.ns("wf.batch_backtest")
    strategy_name = wf.get("strategy", "sma_crossover")
    symbols = wf.get("symbols", "BTC/USD")
    timeframe = wf.get("timeframe", "1h")
    exchange = wf.get("exchange", "kraken")
    grid_json = wf.get("grid", '{"fast_period": [5, 10, 15], "slow_period": [20, 30, 50]}')
    start_str = wf.get("start", "")
    end_str = wf.get("end", "")
    n_workers = int(wf.get("workers", 0)) or None
    initial_cash = wf.get("initial_cash", "10000")

    def validate_data(env):
        """Validate data availability for all symbols."""
        ensure_lib_path(env)
        from helpers import parse_symbols, require_data

        symbol_list = parse_symbols(symbols)
        require_data(env.path, exchange, symbol_list, timeframe)

        log.info("Data validated for %s", symbols)
        return {"symbols": symbol_list, "timeframe": timeframe}

    def run_batch(env, **kwargs):
        """Run the batch backtest."""
        ensure_lib_path(env)
        from datetime import datetime, timezone
        from decimal import Decimal

        from data.universe import Universe
        from execution.batch import BatchBacktest, ParameterGrid
        from helpers import market_data_dir, parse_symbols
        from strategy.registry import get_strategy

        strategy_class = get_strategy(strategy_name)
        symbol_list = parse_symbols(symbols)
        universe = Universe.from_symbols(symbol_list, timeframe)

        if isinstance(grid_json, str):
            grid_params = json.loads(grid_json)
        else:
            grid_params = grid_json

        grid = ParameterGrid(params=grid_params)

        start_dt = datetime.fromisoformat(start_str) if start_str else datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(end_str) if end_str else datetime.now(timezone.utc)

        batch = BatchBacktest(
            strategy_class=strategy_class,
            universe=universe,
            start=start_dt,
            end=end_dt,
            base_params={"symbols": symbol_list, "quantity": "0.01"},
            grid=grid,
            initial_cash=Decimal(initial_cash),
            n_workers=n_workers,
            data_dir=market_data_dir(env.path),
        )

        results = batch.run()

        result_dir = Path(env.path) / ".persistra" / "batch_results" / strategy_name
        results.save(result_dir)

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

    w = Workflow("batch_backtest")
    w.add("validate_data", validate_data)
    w.add("run_batch", run_batch, depends_on=["validate_data"])
    return w
