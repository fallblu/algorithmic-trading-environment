"""Data analysis results route."""

from __future__ import annotations

from pathlib import Path

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse
except ImportError:
    pass

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/", response_class=HTMLResponse)
async def analysis_results(request: Request):
    """Display analysis results."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    results: list[dict] = []
    try:
        from data.result_store import ResultStore

        results_dir = data_dir / "results"
        if results_dir.exists():
            store = ResultStore(results_dir)
            results = store.list_results(result_type="analysis")
    except Exception:
        pass

    return templates.TemplateResponse(
        "analysis.html",
        {"request": request, "results": results},
    )
