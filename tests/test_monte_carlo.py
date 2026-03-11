import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from analytics.monte_carlo import (
    bootstrap_equity_paths,
    compute_path_statistics,
    confidence_intervals,
    gbm_equity_paths,
    probability_of_ruin,
)


def _sample_returns(n=100, seed=42):
    rng = np.random.default_rng(seed)
    return rng.normal(0.001, 0.02, size=n)


def test_bootstrap_equity_paths_shape():
    returns = _sample_returns()
    n_sims, path_len = 50, 80
    paths = bootstrap_equity_paths(
        returns, n_simulations=n_sims, path_length=path_len, seed=1
    )
    assert paths.shape == (n_sims, path_len)
    # All values should be positive (equity paths)
    assert np.all(paths > 0)


def test_gbm_equity_paths_shape():
    n_sims, path_len = 30, 100
    paths = gbm_equity_paths(
        mu=0.10, sigma=0.20, dt=1 / 252,
        n_simulations=n_sims, path_length=path_len, seed=1,
    )
    assert paths.shape == (n_sims, path_len)
    assert np.all(paths > 0)


def test_compute_path_statistics_keys():
    paths = gbm_equity_paths(mu=0.1, sigma=0.2, dt=1/252, n_simulations=10, path_length=50, seed=1)
    stats = compute_path_statistics(paths)

    assert isinstance(stats, list)
    assert len(stats) == 10
    expected_keys = {"total_return", "max_drawdown", "sharpe", "final_value"}
    for s in stats:
        assert expected_keys.issubset(s.keys())
        assert isinstance(s["total_return"], float)
        assert isinstance(s["max_drawdown"], float)
        assert s["max_drawdown"] >= 0


def test_confidence_intervals_returns_expected_keys():
    paths = gbm_equity_paths(mu=0.1, sigma=0.2, dt=1/252, n_simulations=100, path_length=50, seed=1)
    ci = confidence_intervals(paths)

    assert isinstance(ci, dict)
    expected_keys = {"p5", "p25", "p50", "p75", "p95"}
    assert expected_keys == set(ci.keys())

    # Each value should be an array with length == path_length
    for key, arr in ci.items():
        assert len(arr) == 50


def test_probability_of_ruin_returns_float_between_0_and_1():
    paths = gbm_equity_paths(
        mu=-0.5, sigma=0.5, dt=1/252,
        n_simulations=200, path_length=252, seed=1,
        initial_value=10000.0,
    )
    p_ruin = probability_of_ruin(paths, ruin_threshold=5000.0)

    assert isinstance(p_ruin, float)
    assert 0.0 <= p_ruin <= 1.0
