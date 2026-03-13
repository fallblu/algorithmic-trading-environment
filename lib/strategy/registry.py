"""Strategy registry — register, discover, and look up strategies."""

from __future__ import annotations

import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Callable

from strategy.base import Strategy

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type[Strategy]] = {}


def register(name: str) -> Callable:
    """Decorator to register a strategy class by name."""
    def decorator(cls: type[Strategy]) -> type[Strategy]:
        if not issubclass(cls, Strategy):
            raise TypeError(f"{cls.__name__} must be a subclass of Strategy")
        _REGISTRY[name] = cls
        log.debug("Registered strategy: %s -> %s", name, cls.__name__)
        return cls
    return decorator


def get_strategy(name: str) -> type[Strategy]:
    """Look up a registered strategy by name."""
    if name not in _REGISTRY:
        raise KeyError(f"Strategy '{name}' not found. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]


def list_strategies() -> list[str]:
    """Return list of registered strategy names."""
    return sorted(_REGISTRY.keys())


def discover_strategies(strategies_dir: Path) -> None:
    """Import all .py files in a directory to trigger @register decorators."""
    if not strategies_dir.is_dir():
        return

    for py_file in sorted(strategies_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"strategies.{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                log.debug("Discovered strategy module: %s", py_file.name)
        except Exception as e:
            log.warning("Failed to load strategy %s: %s", py_file.name, e)
