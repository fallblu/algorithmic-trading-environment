"""Portfolio / positions route."""

from __future__ import annotations

from pathlib import Path

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse
except ImportError:
    pass

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/", response_class=HTMLResponse)
async def portfolio(request: Request):
    """Current positions and account summary."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    positions: list[dict] = []
    account_summary: dict = {}

    # Try to load portfolio state from parquet
    try:
        state_path = data_dir / "state" / "positions.parquet"
        if state_path.exists():
            import pandas as pd

            df = pd.read_parquet(state_path)
            positions = df.to_dict(orient="records")
    except Exception:
        pass

    # Try to load account summary
    try:
        import json

        account_path = data_dir / "state" / "account.json"
        if account_path.exists():
            with open(account_path) as f:
                account_summary = json.load(f)
    except Exception:
        pass

    return templates.TemplateResponse(
        "portfolio.html",
        {
            "request": request,
            "positions": positions,
            "account_summary": account_summary,
        },
    )
