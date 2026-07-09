"""Draft workspace for smkit intelligence.

Persistent draft records that bridge intelligence opportunities to later
content publishing. No live publishing here.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DRAFTS_DIR = ROOT / "content" / "drafts"
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)


VALID_STATUSES = {"draft", "reviewed", "approved", "published"}


@dataclass
class ContentDraft:
    draft_id: str = ""
    source_cluster: dict[str, Any] = field(default_factory=dict)
    recommendation: dict[str, Any] = field(default_factory=dict)
    content_type: str = "blog"
    title: str = ""
    slug: str = ""
    brief: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    source_urls: list[str] = field(default_factory=list)
    status: str = "draft"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.draft_id:
            self.draft_id = str(uuid.uuid4())[:8]
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if self.status not in VALID_STATUSES:
            self.status = "draft"
        if not self.slug and self.title:
            self.slug = _slugify(self.title)

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "source_cluster": self.source_cluster,
            "recommendation": self.recommendation,
            "content_type": self.content_type,
            "title": self.title,
            "slug": self.slug,
            "brief": self.brief,
            "body": self.body,
            "source_urls": self.source_urls,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def touch(self) -> None:
        self.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:60] or "draft"


def _draft_path(draft_id: str) -> Path:
    if ".." in draft_id or "/" in draft_id or "\\" in draft_id:
        raise ValueError("invalid draft id")
    return DRAFTS_DIR / f"{draft_id}.json"


def create_draft(card: dict[str, Any], brief: dict[str, Any]) -> ContentDraft:
    """Create a new draft from an intelligence card + generated brief."""
    cluster = card.get("cluster", {})
    rec = card.get("recommendation", {})
    draft = ContentDraft(
        source_cluster=cluster,
        recommendation=rec,
        content_type=brief.get("content_type", rec.get("recommendation", "blog")),
        title=brief.get("title", "Untitled Draft"),
        brief=brief,
        body=brief.get("markdown", "") or brief.get("draft_body", ""),
        source_urls=cluster.get("urls", []),
    )
    save_draft(draft)
    return draft


def save_draft(draft: ContentDraft) -> Path:
    """Persist a draft JSON."""
    draft.touch()
    path = _draft_path(draft.draft_id)
    path.write_text(json.dumps(draft.to_dict(), indent=2), encoding="utf-8")
    return path


def load_draft(draft_id: str) -> ContentDraft | None:
    """Load a draft by id."""
    path = _draft_path(draft_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ContentDraft(**data)
    except (json.JSONDecodeError, TypeError):
        return None


def update_draft(draft_id: str, fields: dict[str, Any]) -> ContentDraft | None:
    """Update draft fields and persist."""
    draft = load_draft(draft_id)
    if draft is None:
        return None
    allowed = {"title", "slug", "body", "status"}
    for key, value in fields.items():
        if key in allowed and hasattr(draft, key):
            setattr(draft, key, value)
    if "status" in fields and fields["status"] not in VALID_STATUSES:
        return None
    draft.touch()
    save_draft(draft)
    return draft


def transition_status(draft_id: str, new_status: str) -> ContentDraft | None:
    """Move a draft through its status workflow."""
    if new_status not in VALID_STATUSES:
        return None
    return update_draft(draft_id, {"status": new_status})


def list_drafts(status: str | None = None) -> list[dict[str, Any]]:
    """List all drafts, optionally filtered by status."""
    out = []
    for p in sorted(DRAFTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if status is None or data.get("status") == status:
                out.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return out


def delete_draft(draft_id: str) -> bool:
    """Delete a draft file."""
    path = _draft_path(draft_id)
    if path.exists():
        path.unlink()
        return True
    return False
