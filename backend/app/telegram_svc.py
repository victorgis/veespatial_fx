"""Posts to one Telegram channel. Missing credentials are a quiet skip."""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

log = logging.getLogger("desk.telegram")
_last_error = ""


def configured() -> bool:
    cfg = get_settings()
    return bool(cfg.telegram_bot_token.strip() and cfg.telegram_channel_id.strip())


def last_error() -> str:
    return _last_error


def explain_telegram_error(status: int, body: str) -> str:
    folded = body.lower()
    if "chat not found" in folded:
        return (
            "Telegram could not find that chat. Add the bot to the channel as an admin, "
            "then set TELEGRAM_CHANNEL_ID to the channel id. A channel id looks like -100 followed by digits. "
            "A public channel can use its @name once the bot is an admin."
        )
    if "not enough rights" in folded or "forbidden" in folded or "bot was blocked" in folded:
        return "Telegram refused the bot. Make it an admin of the channel and allow it to post messages."
    return f"Telegram rejected the message ({status})."


def send(text: str) -> bool:
    global _last_error
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
        _last_error = "Telegram could not be reached."
        log.warning("Telegram request failed: %s", type(exc).__name__)
        return False
    if response.status_code >= 300:
        _last_error = explain_telegram_error(response.status_code, response.text[:300])
        log.warning("Telegram rejected the message: %s", _last_error)
        return False
    _last_error = ""
    return True
