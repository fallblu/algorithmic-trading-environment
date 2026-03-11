"""Signal viewer route."""

from __future__ import annotations

from pathlib import Path

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse
except ImportError:
    pass

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/", response_class=HTMLResponse)
async def signal_viewer(request: Request):
    """Display recent signals."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    signals: list[dict] = []

    # Try to load signals from results store
    try:
        from data.result_store import ResultStore

        results_dir = data_dir / "results"
        if results_dir.exists():
            store = ResultStore(results_dir)
            # Signals may be stored as analysis results with type 'signal'
            # or as a dedicated signals file
            signal_results = store.list_results(result_type="signal")
            for entry in signal_results[:50]:  # limit to most recent 50
                try:
                    meta = store.load(entry["id"])
                    signals.append(meta)
                except Exception:
                    continue
    except Exception:
        pass

    # Also check for a signals JSON file
    if not signals:
        try:
            import json

            signals_path = data_dir / "state" / "signals.json"
            if signals_path.exists():
                with open(signals_path) as f:
                    signals = json.load(f)
                if not isinstance(signals, list):
                    signals = [signals]
        except Exception:
            signals = []

    return templates.TemplateResponse(
        "signals.html",
        {"request": request, "signals": signals},
    )
