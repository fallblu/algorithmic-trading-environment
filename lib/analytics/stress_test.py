"""Stress test orchestrator — runs Monte Carlo simulations on backtest results."""

import json
import logging
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from analytics.monte_carlo import (
    bootstrap_equity_paths,
    gbm_equity_paths,
    summary_report,
)

log = logging.getLogger(__name__)


def run_stress_test(
    backtest_results: dict,
    config: dict | None = None,
) -> dict:
    """Run stress test using both bootstrap and GBM methods.

    Args:
        backtest_results: Dict with 'equity_curve' (list of (timestamp, Decimal))
                         and optionally 'fills'.
        config: Configuration dict with:
            - n_simulations (int, default 1000)
            - methods (list, default ["bootstrap", "gbm"])
            - block_size (int, default 1)
            - confidence_levels (list, default [0.05, 0.25, 0.50, 0.75, 0.95])
            - ruin_threshold (float, default 0.5 = 50% of initial equity)

    Returns:
        Dict with results for each method.
    """
    if config is None:
        config = {}

    n_simulations = config.get("n_simulations", 1000)
    methods = config.get("methods", ["bootstrap", "gbm"])
    block_size = config.get("block_size", 1)

    if n_simulations < 1:
        raise ValueError("n_simulations must be >= 1")

    for method in methods:
        if method not in ("bootstrap", "gbm"):
            raise ValueError(f"Invalid method: {method!r}. Use 'bootstrap' or 'gbm'.")

    # Extract equity curve
    equity_curve = backtest_results.get("equity_curve", [])
    if len(equity_curve) < 3:
        raise ValueError("Need at least 3 equity points for stress testing")

    equities = np.array([float(eq) for _, eq in equity_curve])
    initial_value = equities[0]

    # Compute returns
    returns = np.diff(equities) / equities[:-1]
    returns = returns[np.isfinite(returns)]

    if len(returns) < 2:
        raise ValueError("Not enough valid returns for simulation")

    results = {}

    if "bootstrap" in methods:
        log.info("Running bootstrap simulation (%d paths)...", n_simulations)
        bootstrap_paths = bootstrap_equity_paths(
            returns=returns,
            n_simulations=n_simulations,
            path_length=len(returns),
            block_size=block_size,
            initial_value=initial_value,
        )
        results["bootstrap"] = {
            "paths": bootstrap_paths,
            "summary": summary_report(bootstrap_paths, "bootstrap"),
        }
        log.info("Bootstrap complete. Mean return: %.4f",
                 results["bootstrap"]["summary"]["mean_return"])

    if "gbm" in methods:
        log.info("Running GBM simulation (%d paths)...", n_simulations)
        # Estimate drift and volatility from returns
        mu = float(np.mean(returns)) * 252  # Annualize
        sigma = float(np.std(returns, ddof=1)) * sqrt(252)
        dt = 1.0 / 252

        gbm_paths = gbm_equity_paths(
            mu=mu,
            sigma=sigma,
            dt=dt,
            n_simulations=n_simulations,
            path_length=len(returns),
            initial_value=initial_value,
        )
        results["gbm"] = {
            "paths": gbm_paths,
            "summary": summary_report(gbm_paths, "gbm"),
        }
        log.info("GBM complete. Mean return: %.4f",
                 results["gbm"]["summary"]["mean_return"])

    return results


def save_stress_test_results(
    results: dict,
    base_dir: Path,
    strategy_name: str = "unknown",
) -> Path:
    """Save stress test results to Parquet and JSON.

    Layout:
        {base_dir}/stress_tests/{strategy}_{timestamp}/
            bootstrap_paths.parquet
            gbm_paths.parquet
            statistics.json
    """
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    result_dir = base_dir / "stress_tests" / f"{strategy_name}_{timestamp}"
    result_dir.mkdir(parents=True, exist_ok=True)

    statistics = {}

    for method_name, method_results in results.items():
        if "paths" in method_results:
            paths_df = pd.DataFrame(method_results["paths"])
            paths_df.to_parquet(result_dir / f"{method_name}_paths.parquet")

        if "summary" in method_results:
            statistics[method_name] = method_results["summary"]

    with open(result_dir / "statistics.json", "w") as f:
        json.dump(statistics, f, indent=2, default=str)

    log.info("Stress test results saved to %s", result_dir)
    return result_dir
