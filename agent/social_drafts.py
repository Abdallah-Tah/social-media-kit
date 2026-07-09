"""Social draft generator for published blog posts.

Creates editable, per-platform post drafts from a published draft's blog_url.
No live publishing happens here.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOCIAL_DRAFTS_DIR = ROOT / "content" / "social_drafts"
SOCIAL_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

VALID_STATUSES = {"draft", "approved", "scheduled", "published"}
SUPPORTED_PLATFORMS = {
    "linkedin", "facebook", "x", "threads", "reddit", "newsletter", "youtube",
}


@dataclass
class SocialDraft:
    draft_id: str = ""
    source_draft_id: str = ""
    platform: str = ""
    blog_url: str = ""
    title: str = ""
    text: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    status: str = "draft"
    published_url: str = ""
    published_at: str = ""
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "source_draft_id": self.source_draft_id,
            "platform": self.platform,
            "blog_url": self.blog_url,
            "title": self.title,
            "text": self.text,
            "description": self.description,
            "tags": self.tags,
            "hashtags": self.hashtags,
            "status": self.status,
            "published_url": self.published_url,
            "published_at": self.published_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def touch(self) -> None:
        self.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()


def _social_draft_path(draft_id: str) -> Path:
    if ".." in draft_id or "/" in draft_id or "\\" in draft_id:
        raise ValueError("invalid draft id")
    return SOCIAL_DRAFTS_DIR / f"{draft_id}.json"


def _extract_summary(body: str, max_chars: int = 240) -> str:
    """Return a short plain-text summary from markdown-ish body."""
    import re
    text = re.sub(r"[#*`_\[\]()]", "", body)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rsplit(" ", 1)[0] + "..."


def _format_hashtags(tags: list[str]) -> list[str]:
    return [t.lower().replace(" ", "") for t in tags if t]


def generate_social_drafts(
    source_draft_id: str,
    blog_url: str,
    title: str,
    body: str,
    platforms: list[str],
    tags: list[str] | None = None,
) -> list[SocialDraft]:
    """Generate social post drafts for selected platforms.

    Returns an empty list if blog_url is missing or platforms is empty.
    """
    if not blog_url or not platforms:
        return []

    summary = _extract_summary(body, 240)
    hashtags = _format_hashtags(tags or [])
    hashtag_str = " ".join(f"#{h}" for h in hashtags)

    builders = {
        "linkedin": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="linkedin",
            blog_url=blog_url,
            title=title,
            text=f"{title}\n\n{summary}\n\nWhat do you think? {blog_url}",
            description=summary,
            hashtags=hashtags,
        ),
        "facebook": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="facebook",
            blog_url=blog_url,
            title=title,
            text=f"{title}\n\n{summary}\n\nRead more: {blog_url}",
            description=summary,
            hashtags=hashtags,
        ),
        "x": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="x",
            blog_url=blog_url,
            title=title,
            text=f"{title}\n\n{summary[:180]}\n\n{blog_url} {hashtag_str}",
            description=summary[:180],
            hashtags=hashtags,
        ),
        "threads": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="threads",
            blog_url=blog_url,
            title=title,
            text=f"{title}\n\n{summary}\n\nLink in bio: {blog_url}",
            description=summary,
            hashtags=hashtags,
        ),
        "reddit": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="reddit",
            blog_url=blog_url,
            title=title,
            text=f"{summary}\n\nFull write-up: {blog_url}",
            description=summary,
            hashtags=hashtags,
        ),
        "newsletter": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="newsletter",
            blog_url=blog_url,
            title=title,
            text=f"# {title}\n\n{summary}\n\nRead the full article: {blog_url}",
            description=summary,
            hashtags=hashtags,
        ),
        "youtube": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="youtube",
            blog_url=blog_url,
            title=title,
            text=f"{title} — short covering the latest. Full details in the blog post: {blog_url}",
            description=summary,
            hashtags=hashtags,
        ),
    }

    drafts: list[SocialDraft] = []
    for platform in platforms:
        platform = platform.lower().strip()
        if platform in SUPPORTED_PLATFORMS and platform in builders:
            drafts.append(builders[platform]())
    return drafts


def save_social_draft(draft: SocialDraft) -> Path:
    draft.touch()
    path = _social_draft_path(draft.draft_id)
    path.write_text(json.dumps(draft.to_dict(), indent=2), encoding="utf-8")
    return path


def load_social_draft(draft_id: str) -> SocialDraft | None:
    path = _social_draft_path(draft_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SocialDraft(**data)
    except (json.JSONDecodeError, TypeError):
        return None


def update_social_draft(draft_id: str, fields: dict[str, Any]) -> SocialDraft | None:
    draft = load_social_draft(draft_id)
    if draft is None:
        return None
    allowed = {"title", "text", "description", "tags", "hashtags", "status"}
    for key, value in fields.items():
        if key in allowed and hasattr(draft, key):
            if key in {"tags", "hashtags"} and isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            setattr(draft, key, value)
    if "status" in fields and fields["status"] not in VALID_STATUSES:
        return None
    draft.touch()
    save_social_draft(draft)
    return draft


def list_social_drafts(source_draft_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    out = []
    for p in sorted(SOCIAL_DRAFTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if source_draft_id is not None and data.get("source_draft_id") != source_draft_id:
                continue
            if status is not None and data.get("status") != status:
                continue
            out.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return out


def delete_social_draft(draft_id: str) -> bool:
    path = _social_draft_path(draft_id)
    if path.exists():
        path.unlink()
        return True
    return False


def publish_social_draft(draft_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Publish a single approved social draft to its platform.

    Returns ok, published_url, error. On success, updates the draft with
    published_url, published_at, and status=published. On failure, keeps
    the draft at its current status (expected to be approved).
    """
    from .social_publishers import publish

    draft = load_social_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "social draft not found"}
    if draft.status != "approved":
        return {"ok": False, "error": f"social draft must be approved, current status: {draft.status}"}

    result = publish(draft.platform, draft.to_dict(), dry_run=dry_run)
    if result.get("ok"):
        draft.status = "published"
        draft.published_url = result.get("published_url", "")
        draft.published_at = dt.datetime.now(dt.timezone.utc).isoformat()
        save_social_draft(draft)
    return result


def publish_selected_social_drafts(draft_ids: list[str], dry_run: bool = False) -> dict[str, Any]:
    """Publish multiple approved social drafts. Returns per-id results."""
    results = {}
    for draft_id in draft_ids:
        results[draft_id] = publish_social_draft(draft_id, dry_run=dry_run)
    return {"ok": True, "results": results}


def create_social_drafts_from_blog(
    source_draft_id: str,
    blog_url: str,
    title: str,
    body: str,
    platforms: list[str],
    tags: list[str] | None = None,
) -> list[SocialDraft]:
    """Generate and persist social drafts for a published blog post."""
    drafts = generate_social_drafts(source_draft_id, blog_url, title, body, platforms, tags)
    for d in drafts:
        save_social_draft(d)
    return drafts
