"""Batch run routes."""

from __future__ import annotations

from pathlib import Path

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import HTMLResponse
except ImportError:
    pass

router = APIRouter(prefix="/batch", tags=["batch"])


def _get_result_store(data_dir: Path):
    from data.result_store import ResultStore

    results_dir = data_dir / "results"
    if not results_dir.exists():
        return None
    return ResultStore(results_dir)


@router.get("/", response_class=HTMLResponse)
async def list_batch_runs(request: Request):
    """List all batch runs."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    results: list[dict] = []
    try:
        store = _get_result_store(data_dir)
        if store is not None:
            results = store.list_results(result_type="batch")
    except Exception:
        pass

    return templates.TemplateResponse(
        "batch.html",
        {"request": request, "results": results},
    )


@router.get("/{result_id}", response_class=HTMLResponse)
async def batch_detail(request: Request, result_id: str):
    """Detail view for a batch run with heatmap."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    try:
        store = _get_result_store(data_dir)
        if store is None:
            raise HTTPException(status_code=404, detail="No results store found")

        metadata = store.load(result_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Batch run {result_id} not found")

    # Try to load heatmap data
    heatmap_df = None
    try:
        heatmap_df = store.load_dataframe(result_id, "heatmap")
    except (KeyError, Exception):
        pass

    heatmap_chart_html = ""
    if heatmap_df is not None:
        try:
            from dashboard.charts import render_heatmap

            heatmap_chart_html = render_heatmap(heatmap_df)
        except (ImportError, Exception):
            pass

    return templates.TemplateResponse(
        "batch_detail.html",
        {
            "request": request,
            "result": metadata,
            "result_id": result_id,
            "heatmap_chart_html": heatmap_chart_html,
        },
    )
