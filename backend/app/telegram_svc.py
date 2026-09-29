"""Posts to one Telegram channel. Missing credentials are a quiet skip."""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

log = logging.getLogger("desk.telegram")


def configured() -> bool:
    cfg = get_settings()
    return bool(cfg.telegram_bot_token.strip() and cfg.telegram_channel_id.strip())


def send(text: str) -> bool:
    cfg = get_settings()
    token = cfg.telegram_bot_token.strip()
    channel = cfg.telegram_channel_id.strip()
    if not token or not channel:
        log.info("Telegram is not configured. Signal stayed on the dashboard.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = httpx.post(
            url,
            json={"chat_id": channel, "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        log.warning("Telegram request failed: %s", exc)
        return False
    if response.status_code >= 300:
        log.warning("Telegram rejected the message: %s %s", response.status_code, response.text[:300])
        return False
    return True
