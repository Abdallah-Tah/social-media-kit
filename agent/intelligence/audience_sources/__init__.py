"""Audience signal collectors for the Content Intelligence Engine."""
from __future__ import annotations

from .telegram import collect_telegram_signals
from .website import collect_website_signals
from .youtube import collect_youtube_signals

__all__ = [
    "collect_telegram_signals",
    "collect_website_signals",
    "collect_youtube_signals",
]
