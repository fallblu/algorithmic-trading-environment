"""Stress test workflow — run Monte Carlo simulations on backtest results."""

import logging
import sys
from pathlib import Path

from persistra import Workflow

log = logging.getLogger(__name__)


def _ensure_lib_path(env):
    lib_path = str(Path(env.path) / "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def load_backtest_results(env):
    """Load backtest results (equity curve, returns) from state."""
    _ensure_lib_path(env)
    import pandas as pd
    from data.state_parquet import ParquetStateStore
    from decimal import Decimal

    ns = env.state.ns("backtest")
    eq_path = ns.get("equity_curve_path", "")

    if not eq_path:
        raise RuntimeError("No backtest equity curve found. Run a backtest first.")

    pq_store = ParquetStateStore(Path(env.path) / ".persistra")
    eq_df = pq_store.load(eq_path)

    equity_curve = [
        (row["timestamp"], Decimal(str(row["equity"])))
        for _, row in eq_df.iterrows()
    ]

    log.info("Loaded %d equity points from backtest", len(equity_curve))
    return {"equity_curve": equity_curve}


def run_simulations(env, **kwargs):
    """Run bootstrap and GBM simulations."""
    _ensure_lib_path(env)
    from analytics.stress_test import run_stress_test, save_stress_test_results

    backtest_results = kwargs.get("equity_curve_data", {})
    if not backtest_results:
        # Fallback: try to get from previous step
        backtest_results = load_backtest_results(env)

    config = {
        "n_simulations": int(env.state.get("stress_n_simulations", 1000)),
        "methods": ["bootstrap", "gbm"],
        "block_size": int(env.state.get("stress_block_size", 1)),
    }

    results = run_stress_test(backtest_results, config)

    base_dir = Path(env.path) / ".persistra"
    strategy_name = env.state.ns("strategy.sma_crossover").get("params", {}).get("strategy", "sma_crossover")
    result_dir = save_stress_test_results(results, base_dir, strategy_name)

    # Save summary to state
    ns = env.state.ns("stress_test")
    for method, method_results in results.items():
        if "summary" in method_results:
            ns.set(f"{method}_summary", method_results["summary"])

    ns.set("result_dir", str(result_dir))

    log.info("=== Stress Test Summary ===")
    for method, method_results in results.items():
        summary = method_results.get("summary", {})
        log.info("%s — Mean Return: %.4f, P(Ruin): %.4f, VaR95: %.4f",
                 method, summary.get("mean_return", 0),
                 summary.get("probability_of_ruin_50pct", 0),
                 summary.get("var_95", 0))

    return results


def build(env) -> Workflow:
    """Build the stress test workflow DAG."""
    w = Workflow("stress_test")
    w.add("load_results", load_backtest_results)
    w.add("run_simulations", run_simulations, depends_on=["load_results"])
    return w
