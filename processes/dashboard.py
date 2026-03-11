"""Dashboard process — serves the interactive web dashboard."""

import logging
import sys
from pathlib import Path

from persistra import process

log = logging.getLogger(__name__)


@process("daemon")
def run(
    env,
    host: str = "127.0.0.1",
    port: int = 8050,
):
    """Start the trading dashboard web server.

    Runs as a Persistra daemon process using uvicorn.
    """
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

    log.info("Starting dashboard on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
