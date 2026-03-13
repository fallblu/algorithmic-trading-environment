"""Editor routes — unified code editor for strategies, portfolios, and user modules."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from modules.discovery import discover_user_modules
from modules.loader import ensure_init_file, run_module_file
from portfolio.storage import PortfolioStorage

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@router.get("/")
async def editor_page(
    request: Request,
    portfolio: str | None = None,
    mode: str = "portfolio",
):
    templates = request.app.state.templates
    state = request.app.state.app_state
    lib_dir: Path = request.app.state.lib_dir

    # Strategy templates
    tdir = lib_dir / "strategy" / "templates"
    strategy_templates = sorted(
        f.stem for f in tdir.glob("*.py") if not f.name.startswith("_")
    ) if tdir.is_dir() else []

    # Portfolios for dropdown
    storage = PortfolioStorage(state)
    portfolios = [p.to_dict() for p in storage.list_all()]

    # If portfolio query param, find and preselect it
    initial_portfolio = None
    if portfolio:
        for p in portfolios:
            if p["name"] == portfolio:
                initial_portfolio = p
                mode = "portfolio"
                break

    return templates.TemplateResponse("editor.html", {
        "request": request,
        "templates": strategy_templates,
        "portfolios": portfolios,
        "initial_portfolio": initial_portfolio,
        "initial_mode": mode,
        "active_page": "editor",
    })


# ---------------------------------------------------------------------------
# Portfolio lookup by name (portfolio cards link by name)
# ---------------------------------------------------------------------------

@router.get("/api/portfolio-by-name/{name}")
async def get_portfolio_by_name(name: str, request: Request) -> JSONResponse:
    state = request.app.state.app_state
    storage = PortfolioStorage(state)
    for p in storage.list_all():
        if p.name == name:
            return JSONResponse(p.to_dict())
    return JSONResponse({"error": "Portfolio not found"}, status_code=404)


# ---------------------------------------------------------------------------
# Strategy source files  (scan strategy/templates/)
# ---------------------------------------------------------------------------

def _templates_dir(request: Request) -> Path:
    lib_dir: Path = request.app.state.lib_dir
    return lib_dir / "strategy" / "templates"


@router.get("/api/strategies")
async def list_strategies(request: Request) -> JSONResponse:
    try:
        tdir = _templates_dir(request)
        if not tdir.is_dir():
            return JSONResponse({"strategies": []})
        files = sorted(
            f.stem for f in tdir.glob("*.py") if not f.name.startswith("_")
        )
        return JSONResponse({"strategies": files})
    except Exception as exc:
        log.exception("Failed to list strategies")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/strategies/{name}")
async def get_strategy_source(name: str, request: Request) -> JSONResponse:
    try:
        path = _templates_dir(request) / f"{name}.py"
        if not path.is_file():
            return JSONResponse({"error": "Strategy not found"}, status_code=404)
        source = path.read_text(encoding="utf-8")
        return JSONResponse({"name": name, "source": source})
    except Exception as exc:
        log.exception("Failed to read strategy %s", name)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/strategies/{name}")
async def save_strategy_source(name: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
        source = body.get("source", "")
        path = _templates_dir(request) / f"{name}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return JSONResponse({"ok": True, "name": name})
    except Exception as exc:
        log.exception("Failed to save strategy %s", name)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# User modules
# ---------------------------------------------------------------------------

@router.get("/api/modules")
async def list_modules(request: Request) -> JSONResponse:
    lib_dir: Path = request.app.state.lib_dir
    try:
        modules = discover_user_modules(lib_dir)
        return JSONResponse({
            "modules": [
                {
                    "name": m.name,
                    "files": m.files,
                    "charts": list(m.charts.keys()),
                }
                for m in modules
            ],
        })
    except Exception as exc:
        log.exception("Failed to list modules")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/modules/{name}/files")
async def list_module_files(name: str, request: Request) -> JSONResponse:
    lib_dir: Path = request.app.state.lib_dir
    module_dir = lib_dir / name
    if not module_dir.is_dir():
        return JSONResponse({"error": "Module not found"}, status_code=404)
    try:
        files = sorted(f.name for f in module_dir.glob("*.py"))
        return JSONResponse({"module": name, "files": files})
    except Exception as exc:
        log.exception("Failed to list files for module %s", name)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/modules/{name}/files/{filename}")
async def get_module_file(
    name: str, filename: str, request: Request,
) -> JSONResponse:
    lib_dir: Path = request.app.state.lib_dir
    path = lib_dir / name / filename
    if not path.is_file():
        return JSONResponse({"error": "File not found"}, status_code=404)
    try:
        content = path.read_text(encoding="utf-8")
        return JSONResponse({"module": name, "filename": filename, "content": content})
    except Exception as exc:
        log.exception("Failed to read %s/%s", name, filename)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/modules/{name}/files/{filename}")
async def save_module_file(
    name: str, filename: str, request: Request,
) -> JSONResponse:
    lib_dir: Path = request.app.state.lib_dir
    module_dir = lib_dir / name
    if not module_dir.is_dir():
        return JSONResponse({"error": "Module not found"}, status_code=404)
    try:
        body = await request.json()
        content = body.get("content", "")
        path = module_dir / filename
        path.write_text(content, encoding="utf-8")
        return JSONResponse({"ok": True, "module": name, "filename": filename})
    except Exception as exc:
        log.exception("Failed to save %s/%s", name, filename)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/modules/{name}/run/{filename}")
async def run_module(name: str, filename: str, request: Request) -> JSONResponse:
    lib_dir: Path = request.app.state.lib_dir
    path = lib_dir / name / filename
    if not path.is_file():
        return JSONResponse({"error": "File not found"}, status_code=404)
    try:
        stdout, stderr = run_module_file(path)
        return JSONResponse({"stdout": stdout, "stderr": stderr})
    except Exception as exc:
        log.exception("Failed to run %s/%s", name, filename)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/modules/create/{name}")
async def create_module(name: str, request: Request) -> JSONResponse:
    lib_dir: Path = request.app.state.lib_dir
    module_dir = lib_dir / name
    if module_dir.exists():
        return JSONResponse({"error": "Module already exists"}, status_code=409)
    try:
        module_dir.mkdir(parents=True, exist_ok=True)
        ensure_init_file(module_dir)
        return JSONResponse({"ok": True, "name": name}, status_code=201)
    except Exception as exc:
        log.exception("Failed to create module %s", name)
        return JSONResponse({"error": str(exc)}, status_code=500)
