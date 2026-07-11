"""Feed API route handlers — browse and act on Google News / HN / Reddit items."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FEED_DIR = ROOT / "content" / "feed"
SCRIPTS_DIR = ROOT / "scripts"


def _ensure_scripts_path() -> None:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))


def _load_latest_feed() -> dict[str, Any]:
    if not FEED_DIR.exists():
        return {"generated_at": None, "count": 0, "items": []}
    snapshots = sorted(FEED_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    # Skip seen.json
    snapshots = [p for p in snapshots if p.name != "seen.json"]
    if not snapshots:
        return {"generated_at": None, "count": 0, "items": []}
    try:
        data = json.loads(snapshots[0].read_text(encoding="utf-8"))
        data["snapshot_file"] = snapshots[0].name
        return data
    except (json.JSONDecodeError, OSError):
        return {"generated_at": None, "count": 0, "items": []}


def _list_snapshots() -> list[dict[str, Any]]:
    if not FEED_DIR.exists():
        return []
    snapshots = sorted(FEED_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in snapshots:
        if p.name == "seen.json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({"name": p.name, "generated_at": data.get("generated_at"), "count": data.get("count", 0)})
        except (json.JSONDecodeError, OSError):
            continue
    return out[:10]


def register_routes(
    path: str,
    query: dict[str, list[str]],
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if path == "/api/feed":
        snapshot = (query.get("snapshot") or [None])[0]
        if snapshot:
            p = FEED_DIR / snapshot
            if not p.exists() or not p.name.endswith(".json") or p.name == "seen.json":
                return {"error": "not found"}
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                data["snapshot_file"] = p.name
                return {"ok": True, **data}
            except (json.JSONDecodeError, OSError):
                return {"error": "not found"}
        data = _load_latest_feed()
        return {"ok": True, **data, "snapshots": _list_snapshots()}

    if path == "/api/feed/run":
        _ensure_scripts_path()
        try:
            from .feed import build_feed, save_feed
            dry_run = (body or {}).get("dry_run", True)
            limit = int((body or {}).get("limit", 20))
            items = build_feed(limit=limit, use_llm=not dry_run)
            if not dry_run:
                saved = save_feed(items)
                saved_name = Path(saved).name if saved else None
            else:
                saved_name = None
            return {
                "ok": True,
                "count": len(items),
                "items": [i.to_dict() for i in items],
                "saved": saved_name,
                "dry_run": dry_run,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    if path == "/api/feed/publish":
        # Create social drafts from a feed item and optionally publish immediately.
        item = (body or {}).get("item", {})
        platforms = (body or {}).get("platforms", [])
        dry_run = (body or {}).get("dry_run", True)
        if not item or not platforms:
            return {"ok": False, "error": "item and platforms are required"}
        return _publish_feed_item(item, platforms, dry_run)

    return {"error": "not found"}


def _publish_feed_item(item: dict[str, Any], platforms: list[str], dry_run: bool) -> dict[str, Any]:
    """Create social drafts from a news feed item and optionally publish them."""
    from .social_drafts import generate_social_drafts, save_social_draft
    from .social_publishers import publish

    title = item.get("title", "Untitled")
    url = item.get("url", "")
    summary = item.get("summary", "") or item.get("title", "")
    source = item.get("source", "")

    body_text = (
        f"**{title}**\n\n{summary}\n\n"
        f"Source: {source}\n{url}"
    )

    drafts = generate_social_drafts(
        source_draft_id=f"feed-{url[:20]}",
        blog_url=url,
        title=title,
        body=body_text,
        platforms=platforms,
    )

    results: dict[str, Any] = {}
    for sd in drafts:
        sd.status = "approved"
        save_social_draft(sd)
        if dry_run:
            results[sd.platform] = {"ok": True, "dry_run": True, "draft_id": sd.draft_id}
        else:
            pub = publish(sd.platform, sd.to_dict(), dry_run=False)
            if pub.get("ok"):
                sd.status = "published"
                sd.published_url = pub.get("published_url", "")
            else:
                sd.status = "failed"
                sd.error = pub.get("error", "publish failed")
            save_social_draft(sd)
            results[sd.platform] = {**pub, "draft_id": sd.draft_id}

    return {"ok": True, "results": results, "dry_run": dry_run}
