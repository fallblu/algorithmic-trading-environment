"""Overview / home page route."""

from __future__ import annotations

from pathlib import Path

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse
except ImportError:
    pass

router = APIRouter(tags=["overview"])


def _get_result_store(data_dir: Path):
    """Lazily import and instantiate ResultStore."""
    from data.result_store import ResultStore

    results_dir = data_dir / "results"
    if not results_dir.exists():
        return None
    return ResultStore(results_dir)


@router.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    """Render the overview page with system status and quick stats."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    # Gather quick stats
    stats: dict = {
        "total_backtests": 0,
        "total_batch_runs": 0,
        "total_stress_tests": 0,
        "recent_results": [],
    }

    try:
        store = _get_result_store(data_dir)
        if store is not None:
            backtests = store.list_results(result_type="backtest")
            batch_runs = store.list_results(result_type="batch")
            stress_tests = store.list_results(result_type="stress_test")

            stats["total_backtests"] = len(backtests)
            stats["total_batch_runs"] = len(batch_runs)
            stats["total_stress_tests"] = len(stress_tests)

            # Most recent 5 results across all types
            all_results = backtests + batch_runs + stress_tests
            all_results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
            stats["recent_results"] = all_results[:5]
    except Exception:
        pass

    # Check data directory status
    market_data_exists = (data_dir / "market").is_dir() if data_dir.exists() else False

    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "stats": stats,
            "market_data_exists": market_data_exists,
            "data_dir": str(data_dir),
        },
    )
