"""Tests for BatchResults in analytics/batch_results.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import pandas as pd
import pytest

from analytics.batch_results import BatchResults
from execution.batch import ParameterGrid


def _sample_runs():
    """Build a small list of successful run dicts."""
    return [
        {
            "run_index": 0,
            "params": {"fast": 5, "slow": 20},
            "metrics": {"sharpe_ratio": 1.5, "total_return": 0.12},
            "status": "success",
        },
        {
            "run_index": 1,
            "params": {"fast": 5, "slow": 30},
            "metrics": {"sharpe_ratio": 2.1, "total_return": 0.18},
            "status": "success",
        },
        {
            "run_index": 2,
            "params": {"fast": 10, "slow": 20},
            "metrics": {"sharpe_ratio": 0.8, "total_return": 0.05},
            "status": "success",
        },
    ]


def _sample_grid():
    return ParameterGrid(params={"fast": [5, 10], "slow": [20, 30]})


class TestAsDataFrame:
    def test_returns_dataframe(self):
        """as_dataframe should return a DataFrame with param + metric columns."""
        br = BatchResults(runs=_sample_runs(), grid=_sample_grid(), elapsed_seconds=1.0)
        df = br.as_dataframe()

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert "fast" in df.columns
        assert "slow" in df.columns
        assert "sharpe_ratio" in df.columns
        assert "total_return" in df.columns

    def test_excludes_failed_runs(self):
        """Failed runs should not appear in the DataFrame."""
        runs = _sample_runs()
        runs.append({
            "run_index": 3,
            "params": {"fast": 10, "slow": 30},
            "metrics": {},
            "status": "failed",
            "error": "boom",
        })
        br = BatchResults(runs=runs, grid=_sample_grid(), elapsed_seconds=1.0)
        df = br.as_dataframe()
        assert len(df) == 3


class TestBestBy:
    def test_best_by_sharpe(self):
        """best_by('sharpe_ratio') should return the run with the highest Sharpe."""
        br = BatchResults(runs=_sample_runs(), grid=_sample_grid(), elapsed_seconds=1.0)
        best = br.best_by("sharpe_ratio")

        assert best is not None
        assert best["run_index"] == 1
        assert best["metrics"]["sharpe_ratio"] == 2.1

    def test_best_by_ascending(self):
        """best_by with ascending=True should return the lowest value."""
        br = BatchResults(runs=_sample_runs(), grid=_sample_grid(), elapsed_seconds=1.0)
        worst = br.best_by("sharpe_ratio", ascending=True)

        assert worst is not None
        assert worst["run_index"] == 2
        assert worst["metrics"]["sharpe_ratio"] == 0.8


class TestSaveLoad:
    def test_round_trip(self, tmp_path):
        """save() then load() should preserve run data."""
        original = BatchResults(
            runs=_sample_runs(), grid=_sample_grid(), elapsed_seconds=2.5
        )
        save_dir = tmp_path / "batch_output"
        original.save(save_dir)

        loaded = BatchResults.load(save_dir)

        assert loaded.n_successful == original.n_successful
        assert loaded.elapsed_seconds == original.elapsed_seconds

        # DataFrames should match
        df_orig = original.as_dataframe()
        df_load = loaded.as_dataframe()
        assert len(df_load) == len(df_orig)

        # Metrics should survive the round-trip
        best_orig = original.best_by("sharpe_ratio")
        best_load = loaded.best_by("sharpe_ratio")
        assert best_orig["metrics"]["sharpe_ratio"] == best_load["metrics"]["sharpe_ratio"]
