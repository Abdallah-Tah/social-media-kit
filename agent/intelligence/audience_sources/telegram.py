"""Telegram message/comment collector for Layer 2."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from ..models import AudienceSignal


def _get_bot_token() -> str | None:
    return os.getenv("TELEGRAM_BOT_TOKEN")


def _get_chat_id() -> str | None:
    return os.getenv("TELEGRAM_CHAT_ID")


def _parse_unix_timestamp(value: int | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except Exception:
        return None


def fetch_telegram_messages(
    bot_token: str,
    chat_id: str,
    limit: int = 200,
) -> list[AudienceSignal]:
    """Fetch messages from a Telegram chat using the Bot API.

    Uses getUpdates with offset. Only returns messages from the configured chat.
    """
    signals: list[AudienceSignal] = []
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        resp = requests.get(
            url,
            params={"chat_id": chat_id, "limit": limit},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return []

    if not data.get("ok"):
        return []

    for update in data.get("result", []):
        message = update.get("message") or update.get("channel_post")
        if not message:
            continue
        # Filter to the requested chat if possible.
        msg_chat = message.get("chat", {})
        if str(msg_chat.get("id", "")) != str(chat_id):
            continue

        text = message.get("text") or message.get("caption", "")
        if not text or not text.strip():
            continue
        text = text.strip()
        if len(text) < 8:
            continue
        # Ignore bot/system messages.
        from_user = message.get("from", {})
        if from_user.get("is_bot"):
            continue

        signals.append(
            AudienceSignal(
                platform="telegram",
                text=text,
                author=from_user.get("username", from_user.get("first_name", "")),
                url="",
                published_at=_parse_unix_timestamp(message.get("date")),
                source_id=str(message.get("message_id", "")),
                engagement_count=0,
                metadata={"chat_id": str(chat_id), "update_id": update.get("update_id")},
            )
        )
    return signals


def collect_telegram_signals(
    bot_token: str | None = None,
    chat_id: str | None = None,
    limit: int = 200,
) -> list[AudienceSignal]:
    """Collect Telegram audience signals if credentials are available."""
    bot_token = bot_token or _get_bot_token()
    chat_id = chat_id or _get_chat_id()
    if not bot_token or not chat_id:
        return []
    return fetch_telegram_messages(bot_token, chat_id, limit)
