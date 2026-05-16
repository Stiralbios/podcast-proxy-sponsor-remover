"""Web server serving static podcast files via Starlette."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: Starlette):
    """ASGI lifespan: start initial sync in a background thread, then serve."""
    sched = getattr(app.state, "sched", None)
    sync_all = getattr(app.state, "sync_all", None)

    if sync_all is not None:
        logger.info("Launching initial sync in background thread")
        t = threading.Thread(target=sync_all, daemon=True)
        t.start()
    else:
        logger.info("No sync function provided, serving only")

    yield

    if sched is not None:
        logger.info("Shutting down scheduler...")
        sched.shutdown(wait=False)


def create_app(podcasts_dir: Path, sched: Any = None, sync_all: Any = None) -> Starlette:
    app = Starlette(lifespan=_lifespan)
    app.state.sched = sched
    app.state.sync_all = sync_all
    app.state.podcasts_dir = podcasts_dir
    app.mount("/", StaticFiles(directory=str(podcasts_dir), html=False))
    return app
