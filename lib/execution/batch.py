"""Batch backtesting — run parameter sweeps using multiprocessing."""

import logging
import multiprocessing
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import product
from pathlib import Path

from analytics.batch_results import BatchResults
from data.universe import Universe
from strategy.base import Strategy

log = logging.getLogger(__name__)


@dataclass
class ParameterGrid:
    """Defines parameter sweep space."""
    params: dict[str, list]

    def combinations(self) -> list[dict]:
        """Generate all parameter combinations (Cartesian product)."""
        if not self.params:
            return []
        keys = list(self.params.keys())
        values = list(self.params.values())
        return [dict(zip(keys, combo)) for combo in product(*values)]

    @property
    def total(self) -> int:
        if not self.params:
            return 0
        result = 1
        for v in self.params.values():
            result *= len(v)
        return result


def _run_single_backtest(args: tuple) -> dict:
    """Worker function for a single backtest run.

    Runs in a separate process, so we re-import everything.
    """
    (strategy_class_name, strategy_module, universe_dict, timeframe,
     start_iso, end_iso, base_params, sweep_params,
     initial_cash, data_dir_str, run_index) = args

    import importlib
    import sys

    # Ensure lib is on path
    lib_dir = str(Path(data_dir_str).parent.parent)
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)

    try:
        from analytics.performance import compute_performance
        from data.universe import Universe
        from execution.backtest import BacktestContext

        # Import strategy class
        mod = importlib.import_module(strategy_module)
        strategy_class = getattr(mod, strategy_class_name)

        # Reconstruct universe
        universe = Universe.from_symbols(
            universe_dict["symbols"],
            timeframe,
            exchange=universe_dict.get("exchange", "kraken"),
        )

        # Merge params
        params = {**base_params, **sweep_params}
        params["symbols"] = universe_dict["symbols"]

        start = datetime.fromisoformat(start_iso) if start_iso else None
        end = datetime.fromisoformat(end_iso) if end_iso else None

        ctx = BacktestContext(
            universe=universe,
            start=start,
            end=end,
            initial_cash=Decimal(str(initial_cash)),
            data_dir=Path(data_dir_str),
        )

        strategy = strategy_class(ctx, params)
        results = ctx.run(strategy)

        metrics = compute_performance(
            equity_curve=results["equity_curve"],
            fills=results["fills"],
        )

        return {
            "run_index": run_index,
            "params": sweep_params,
            "metrics": metrics,
            "status": "success",
        }

    except Exception as e:
        return {
            "run_index": run_index,
            "params": sweep_params,
            "metrics": {},
            "status": "failed",
            "error": str(e),
        }


class BatchBacktest:
    """Runs multiple backtests with varying parameters."""

    def __init__(
        self,
        strategy_class: type[Strategy],
        universe: Universe,
        start: datetime | None = None,
        end: datetime | None = None,
        base_params: dict | None = None,
        grid: ParameterGrid | None = None,
        initial_cash: Decimal = Decimal("10000"),
        n_workers: int | None = None,
        data_dir: Path | None = None,
    ):
        self.strategy_class = strategy_class
        self.universe = universe
        self.start = start
        self.end = end
        self.base_params = base_params or {}
        self.grid = grid or ParameterGrid(params={})
        self.initial_cash = initial_cash
        self.n_workers = n_workers
        self.data_dir = data_dir or Path(".persistra/market_data")

    def run(self) -> BatchResults:
        """Execute all backtests and return aggregated results."""
        combinations = self.grid.combinations()

        if not combinations:
            log.warning("Empty parameter grid — nothing to run")
            return BatchResults(runs=[], grid=self.grid, elapsed_seconds=0.0)

        log.info("Starting batch backtest: %d parameter combinations, %s workers",
                 len(combinations), self.n_workers or "auto")

        # Prepare worker arguments
        strategy_module = self.strategy_class.__module__
        strategy_class_name = self.strategy_class.__name__

        universe_dict = {
            "symbols": self.universe.symbols,
            "exchange": next(iter(self.universe.instruments.values())).exchange
            if self.universe.instruments else "kraken",
        }

        start_iso = self.start.isoformat() if self.start else ""
        end_iso = self.end.isoformat() if self.end else ""

        worker_args = []
        for i, sweep_params in enumerate(combinations):
            worker_args.append((
                strategy_class_name,
                strategy_module,
                universe_dict,
                self.universe.timeframe,
                start_iso,
                end_iso,
                self.base_params,
                sweep_params,
                float(self.initial_cash),
                str(self.data_dir),
                i,
            ))

        t0 = time.time()

        if self.n_workers == 1:
            # Sequential for debugging
            runs = [_run_single_backtest(args) for args in worker_args]
        else:
            n = self.n_workers or multiprocessing.cpu_count()
            with multiprocessing.Pool(n) as pool:
                runs = pool.map(_run_single_backtest, worker_args)

        elapsed = time.time() - t0

        successes = [r for r in runs if r["status"] == "success"]
        failures = [r for r in runs if r["status"] == "failed"]

        log.info("Batch complete: %d/%d succeeded in %.1fs",
                 len(successes), len(runs), elapsed)

        if failures:
            for f in failures:
                log.warning("Run %d failed: %s (params: %s)",
                            f["run_index"], f.get("error", ""), f["params"])

        return BatchResults(runs=runs, grid=self.grid, elapsed_seconds=elapsed)
