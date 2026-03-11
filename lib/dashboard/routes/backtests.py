"""Backtest results routes."""

from __future__ import annotations

from pathlib import Path

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import HTMLResponse
except ImportError:
    pass

router = APIRouter(prefix="/backtests", tags=["backtests"])


def _get_result_store(data_dir: Path):
    from data.result_store import ResultStore

    results_dir = data_dir / "results"
    if not results_dir.exists():
        return None
    return ResultStore(results_dir)


@router.get("/", response_class=HTMLResponse)
async def list_backtests(request: Request):
    """List all backtest results."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    results: list[dict] = []
    try:
        store = _get_result_store(data_dir)
        if store is not None:
            results = store.list_results(result_type="backtest")
    except Exception:
        pass

    return templates.TemplateResponse(
        "backtests.html",
        {"request": request, "results": results},
    )


@router.get("/{result_id}", response_class=HTMLResponse)
async def backtest_detail(request: Request, result_id: str):
    """Detail view for a single backtest with equity chart and metrics."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    try:
        store = _get_result_store(data_dir)
        if store is None:
            raise HTTPException(status_code=404, detail="No results store found")

        metadata = store.load(result_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Backtest {result_id} not found")

    # Try to load equity curve for charting
    equity_df = None
    try:
        equity_df = store.load_dataframe(result_id, "equity_curve")
    except (KeyError, Exception):
        pass

    equity_chart_html = ""
    if equity_df is not None:
        try:
            from dashboard.charts import render_equity_curve

            equity_chart_html = render_equity_curve(equity_df)
        except (ImportError, Exception):
            pass

    return templates.TemplateResponse(
        "backtest_detail.html",
        {
            "request": request,
            "result": metadata,
            "result_id": result_id,
            "equity_chart_html": equity_chart_html,
        },
    )
