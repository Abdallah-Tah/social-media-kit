"""Published-posts log + dedupe.

Records every completed run to `content/published.json` so you have a track
record and can avoid re-publishing the same topic. Used by `smkit run`
(dedupe + record) and `smkit history` (view).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .config import ROOT

HISTORY_PATH = ROOT / "content" / "published.json"


def _normalize(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (topic or "").lower()).strip()


def load() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def has_topic(topic: str) -> bool:
    """True if a run with an equivalent topic was already recorded."""
    if not topic:
        return False
    norm = _normalize(topic)
    return any(_normalize(e.get("topic", "")) == norm for e in load())


def record(entry: dict) -> None:
    entries = load()
    entry.setdefault("date", datetime.now(timezone.utc).isoformat())
    entries.append(entry)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
