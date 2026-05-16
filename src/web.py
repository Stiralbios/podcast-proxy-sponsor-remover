from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles


def create_app(podcasts_dir: Path) -> Starlette:
    app = Starlette()
    app.mount("/", StaticFiles(directory=str(podcasts_dir), html=False))
    return app
