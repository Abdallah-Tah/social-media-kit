"""Platform connection health — reads env vars, never publishes."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import load_env

ROOT = Path(__file__).resolve().parents[1]

PLATFORM_SPECS: list[dict[str, Any]] = [
    {"id": "blog",       "name": "Blog",         "env_vars": ["BLOG_API_URL", "BLOG_API_TOKEN"],               "description": "Ghost / WordPress blog API"},
    {"id": "linkedin",   "name": "LinkedIn",      "env_vars": ["LINKEDIN_ACCESS_TOKEN"],                        "description": "Personal feed (cron token method)"},
    {"id": "facebook",   "name": "Facebook",      "env_vars": ["FB_PAGE_ID", "FB_PAGE_TOKEN"],                  "description": "Facebook Page API"},
    {"id": "x",          "name": "X / Twitter",   "env_vars": ["X_API_KEY", "X_API_SECRET"],                   "description": "X API v2"},
    {"id": "threads",    "name": "Threads",        "env_vars": ["THREADS_USER_ID", "THREADS_ACCESS_TOKEN"],      "description": "Threads / Meta API"},
    {"id": "youtube",    "name": "YouTube",        "env_vars": ["YOUTUBE_CLIENT_ID", "YOUTUBE_REFRESH_TOKEN"],   "description": "YouTube Data API v3"},
    {"id": "reddit",     "name": "Reddit",         "env_vars": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],     "description": "Reddit OAuth"},
    {"id": "newsletter", "name": "Newsletter",     "env_vars": [],                                               "description": "Writes local file — no credentials needed"},
]


def _last_publish_for(platform_id: str) -> dict[str, Any]:
    social_dir = ROOT / "content" / "social_drafts"
    if not social_dir.exists():
        return {"last_publish_status": None, "last_publish_at": None, "last_publish_url": None}
    best: dict[str, Any] | None = None
    best_time = ""
    for p in social_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("platform") != platform_id:
                continue
            at = data.get("published_at", "") or data.get("updated_at", "")
            if data.get("status") in ("published", "failed") and at >= best_time:
                best = data
                best_time = at
        except (json.JSONDecodeError, OSError):
            continue
    if best is None:
        return {"last_publish_status": None, "last_publish_at": None, "last_publish_url": None}
    return {
        "last_publish_status": best.get("status"),
        "last_publish_at": best.get("published_at") or best.get("updated_at"),
        "last_publish_url": best.get("published_url"),
        "last_publish_error": best.get("error") if best.get("status") == "failed" else None,
    }


def check_connections() -> list[dict[str, Any]]:
    load_env()
    results = []
    for spec in PLATFORM_SPECS:
        missing = [v for v in spec["env_vars"] if not os.environ.get(v)]
        results.append({
            "id": spec["id"],
            "name": spec["name"],
            "description": spec["description"],
            "env_vars": spec["env_vars"],
            "connected": len(missing) == 0,
            "missing_vars": missing,
            **_last_publish_for(spec["id"]),
        })
    return results
