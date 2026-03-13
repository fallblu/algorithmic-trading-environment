"""Dashboard process — serve the FastAPI trading dashboard."""

from __future__ import annotations

import logging

from persistra import process

log = logging.getLogger(__name__)


@process("daemon")
def run(env, host: str = "127.0.0.1", port: str = "8050", auth_token: str = ""):
    """Serve the trading dashboard.

    Parameters:
        host: Bind host (default 127.0.0.1).
        port: Bind port (default 8050).
        auth_token: Authentication token (empty = no auth).
    """
    import sys
    import uvicorn
    from pathlib import Path

    # The runner registers this process file as sys.modules["dashboard"], which
    # shadows the lib/dashboard package. Pop it so the package is found instead.
    sys.modules.pop("dashboard", None)
    from dashboard.app import create_app

    lib_dir = Path(__file__).parent.parent / "lib"

    app = create_app(
        state=env.state,
        auth_token=auth_token,
        lib_dir=lib_dir,
    )

    log.info("Starting dashboard on %s:%s", host, port)
    uvicorn.run(app, host=host, port=int(port), log_level="info")
