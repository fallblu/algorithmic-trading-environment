"""Monte Carlo simulation engine — bootstrap resampling and GBM."""

import numpy as np


def bootstrap_equity_paths(
    returns: np.ndarray,
    n_simulations: int = 1000,
    path_length: int | None = None,
    block_size: int = 1,
    initial_value: float = 10000.0,
    seed: int | None = None,
) -> np.ndarray:
    """Bootstrap resampling of actual strategy returns.

    Args:
        returns: Historical return series from a completed backtest.
        n_simulations: Number of simulated paths.
        path_length: Length of each path (default: same as returns).
        block_size: Block bootstrap size (>1 preserves autocorrelation).
        initial_value: Starting equity value.
        seed: Random seed for reproducibility.

    Returns:
        Array of shape (n_simulations, path_length) with equity values.
    """
    rng = np.random.default_rng(seed)

    if path_length is None:
        path_length = len(returns)

    paths = np.empty((n_simulations, path_length))

    for sim in range(n_simulations):
        if block_size <= 1:
            # Simple bootstrap
            sampled_returns = rng.choice(returns, size=path_length, replace=True)
        else:
            # Block bootstrap
            n_blocks = (path_length + block_size - 1) // block_size
            sampled_returns = np.empty(0)
            for _ in range(n_blocks):
                start_idx = rng.integers(0, max(1, len(returns) - block_size + 1))
                block = returns[start_idx : start_idx + block_size]
                sampled_returns = np.concatenate([sampled_returns, block])
            sampled_returns = sampled_returns[:path_length]

        # Convert returns to equity path
        equity = initial_value * np.cumprod(1 + sampled_returns)
        paths[sim] = equity

    return paths


def gbm_equity_paths(
    mu: float,
    sigma: float,
    dt: float,
    n_simulations: int = 1000,
    path_length: int = 252,
    initial_value: float = 10000.0,
    seed: int | None = None,
) -> np.ndarray:
    """Geometric Brownian Motion simulation.

    S(t+dt) = S(t) * exp((mu - sigma^2/2)*dt + sigma*sqrt(dt)*Z)

    Args:
        mu: Annualized drift.
        sigma: Annualized volatility.
        dt: Time step as fraction of year (e.g., 1/252 for daily).
        n_simulations: Number of paths.
        path_length: Length of each path.
        initial_value: Starting value.
        seed: Random seed.

    Returns:
        Array of shape (n_simulations, path_length) with equity values.
    """
    rng = np.random.default_rng(seed)

    drift = (mu - 0.5 * sigma ** 2) * dt
    vol = sigma * np.sqrt(dt)

    Z = rng.standard_normal((n_simulations, path_length))
    log_returns = drift + vol * Z

    # Cumulative sum of log returns, then exponentiate
    paths = initial_value * np.exp(np.cumsum(log_returns, axis=1))

    return paths


def compute_path_statistics(paths: np.ndarray) -> list[dict]:
    """Compute statistics for each simulated path.

    Args:
        paths: Array of shape (n_simulations, path_length).

    Returns:
        List of dicts, one per path, with total_return, max_drawdown, sharpe, final_value.
    """
    stats = []
    for i in range(paths.shape[0]):
        path = paths[i]
        initial = path[0] / (1 + 0)  # approximate initial from first step
        # Use first value as proxy for initial
        final_value = path[-1]

        # Returns from path
        returns = np.diff(path) / path[:-1] if len(path) > 1 else np.array([0.0])
        returns = returns[np.isfinite(returns)]

        total_return = (final_value / path[0] - 1) if path[0] != 0 else 0.0

        # Max drawdown
        peak = np.maximum.accumulate(path)
        drawdown = (peak - path) / np.where(peak != 0, peak, 1)
        max_dd = float(np.max(drawdown))

        # Sharpe (annualized, assuming 252 periods)
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(252))
        else:
            sharpe = 0.0

        stats.append({
            "total_return": float(total_return),
            "max_drawdown": max_dd,
            "sharpe": sharpe,
            "final_value": float(final_value),
        })

    return stats


def confidence_intervals(
    paths: np.ndarray,
    levels: list[float] | None = None,
) -> dict[str, np.ndarray]:
    """Compute percentile bands across simulations at each time step.

    Args:
        paths: Array of shape (n_simulations, path_length).
        levels: Percentile levels (default: [0.05, 0.25, 0.50, 0.75, 0.95]).

    Returns:
        Dict of percentile label -> array of values at each timestep.
    """
    if levels is None:
        levels = [0.05, 0.25, 0.50, 0.75, 0.95]

    result = {}
    for level in levels:
        percentile = level * 100
        result[f"p{int(percentile)}"] = np.percentile(paths, percentile, axis=0)

    return result


def probability_of_ruin(paths: np.ndarray, ruin_threshold: float) -> float:
    """Probability that equity drops below threshold at any point.

    Args:
        paths: Array of shape (n_simulations, path_length).
        ruin_threshold: Absolute equity threshold.

    Returns:
        Fraction of paths that hit ruin.
    """
    min_values = np.min(paths, axis=1)
    return float(np.mean(min_values <= ruin_threshold))


def var_cvar_from_simulations(
    paths: np.ndarray, confidence: float = 0.95
) -> tuple[float, float]:
    """VaR and CVaR from terminal values of simulated paths.

    Args:
        paths: Array of shape (n_simulations, path_length).
        confidence: Confidence level (e.g., 0.95).

    Returns:
        (VaR, CVaR) as returns from initial value.
    """
    terminal = paths[:, -1]
    initial = paths[:, 0]
    returns = (terminal - initial) / np.where(initial != 0, initial, 1)

    var_level = np.percentile(returns, (1 - confidence) * 100)
    tail = returns[returns <= var_level]
    cvar = float(np.mean(tail)) if len(tail) > 0 else float(var_level)

    return float(var_level), cvar


def expected_shortfall_over_time(
    paths: np.ndarray, threshold: float
) -> np.ndarray:
    """Time-varying expected shortfall.

    At each timestep, compute the mean equity value of paths
    below the threshold.
    """
    result = np.empty(paths.shape[1])
    for t in range(paths.shape[1]):
        below = paths[:, t][paths[:, t] <= threshold]
        result[t] = float(np.mean(below)) if len(below) > 0 else threshold
    return result


def summary_report(paths: np.ndarray, method_name: str) -> dict:
    """Consolidated summary of all Monte Carlo statistics."""
    stats = compute_path_statistics(paths)
    ci = confidence_intervals(paths)
    initial_value = float(paths[0, 0]) if paths.shape[1] > 0 else 10000.0

    total_returns = [s["total_return"] for s in stats]
    max_drawdowns = [s["max_drawdown"] for s in stats]
    sharpes = [s["sharpe"] for s in stats]
    final_values = [s["final_value"] for s in stats]

    var_95, cvar_95 = var_cvar_from_simulations(paths, 0.95)
    p_ruin_50 = probability_of_ruin(paths, initial_value * 0.5)

    return {
        "method": method_name,
        "n_simulations": paths.shape[0],
        "path_length": paths.shape[1],
        "mean_return": float(np.mean(total_returns)),
        "median_return": float(np.median(total_returns)),
        "std_return": float(np.std(total_returns)),
        "mean_max_drawdown": float(np.mean(max_drawdowns)),
        "median_max_drawdown": float(np.median(max_drawdowns)),
        "mean_sharpe": float(np.mean(sharpes)),
        "mean_final_value": float(np.mean(final_values)),
        "median_final_value": float(np.median(final_values)),
        "var_95": var_95,
        "cvar_95": cvar_95,
        "probability_of_ruin_50pct": p_ruin_50,
    }
