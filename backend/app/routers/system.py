"""Health, markets, the watchlist, scans, and copier downloads."""

import hmac
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import BotConfig, User
from app.present import market_dicts
from app.scan import run_scan
from app.schemas import MarketOut, ScanResultOut, WatchlistIn
from app.security import current_user, require_admin
from app.symbols import BY_ID

router = APIRouter(prefix="/api", tags=["system"])


def experts_dir() -> Path:
    configured = get_settings().experts_dir.strip()
    here = Path(__file__).resolve()
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates += [
        here.parents[3] / "experts",  # repo/experts when this file is backend/app/routers
        here.parents[2] / "experts",
        Path("/app/experts"),
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.query(BotConfig).first()
    return {"ok": True}


@router.get("/markets", response_model=list[MarketOut])
def markets(_user: User = Depends(current_user)) -> list[MarketOut]:
    return [MarketOut(**row) for row in market_dicts()]


@router.put("/system/watchlist")
def save_watchlist(body: WatchlistIn, _admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    if not body.enabled_symbols:
        raise HTTPException(status_code=400, detail="Watch at least one market.")
    for symbol_id in body.enabled_symbols:
        if symbol_id not in BY_ID:
            raise HTTPException(status_code=400, detail=f"Unknown market '{symbol_id}'.")
    row = db.get(BotConfig, 1)
    if row is None:
        row = BotConfig(id=1, enabled_symbols="")
        db.add(row)
    row.enabled_symbols = ",".join(dict.fromkeys(body.enabled_symbols))
    db.commit()
    return {"enabled_symbols": body.enabled_symbols}


@router.post("/system/scan", response_model=ScanResultOut)
def scan(
    x_cron_key: str | None = Header(None),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> ScanResultOut:
    cfg = get_settings()
    allowed = bool(
        cfg.cron_key
        and x_cron_key
        and len(x_cron_key) == len(cfg.cron_key)
        and hmac.compare_digest(x_cron_key, cfg.cron_key)
    )
    if not allowed:
        user = current_user(authorization=authorization, db=db)
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Only the account that created this desk can run a scan.")
    result = run_scan()
    return ScanResultOut(**result)


@router.get("/downloads/{name}")
def download(name: str) -> FileResponse:
    if name not in ("SignalBridge.mq5", "SignalBridge.mq4"):
        raise HTTPException(status_code=404, detail="That file is not available.")
    path = experts_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The copier file is not on this server.")
    return FileResponse(path, filename=name, media_type="text/plain")
