"""Website contact form / message collector for Layer 2."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import AudienceSignal


def _parse_iso_or_string(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return value


def collect_website_signals(path: str | Path | None = None) -> list[AudienceSignal]:
    """Collect website audience signals from a JSON export.

    Expected JSON shape:
    [
      {
        "name": "...",
        "email": "...",
        "message": "...",
        "created_at": "2026-06-18T12:00:00Z"
      }
    ]
    """
    if path is None:
        path = Path.home() / ".openclaw" / "workspace" / "audience" / "website_messages.json"
    path = Path(path)
    if not path.exists():
        return []

    signals: list[AudienceSignal] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return signals

    if not isinstance(raw, list):
        return signals

    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        text = item.get("message") or item.get("comment") or item.get("text", "")
        if not text or not text.strip():
            continue
        text = text.strip()
        if len(text) < 8:
            continue
        signals.append(
            AudienceSignal(
                platform="website",
                text=text,
                author=item.get("name", item.get("email", "")),
                url=item.get("url", ""),
                published_at=_parse_iso_or_string(item.get("created_at", item.get("submitted_at"))),
                source_id=str(item.get("id", idx)),
                engagement_count=0,
                metadata={"email": item.get("email", "")},
            )
        )
    return signals
