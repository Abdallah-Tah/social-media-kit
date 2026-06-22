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
    if post_kind != "news":
        return False, "LinkedIn skipped: policy allows news posts only."
    data = _read()
    today = _today()
    if today in data:
        prior = data[today]
        return False, (
            "LinkedIn skipped: daily news post already used"
            f" ({prior.get('kind', 'news')} {prior.get('id', '')})."
        )
    return True, "LinkedIn allowed."


def mark_posted(kind: str | None = None, post_id: str = "") -> None:
    data = _read()
    data[_today()] = {
        "kind": (kind or os.environ.get("LINKEDIN_POST_KIND") or "news").strip().lower(),
        "id": post_id,
        "posted_at": _dt.datetime.now(tz=LOCAL_TZ).isoformat(timespec="seconds"),
    }
    _write(data)
