"""Dashboard process — serves the interactive web dashboard."""

import logging
import sys
import threading
from pathlib import Path

from persistra import process

log = logging.getLogger(__name__)

# Module-level state persists between daemon ticks
_server = None
_server_thread = None


@process("daemon", interval="10s")
def run(
    env,
    host: str = "127.0.0.1",
    port: int = 8050,
):
    """Start the trading dashboard web server.

    Runs as a Persistra daemon process using uvicorn in a background thread.
    The first tick starts the server; subsequent ticks verify it is still alive.
    """
    global _server, _server_thread

    # If the server thread is already running, nothing to do.
    if _server_thread is not None and _server_thread.is_alive():
        return

    lib_path = str(Path(env.path) / "lib")
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    try:
        import uvicorn
    except ImportError:
        log.error("uvicorn not installed. Install with: pip install uvicorn")
        return

    from dashboard.app import create_app
    from helpers import market_data_dir

    data_dir = market_data_dir(env.path)
    app = create_app(env=env, data_dir=data_dir)

    port = int(port)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    _server = uvicorn.Server(config)

    _server_thread = threading.Thread(target=_server.run, daemon=True)
    _server_thread.start()
    log.info("Starting dashboard on %s:%d", host, port)
