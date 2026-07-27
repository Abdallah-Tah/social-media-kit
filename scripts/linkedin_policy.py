#!/usr/bin/env python3
"""LinkedIn posting policy.

Current rule: one LinkedIn post per local day, and only for developer news.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
LEDGER = KIT / "content" / "linkedin_daily_posts.json"
LOCAL_TZ = _dt.datetime.now().astimezone().tzinfo
MAX_DAILY = 5  # back-compat alias (news limit)
# Per-kind daily LinkedIn limits. News runs high on purpose: the blog and feed
# are a live demonstration of what the bot produces, so throughput IS the point.
# Format rotation (scripts/content_formats.py) is what keeps five posts a day
# from reading as five copies of the same post.
DAILY_LIMITS = {"news": 5, "tutorial": 1, "roundup": 1, "project": 2}


def _day_entries(data: dict, today: str) -> list:
    """Posts logged for `today`, tolerating the legacy single-dict format."""
    v = data.get(today)
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _today() -> str:
    return _dt.datetime.now(tz=LOCAL_TZ).date().isoformat()


def _read() -> dict:
    try:
        return json.loads(LEDGER.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, indent=2, sort_keys=True))


def allowed(kind: str | None = None) -> tuple[bool, str]:
    post_kind = (kind or os.environ.get("LINKEDIN_POST_KIND") or "").strip().lower()
    if post_kind not in DAILY_LIMITS:
        return False, f"LinkedIn skipped: policy allows {'/'.join(DAILY_LIMITS)} posts only."
    today = _today()
    limit = DAILY_LIMITS[post_kind]
    same = [e for e in _day_entries(_read(), today) if (e.get("kind") or "news") == post_kind]
    if len(same) >= limit:
        return False, f"LinkedIn skipped: daily {post_kind} limit reached ({len(same)}/{limit})."
    return True, f"LinkedIn allowed ({len(same) + 1}/{limit} {post_kind})."


def mark_posted(kind: str | None = None, post_id: str = "") -> None:
    data = _read()
    today = _today()
    entries = _day_entries(data, today)
    entries.append({
        "kind": (kind or os.environ.get("LINKEDIN_POST_KIND") or "news").strip().lower(),
        "id": post_id,
        "posted_at": _dt.datetime.now(tz=LOCAL_TZ).isoformat(timespec="seconds"),
    })
    data[today] = entries
    _write(data)
