"""Market data explorer route."""

from __future__ import annotations

from pathlib import Path

try:
    from fastapi import APIRouter, Query, Request
    from fastapi.responses import HTMLResponse
except ImportError:
    pass

router = APIRouter(prefix="/data", tags=["market_data"])


def _discover_symbols(data_dir: Path) -> list[dict]:
    """Scan the market data directory for available symbol/timeframe combos."""
    market_dir = data_dir / "market"
    if not market_dir.is_dir():
        return []

    symbols = []
    for exchange_dir in sorted(market_dir.iterdir()):
        if not exchange_dir.is_dir():
            continue
        exchange = exchange_dir.name
        for symbol_dir in sorted(exchange_dir.iterdir()):
            if not symbol_dir.is_dir():
                continue
            symbol = symbol_dir.name.replace("_", "/")
            timeframes = [
                p.stem for p in sorted(symbol_dir.glob("*.parquet"))
            ]
            if timeframes:
                symbols.append({
                    "exchange": exchange,
                    "symbol": symbol,
                    "timeframes": timeframes,
                })
    return symbols


@router.get("/", response_class=HTMLResponse)
async def market_data_explorer(
    request: Request,
    exchange: str | None = Query(None),
    symbol: str | None = Query(None),
    timeframe: str | None = Query(None),
):
    """Market data explorer with symbol and timeframe selection."""
    templates = request.app.state.templates
    data_dir: Path = request.app.state.data_dir

    available = _discover_symbols(data_dir)

    # If a specific symbol is selected, load its data summary
    data_summary: dict | None = None
    if exchange and symbol and timeframe:
        try:
            from data.store import MarketDataStore

            store = MarketDataStore(data_dir / "market")
            date_range = store.get_date_range(exchange, symbol, timeframe)
            if date_range is not None:
                start, end = date_range
                data_summary = {
                    "exchange": exchange,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "start": str(start),
                    "end": str(end),
                }
        except Exception:
            pass

    return templates.TemplateResponse(
        "market_data.html",
        {
            "request": request,
            "available": available,
            "selected_exchange": exchange,
            "selected_symbol": symbol,
            "selected_timeframe": timeframe,
            "data_summary": data_summary,
        },
    )
