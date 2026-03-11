"""Shared utilities for workflow function nodes."""

import sys
from pathlib import Path


def ensure_lib_path(env):
    """Add lib/ to sys.path for workflow function nodes (they run in-process)."""
    lib_path = str(Path(env.path) / "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
