import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from data.result_store import ResultStore


def test_save_and_load_metadata_roundtrip(tmp_path):
    store = ResultStore(tmp_path)
    metadata = {"strategy": "momentum", "universe": "crypto", "sharpe": 1.5}
    result_id = store.save("backtest", metadata)

    loaded = store.load(result_id)
    assert loaded["strategy"] == "momentum"
    assert loaded["universe"] == "crypto"
    assert loaded["sharpe"] == 1.5
    assert loaded["id"] == result_id
    assert loaded["type"] == "backtest"


def test_save_with_dataframe_and_load_dataframe(tmp_path):
    store = ResultStore(tmp_path)
    equity_df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=5),
        "equity": [10000, 10100, 10050, 10200, 10300],
    })
    metadata = {"strategy": "mean_reversion"}
    result_id = store.save("backtest", metadata, dataframes={"equity_curve": equity_df})

    loaded_df = store.load_dataframe(result_id, "equity_curve")
    assert len(loaded_df) == 5
    assert "equity" in loaded_df.columns
    assert loaded_df["equity"].iloc[-1] == 10300


def test_list_results_filtering_by_type(tmp_path):
    store = ResultStore(tmp_path)
    store.save("backtest", {"strategy": "a"})
    store.save("analysis", {"strategy": "b"})
    store.save("backtest", {"strategy": "c"})

    backtests = store.list_results(result_type="backtest")
    assert len(backtests) == 2
    assert all(r["type"] == "backtest" for r in backtests)

    analyses = store.list_results(result_type="analysis")
    assert len(analyses) == 1
    assert analyses[0]["type"] == "analysis"


def test_delete_removes_result(tmp_path):
    store = ResultStore(tmp_path)
    rid = store.save("backtest", {"strategy": "test"})

    assert len(store.list_results()) == 1
    store.delete(rid)
    assert len(store.list_results()) == 0

    with pytest.raises(KeyError):
        store.load(rid)


def test_load_nonexistent_raises_key_error(tmp_path):
    store = ResultStore(tmp_path)
    with pytest.raises(KeyError):
        store.load("nonexistent-uuid")
