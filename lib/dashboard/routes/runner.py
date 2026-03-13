"""Process runner API — launch and monitor Persistra processes from the dashboard."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
except ImportError:
    pass

router = APIRouter(prefix="/api", tags=["runner"])

# ---------------------------------------------------------------------------
# In-memory process tracker
# ---------------------------------------------------------------------------

_processes: dict[int, dict] = {}
_lock = threading.Lock()


def _register(proc: subprocess.Popen, kind: str, params: dict) -> dict:
    entry = {
        "pid": proc.pid,
        "type": kind,
        "params": params,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }
    with _lock:
        _processes[proc.pid] = {"entry": entry, "proc": proc}
    return entry


def _poll_all() -> list[dict]:
    with _lock:
        entries = []
        for info in _processes.values():
            proc = info["proc"]
            entry = info["entry"]
            rc = proc.poll()
            if rc is None:
                entry["status"] = "running"
            elif rc == 0:
                entry["status"] = "completed"
            else:
                entry["status"] = "failed"
            entries.append(entry)
    # Most recent first
    entries.sort(key=lambda e: e["started_at"], reverse=True)
    return entries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_process_cmd(process_name: str, params: dict, env_path: str) -> list[str]:
    """Build a persistra process run command."""
    cmd = [sys.executable, "-m", "persistra", "process", "run", process_name]
    for key, value in params.items():
        cmd.extend(["-p", f"{key}={value}"])
    return cmd


def _build_workflow_cmd(workflow_name: str, env_path: str) -> list[str]:
    """Build a persistra workflow run command."""
    return [sys.executable, "-m", "persistra", "workflow", "run", workflow_name]


def _get_env_path(request: Request) -> str:
    env = request.app.state.env
    if env is not None and hasattr(env, "path"):
        return str(env.path)
    return str(Path.cwd())


def _launch(request: Request, kind: str, cmd: list[str], params: dict) -> JSONResponse:
    env_path = _get_env_path(request)
    try:
        log_dir = Path(env_path) / ".persistra" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        log_file = log_dir / f"{kind}_{ts}.log"
        fh = open(log_file, "w")
        proc = subprocess.Popen(
            cmd,
            cwd=env_path,
            stdout=fh,
            stderr=fh,
        )
        entry = _register(proc, kind, params)
        entry["log"] = str(log_file)
        return JSONResponse({"ok": True, **entry})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class BacktestRequest(BaseModel):
    strategy: str = "sma_crossover"
    symbols: str = "BTC/USD"
    timeframe: str = "1h"
    exchange: str = "kraken"
    start: str = ""
    end: str = ""
    initial_cash: str = "10000"
    max_position_size: str = "1.0"
    params: str = "{}"


class BatchRequest(BaseModel):
    strategy: str = "sma_crossover"
    symbols: str = "BTC/USD"
    timeframe: str = "1h"
    grid: str = '{"fast_period": [5, 10, 15, 20], "slow_period": [20, 30, 40, 50]}'
    initial_cash: str = "10000"
    n_workers: int = 0
    start: str = ""
    end: str = ""


class IngestRequest(BaseModel):
    exchange: str = "kraken"
    symbols: str = "BTC/USD"
    timeframe: str = "1h"
    backfill_days: int = 365


class StressTestRequest(BaseModel):
    n_simulations: int = 1000
    block_size: int = 1


class AnalysisRequest(BaseModel):
    symbol: str = "BTC/USD"
    timeframe: str = "1h"
    exchange: str = "kraken"
    scan_symbols: str = "BTC/USD,ETH/USD"
    correlation_symbols: str = "BTC/USD,ETH/USD"


class ScanRequest(BaseModel):
    symbols: str = "BTC/USD,ETH/USD"
    timeframe: str = "1h"
    exchange: str = "kraken"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/processes")
async def list_processes():
    """Return status of all tracked processes."""
    return JSONResponse({"processes": _poll_all()})


@router.get("/strategies")
async def list_strategies_endpoint():
    """Return available strategy names."""
    try:
        from strategy.registry import load_all_strategies, list_strategies
        load_all_strategies()
        names = list_strategies()
    except Exception:
        names = [
            "sma_crossover", "bollinger_reversion", "rsi_reversion",
            "breakout", "macd_trend", "adx_trend", "pairs",
            "regime_adaptive", "multi_tf", "portfolio_rebalance",
        ]
    return JSONResponse({"strategies": names})


@router.post("/run/backtest")
async def run_backtest(body: BacktestRequest, request: Request):
    """Launch a backtest process."""
    p = {k: v for k, v in body.model_dump().items() if v}
    cmd = _build_process_cmd("backtest", p, _get_env_path(request))
    return _launch(request, "backtest", cmd, p)


@router.post("/run/batch")
async def run_batch(body: BatchRequest, request: Request):
    """Launch a batch backtest process."""
    p = {k: v for k, v in body.model_dump().items() if v}
    if body.n_workers:
        p["n_workers"] = str(body.n_workers)
    cmd = _build_process_cmd("batch_backtest", p, _get_env_path(request))
    return _launch(request, "batch", cmd, p)


@router.post("/run/ingest")
async def run_ingest(body: IngestRequest, request: Request):
    """Launch a data ingestor process."""
    p = body.model_dump()
    p["backfill_days"] = str(p["backfill_days"])
    cmd = _build_process_cmd("data_ingestor", p, _get_env_path(request))
    return _launch(request, "ingest", cmd, p)


@router.post("/run/stress-test")
async def run_stress_test(body: StressTestRequest, request: Request):
    """Launch a stress test workflow."""
    env_path = _get_env_path(request)

    # Pre-set workflow state via persistra CLI
    params = body.model_dump()
    cmd = _build_workflow_cmd("stress_test", env_path)
    return _launch(request, "stress_test", cmd, params)


@router.post("/run/analysis")
async def run_analysis(body: AnalysisRequest, request: Request):
    """Launch an analysis workflow."""
    env_path = _get_env_path(request)
    params = body.model_dump()
    cmd = _build_workflow_cmd("analyze", env_path)
    return _launch(request, "analysis", cmd, params)


@router.post("/run/scan")
async def run_scan(body: ScanRequest, request: Request):
    """Launch a scan (subset of analysis workflow)."""
    env_path = _get_env_path(request)
    params = body.model_dump()
    cmd = _build_workflow_cmd("analyze", env_path)
    return _launch(request, "scan", cmd, params)
