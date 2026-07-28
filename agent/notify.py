"""Telegram notifications for publish events.

Best-effort: a notification failure must never break a publish. Uses
scripts/telegram_poster.py (TELEGRAM_TOKEN / TELEGRAM_BOT_TOKEN + CHAT_ID
from secrets.env).

Environment isolation
---------------------
Notifications are disabled unless *all* of the following hold:

    SMKIT_ENV == "production"
    SMKIT_NOTIFICATIONS_ENABLED == "1"  (opt-in, even in production)
    not testing / dry-run / shadow / replay / simulated

Tests and local verification must never send production notifications.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ── environment guard ────────────────────────────────────────────────────────

_PRODUCTION_ENVS = {"production", "prod"}
_BLOCKING_MODES = {"dry_run", "test", "replay", "simulated", "shadow"}


def notifications_enabled() -> bool:
    """Return True only when real Telegram notifications are permitted.

    The guard is *deny-by-default*: every condition must explicitly allow
    sending.  A single missing or wrong value silences the notifier.
    """
    env = os.environ.get("SMKIT_ENV", "").strip().lower()
    if env not in _PRODUCTION_ENVS:
        return False
    opt_in = os.environ.get("SMKIT_NOTIFICATIONS_ENABLED", "").strip().lower()
    if opt_in not in ("1", "true", "yes", "on"):
        return False
    mode = os.environ.get("SMKIT_MODE", "").strip().lower()
    if mode in _BLOCKING_MODES:
        return False
    if os.environ.get("SMKIT_TESTING", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    return True


def notify_publish(text: str) -> bool:
    """Send a publish notification to the user's Telegram. Returns success.

    Silently returns False when the environment guard blocks sending.
    """
    if not notifications_enabled():
        return False
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
