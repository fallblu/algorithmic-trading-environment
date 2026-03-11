"""Stress test results routes."""

from __future__ import annotations

from pathlib import Path

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import HTMLResponse
except ImportError:
    pass

router = APIRouter(prefix="/stress", tags=["stress_test"])


def _get_result_store(data_dir: Path):
    from data.result_store import ResultStore

    results_dir = data_dir / "results"
    if not results_dir.exists():
        return None
    return ResultStore(results_dir)


@router.get("/", response_class=HTMLResponse)
async def list_stress_tests(request: Request):
    """List all stress test results."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    results: list[dict] = []
    try:
        store = _get_result_store(data_dir)
        if store is not None:
            results = store.list_results(result_type="stress_test")
    except Exception:
        pass

    return templates.TemplateResponse(
        "stress_test.html",
        {"request": request, "results": results},
    )


@router.get("/{result_id}", response_class=HTMLResponse)
async def stress_test_detail(request: Request, result_id: str):
    """Detail view for a single stress test."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    try:
        store = _get_result_store(data_dir)
        if store is None:
            raise HTTPException(status_code=404, detail="No results store found")

        metadata = store.load(result_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Stress test {result_id} not found")

    # Try to load simulation paths for charting
    paths_df = None
    try:
        paths_df = store.load_dataframe(result_id, "paths")
    except (KeyError, Exception):
        pass

    chart_html = ""
    if paths_df is not None:
        try:
            from dashboard.charts import render_stress_paths

            chart_html = render_stress_paths(paths_df)
        except (ImportError, Exception):
            pass

    return templates.TemplateResponse(
        "stress_test_detail.html",
        {
            "request": request,
            "result": metadata,
            "result_id": result_id,
            "chart_html": chart_html,
        },
    )
