"""App factory. Initializes the DB on startup, mounts static, serves the PWA manifest and
service worker at the root scope, and includes every feature router."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, export, history, library, prspage, sessions, settings, settingspage, web

STATIC_DIR = os.path.join(settings.BASE_DIR, "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest():
        return FileResponse(os.path.join(STATIC_DIR, "manifest.webmanifest"),
                            media_type="application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        # Served from root so its scope covers the whole app.
        return FileResponse(os.path.join(STATIC_DIR, "sw.js"), media_type="application/javascript",
                            headers={"Cache-Control": "no-cache"})

    for module in (sessions, prspage, history, library, settingspage, export):
        app.include_router(module.router)
    return app


app = create_app()
