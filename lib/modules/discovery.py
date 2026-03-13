"""Module discovery — scan lib/ for user-created packages and their __charts__."""

from __future__ import annotations

import importlib
import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Core packages that are not user-editable
CORE_PACKAGES = frozenset({
    "models", "broker", "data", "strategy", "portfolio",
    "execution", "risk", "analytics", "charts", "modules", "dashboard",
})


@dataclass
class ModuleInfo:
    """Information about a discovered user module."""

    name: str
    path: Path
    files: list[str] = field(default_factory=list)
    charts: dict[str, dict] = field(default_factory=dict)


def discover_user_modules(lib_dir: Path) -> list[ModuleInfo]:
    """Scan lib/ for user-created packages (non-core directories)."""
    modules: list[ModuleInfo] = []

    if not lib_dir.is_dir():
        return modules

    for entry in sorted(lib_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_"):
            continue
        if entry.name in CORE_PACKAGES:
            continue

        py_files = sorted(f.name for f in entry.glob("*.py") if not f.name.startswith("_"))
        info = ModuleInfo(name=entry.name, path=entry, files=py_files)

        # Try to discover __charts__ exports
        info.charts = _discover_charts(entry)

        modules.append(info)
        log.debug("Discovered user module: %s (%d files)", entry.name, len(py_files))

    return modules


def _discover_charts(package_dir: Path) -> dict[str, dict]:
    """Import module files and collect __charts__ exports."""
    all_charts: dict[str, dict] = {}

    for py_file in sorted(package_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_name = f"{package_dir.name}.{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                charts = getattr(module, "__charts__", None)
                if isinstance(charts, dict):
                    for key, config in charts.items():
                        prefixed_key = f"{package_dir.name}.{key}"
                        all_charts[prefixed_key] = config
                        log.debug("Found chart series: %s", prefixed_key)
        except Exception as e:
            log.warning("Failed to load module %s: %s", module_name, e)

    return all_charts


def is_core_package(name: str) -> bool:
    """Check if a package name is a core (non-editable) package."""
    return name in CORE_PACKAGES
