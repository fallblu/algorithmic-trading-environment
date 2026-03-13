"""Module loader — import and validate user modules."""

from __future__ import annotations

import importlib
import importlib.util
import io
import logging
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

log = logging.getLogger(__name__)


def load_module(module_path: Path) -> object:
    """Import a Python module from a file path."""
    module_name = f"user_modules.{module_path.parent.name}.{module_path.stem}"

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_module_file(file_path: Path) -> tuple[str, str]:
    """Execute a module file and capture stdout/stderr.

    Returns (stdout_output, stderr_output).
    """
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    try:
        source = file_path.read_text()
        compiled = compile(source, str(file_path), "exec")

        namespace = {"__file__": str(file_path), "__name__": "__main__"}

        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compiled, namespace)

    except Exception as e:
        stderr_buf.write(f"\n{type(e).__name__}: {e}\n")

    return stdout_buf.getvalue(), stderr_buf.getvalue()


def ensure_init_file(package_dir: Path) -> None:
    """Create __init__.py if it doesn't exist."""
    init_path = package_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text("from __future__ import annotations\n")
