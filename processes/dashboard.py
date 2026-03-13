"""Dashboard process — serve the FastAPI trading dashboard."""

from __future__ import annotations

import logging

from persistra import process, state

log = logging.getLogger(__name__)


@process("daemon")
def dashboard(host: str = "127.0.0.1", port: str = "8050", auth_token: str = ""):
    """Serve the trading dashboard.

    Parameters:
        host: Bind host (default 127.0.0.1).
        port: Bind port (default 8050).
        auth_token: Authentication token (empty = no auth).
    """
    import uvicorn
    from pathlib import Path

    from dashboard.app import create_app

    s = state()
    lib_dir = Path(__file__).parent.parent / "lib"

    app = create_app(
        state=s,
        auth_token=auth_token,
        lib_dir=lib_dir,
    )

    log.info("Starting dashboard on %s:%s", host, port)
    uvicorn.run(app, host=host, port=int(port), log_level="info")
