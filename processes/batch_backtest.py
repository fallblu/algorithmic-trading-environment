"""Batch backtest process — run parameter sweeps from command line."""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from persistra import process

log = logging.getLogger(__name__)


@process("job")
def run(
    env,
    strategy: str = "sma_crossover",
    symbols: str = "BTC/USD",
    timeframe: str = "1h",
    grid: str = '{"fast_period": [5, 10, 15, 20], "slow_period": [20, 30, 40, 50]}',
    initial_cash: str = "10000",
    n_workers: int = 0,
    start: str = "",
    end: str = "",
):
    """Run a batch of backtests with varying parameters.

    Args:
        strategy: Registered strategy name.
        symbols: Comma-separated symbol list.
        timeframe: Bar timeframe.
        grid: JSON string of parameter grid.
        initial_cash: Starting equity.
        n_workers: Number of worker processes (0 = auto).
        start: Start date ISO format.
        end: End date ISO format.
    """
    from data.universe import Universe
    from execution.batch import BatchBacktest, ParameterGrid
    from strategy.registry import get_strategy
    # Ensure sma_crossover is registered
    import strategy.sma_crossover  # noqa: F401

    from helpers import market_data_dir, parse_symbols, require_data

    strategy_class = get_strategy(strategy)
    symbol_list = parse_symbols(symbols)
    require_data(env.path, "kraken", symbol_list, timeframe)
    universe = Universe.from_symbols(symbol_list, timeframe)

    grid_params = json.loads(grid)
    param_grid = ParameterGrid(params=grid_params)

    start_dt = datetime.fromisoformat(start) if start else datetime(2024, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)

    batch = BatchBacktest(
        strategy_class=strategy_class,
        universe=universe,
        start=start_dt,
        end=end_dt,
        base_params={"symbols": symbol_list, "quantity": "0.01"},
        grid=param_grid,
        initial_cash=Decimal(initial_cash),
        n_workers=n_workers or None,
        data_dir=market_data_dir(env.path),
    )

    results = batch.run()

    # Save
    result_dir = Path(env.path) / ".persistra" / "batch_results" / strategy
    results.save(result_dir)

    ns = env.state.ns("batch")
    best = results.best_by("sharpe_ratio")
    if best:
        ns.set("best_params", best["params"])
        ns.set("best_metrics", best["metrics"])

    ns.set("total_runs", len(results.runs))
    ns.set("successful_runs", results.n_successful)

    log.info("=== Batch Results ===")
    log.info("Runs: %d/%d succeeded", results.n_successful, len(results.runs))
    log.info("Time: %.1fs", results.elapsed_seconds)
    if best:
        log.info("Best: %s → Sharpe=%.4f", best["params"],
                 best["metrics"].get("sharpe_ratio", 0))
