"""BatchResults — aggregated results from batch backtesting."""

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class BatchResults:
    """Aggregated results from a batch of backtests."""
    runs: list[dict]
    grid: object  # ParameterGrid
    elapsed_seconds: float

    def as_dataframe(self) -> pd.DataFrame:
        """All runs as a DataFrame with param columns + metric columns."""
        rows = []
        for run in self.runs:
            if run.get("status") != "success":
                continue
            row = {**run.get("params", {}), **run.get("metrics", {})}
            rows.append(row)

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows)

    def best_by(self, metric: str, ascending: bool = False) -> dict | None:
        """Return the run with the best value for a metric."""
        successful = [r for r in self.runs if r.get("status") == "success"]
        if not successful:
            return None

        def key_fn(r):
            return r.get("metrics", {}).get(metric, float("-inf") if not ascending else float("inf"))

        return sorted(successful, key=key_fn, reverse=not ascending)[0]

    def heatmap_data(self, param_x: str, param_y: str, metric: str) -> pd.DataFrame:
        """Pivot table for 2D heatmap visualization of metric vs two params."""
        df = self.as_dataframe()
        if df.empty or param_x not in df.columns or param_y not in df.columns:
            return pd.DataFrame()

        return df.pivot_table(
            values=metric,
            index=param_y,
            columns=param_x,
            aggfunc="mean",
        )

    def sensitivity(self, param: str, metric: str) -> pd.DataFrame:
        """1D sensitivity: metric vs single param (averaged over other params)."""
        df = self.as_dataframe()
        if df.empty or param not in df.columns or metric not in df.columns:
            return pd.DataFrame()

        return df.groupby(param)[metric].mean().reset_index()

    @property
    def n_successful(self) -> int:
        return sum(1 for r in self.runs if r.get("status") == "success")

    @property
    def n_failed(self) -> int:
        return sum(1 for r in self.runs if r.get("status") == "failed")

    def save(self, path: Path) -> None:
        """Save all results to Parquet + JSON."""
        path.mkdir(parents=True, exist_ok=True)

        # Save runs as Parquet
        df = self.as_dataframe()
        if not df.empty:
            df.to_parquet(path / "runs.parquet", index=False)

        # Save metadata as JSON
        meta = {
            "total_runs": len(self.runs),
            "successful": self.n_successful,
            "failed": self.n_failed,
            "elapsed_seconds": self.elapsed_seconds,
            "grid_params": self.grid.params if hasattr(self.grid, "params") else {},
        }
        with open(path / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2, default=str)

        # Save individual run details
        runs_serializable = []
        for run in self.runs:
            runs_serializable.append({
                "run_index": run.get("run_index"),
                "params": run.get("params", {}),
                "metrics": run.get("metrics", {}),
                "status": run.get("status"),
                "error": run.get("error", ""),
            })
        with open(path / "runs.json", "w") as f:
            json.dump(runs_serializable, f, indent=2, default=str)

    @classmethod
    def load(cls, path: Path) -> "BatchResults":
        """Load results from saved files."""
        from execution.batch import ParameterGrid

        with open(path / "metadata.json") as f:
            meta = json.load(f)

        with open(path / "runs.json") as f:
            runs = json.load(f)

        grid = ParameterGrid(params=meta.get("grid_params", {}))
        return cls(
            runs=runs,
            grid=grid,
            elapsed_seconds=meta.get("elapsed_seconds", 0.0),
        )
