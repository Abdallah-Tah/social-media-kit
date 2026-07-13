"""Telegram notifications for publish events.

Best-effort: a notification failure must never break a publish. Uses
scripts/telegram_poster.py (TELEGRAM_TOKEN / TELEGRAM_BOT_TOKEN + CHAT_ID
from secrets.env).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def notify_publish(text: str) -> bool:
    """Send a publish notification to the user's Telegram. Returns success."""
    try:
        scripts_dir = str(ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from .config import load_env
        load_env()
        import telegram_poster
        result = telegram_poster.post_message(text)
        return bool(result)
    except Exception:
        return False
