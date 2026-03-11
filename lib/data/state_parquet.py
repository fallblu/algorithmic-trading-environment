"""ParquetStateStore — persist DataFrames as .parquet files."""

from pathlib import Path

import pandas as pd


class ParquetStateStore:
    """Stores DataFrames as Parquet files under a base directory."""

    def __init__(self, base_dir: Path):
        self._dir = base_dir / "dataframes"
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, df: pd.DataFrame) -> str:
        """Save a DataFrame to {key}.parquet. Returns the file path."""
        safe_key = key.replace("/", "_").replace(".", "_")
        path = self._dir / f"{safe_key}.parquet"
        df.to_parquet(path, index=True)
        return str(path)

    def load(self, path: str) -> pd.DataFrame:
        """Read a parquet file back into a DataFrame."""
        return pd.read_parquet(path)
