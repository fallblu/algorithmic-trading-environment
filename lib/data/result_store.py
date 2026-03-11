"""ResultStore — centralized storage and indexing of all results."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


class ResultStore:
    """Centralized storage for backtest, batch, stress test, and analysis results.

    Each result gets a UUID, timestamp, and metadata. Heavy data (equity curves,
    paths) is stored in Parquet files. An index file tracks all results for
    fast listing and querying.

    Layout:
        {base_dir}/
            index.json                              — result index
            {result_type}/{uuid}/
                metadata.json                       — params, strategy, universe
                equity_curve.parquet (or similar)    — heavy data
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.base_dir / "index.json"
        self._index: list[dict] = self._load_index()

    def _load_index(self) -> list[dict]:
        if self._index_path.exists():
            with open(self._index_path) as f:
                return json.load(f)
        return []

    def _save_index(self) -> None:
        with open(self._index_path, "w") as f:
            json.dump(self._index, f, indent=2, default=str)

    def save(
        self,
        result_type: str,
        metadata: dict,
        dataframes: dict[str, pd.DataFrame] | None = None,
    ) -> str:
        """Save a result with metadata and optional DataFrames.

        Args:
            result_type: One of 'backtest', 'batch', 'stress_test', 'analysis'.
            metadata: Dict with strategy name, params, universe, metrics, etc.
            dataframes: Optional dict of name -> DataFrame to save as Parquet.

        Returns:
            The UUID string assigned to this result.
        """
        result_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        result_dir = self.base_dir / result_type / result_id
        result_dir.mkdir(parents=True, exist_ok=True)

        # Save metadata
        meta = {
            "id": result_id,
            "type": result_type,
            "timestamp": timestamp,
            **metadata,
        }
        with open(result_dir / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2, default=str)

        # Save DataFrames as Parquet
        parquet_paths = {}
        if dataframes:
            for name, df in dataframes.items():
                path = result_dir / f"{name}.parquet"
                df.to_parquet(path, index=True)
                parquet_paths[name] = str(path)

        # Update index
        index_entry = {
            "id": result_id,
            "type": result_type,
            "timestamp": timestamp,
            "strategy": metadata.get("strategy", ""),
            "universe": metadata.get("universe", ""),
            "parquet_paths": parquet_paths,
        }
        self._index.append(index_entry)
        self._save_index()

        return result_id

    def load(self, result_id: str) -> dict:
        """Load a result by UUID. Returns metadata dict with 'parquet_paths'."""
        for entry in self._index:
            if entry["id"] == result_id:
                result_dir = self.base_dir / entry["type"] / result_id
                meta_path = result_dir / "metadata.json"
                if meta_path.exists():
                    with open(meta_path) as f:
                        meta = json.load(f)
                    meta["parquet_paths"] = entry.get("parquet_paths", {})
                    return meta
        raise KeyError(f"Result {result_id} not found")

    def load_dataframe(self, result_id: str, name: str) -> pd.DataFrame:
        """Load a specific DataFrame from a result."""
        result = self.load(result_id)
        parquet_paths = result.get("parquet_paths", {})
        path = parquet_paths.get(name)
        if path is None:
            raise KeyError(f"DataFrame {name!r} not found in result {result_id}")
        return pd.read_parquet(path)

    def list_results(
        self,
        result_type: str | None = None,
        strategy: str | None = None,
    ) -> list[dict]:
        """List results, optionally filtered by type and/or strategy.

        Returns results sorted by timestamp descending (newest first).
        """
        results = self._index

        if result_type is not None:
            results = [r for r in results if r["type"] == result_type]

        if strategy is not None:
            results = [r for r in results if r.get("strategy") == strategy]

        return sorted(results, key=lambda r: r["timestamp"], reverse=True)

    def delete(self, result_id: str) -> None:
        """Delete a result by UUID."""
        import shutil

        for i, entry in enumerate(self._index):
            if entry["id"] == result_id:
                result_dir = self.base_dir / entry["type"] / result_id
                if result_dir.exists():
                    shutil.rmtree(result_dir)
                self._index.pop(i)
                self._save_index()
                return

        raise KeyError(f"Result {result_id} not found")
