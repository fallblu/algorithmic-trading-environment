"""Stress test workflow — run Monte Carlo simulations on backtest results."""

import logging
from pathlib import Path

from persistra import Workflow

from _common import ensure_lib_path

log = logging.getLogger(__name__)


def build(env) -> Workflow:
    """Build the stress test workflow DAG."""
    wf = env.state.ns("wf.stress_test")
    n_simulations = int(wf.get("n_simulations", 1000))
    block_size = int(wf.get("block_size", 1))

    def load_backtest_results(env):
        """Load backtest results (equity curve, returns) from state."""
        ensure_lib_path(env)
        import pandas as pd
        from data.state_parquet import ParquetStateStore
        from decimal import Decimal

        ns = env.state.ns("backtest")
        eq_path = ns.get("equity_curve_path", "")

        if not eq_path:
            raise RuntimeError(
                "No backtest equity curve found. "
                "Run: persistra process run sma_crossover -p symbols=BTC/USD first."
            )

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
        ensure_lib_path(env)
        from analytics.stress_test import run_stress_test, save_stress_test_results

        backtest_results = kwargs.get("equity_curve_data", {})
        if not backtest_results:
            backtest_results = load_backtest_results(env)

        config = {
            "n_simulations": n_simulations,
            "methods": ["bootstrap", "gbm"],
            "block_size": block_size,
        }

        results = run_stress_test(backtest_results, config)

        base_dir = Path(env.path) / ".persistra"
        strategy_name = env.state.ns("strategy.sma_crossover").get(
            "params", {}
        ).get("strategy", "sma_crossover")
        result_dir = save_stress_test_results(results, base_dir, strategy_name)

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

    w = Workflow("stress_test")
    w.add("load_results", load_backtest_results)
    w.add("run_simulations", run_simulations, depends_on=["load_results"])
    return w
