"""Signal Desk HTTP server."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.routers import auth, dashboard, ea, settings, signals, system

log = logging.getLogger("desk")


def _static_dir() -> Path | None:
    cfg = get_settings()
    here = Path(__file__).resolve()
    candidates = []
    if cfg.static_dir.strip():
        candidates.append(Path(cfg.static_dir.strip()))
    candidates += [
        here.parents[2] / "frontend" / "dist",
        here.parents[1] / "static",
        Path("/app/static"),
    ]
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx logs the full request URL at INFO, which would include the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    cfg = get_settings()
    if cfg.env == "production" and cfg.jwt_secret == "dev-only-change-me":
        raise RuntimeError("Set JWT_SECRET before running with ENV=production.")
    if cfg.env == "production" and cfg.database_url.startswith("sqlite"):
        log.warning(
            "DATABASE_URL is still SQLite. Set it to your Neon (or other Postgres) URL. "
            "The Render disk is wiped on redeploy, and a scan can lock the file."
        )
    init_db()
    scheduler = None
    if cfg.scheduler_enabled:
        from app.scheduler import start_scheduler

        scheduler = start_scheduler()
        log.info("Scanner every %s seconds", max(60, cfg.scan_interval_seconds))
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Signal Desk", lifespan=lifespan)
_cfg = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cfg.cors_origin_list or ["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(settings.router)
app.include_router(signals.router)
app.include_router(ea.router)
app.include_router(system.router)


@app.get("/health", include_in_schema=False)
def root_health() -> dict:
    """Render's default check is /health. The API check stays at /api/health."""
    from app.database import session_scope
    from app.models import BotConfig

    db = session_scope()
    try:
        db.query(BotConfig).first()
    finally:
        db.close()
    return {"ok": True}


@app.middleware("http")
async def security_headers(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


_static = _static_dir()
if _static is not None:
    assets = _static / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not found.")
        candidate = (_static / full_path).resolve()
        if full_path and candidate.is_file() and str(candidate).startswith(str(_static.resolve())):
            return FileResponse(candidate)
        return FileResponse(_static / "index.html")
