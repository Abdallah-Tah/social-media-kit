"""Social draft generator for published blog posts.

Creates editable, per-platform post drafts from a published draft's blog_url.
No live publishing happens here.
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
SOCIAL_DRAFTS_DIR = ROOT / "content" / "social_drafts"
SOCIAL_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

VALID_STATUSES = {"idea", "draft", "needs_review", "approved", "scheduled", "published", "failed"}
_STATUS_ALIASES = {"reviewed": "needs_review"}
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
    scheduled_at: str = ""
    published_url: str = ""
    published_at: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    campaign_id: str = ""

    def __post_init__(self):
        if not self.draft_id:
            self.draft_id = str(uuid.uuid4())[:8]
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        self.status = _STATUS_ALIASES.get(self.status, self.status)
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
            "scheduled_at": self.scheduled_at,
            "published_url": self.published_url,
            "published_at": self.published_at,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": self.history,
            "campaign_id": self.campaign_id,
        }

    def touch(self) -> None:
        self.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()


def _social_draft_path(draft_id: str) -> Path:
    if ".." in draft_id or "/" in draft_id or "\\" in draft_id:
        raise ValueError("invalid draft id")
    return SOCIAL_DRAFTS_DIR / f"{draft_id}.json"


def _extract_summary(body: str, max_chars: int = 240) -> str:
    """Return the first substantive paragraph, excluding headings and sources."""
    body = re.sub(r"```.*?```", "", body or "", flags=re.S)
    body = re.sub(r"^#\s+.*$", "", body, flags=re.M)
    body = re.split(r"^##\s+(?:sources?|references?)\b", body, maxsplit=1, flags=re.I | re.M)[0]
    for paragraph in re.split(r"\n\s*\n", body):
        text = re.sub(r"^\s{0,3}#{1,6}\s+", "", paragraph, flags=re.M)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"[*`_]", "", text)
        text = re.sub(r"\s+", " ", text).strip(" -")
        if len(text) >= 80 and not _contains_placeholder(text):
            return _truncate(text, max_chars)
    return ""


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rsplit(" ", 1)[0] + "..."


def _contains_placeholder(text: str) -> bool:
    normalized = " ".join((text or "").lower().split())
    markers = (
        "explain why this matters",
        "what the reader should do next",
        "deep technical analysis of the news",
        "builder takeaway explain",
        "angle deep technical analysis",
        "what do you think?",
    )
    return any(marker in normalized for marker in markers)


def _quality_error(title: str, body: str, summary: str = "") -> str | None:
    if not title or len(title.strip()) < 12:
        return "content needs a specific title before social drafts can be created"
    if _contains_placeholder(title) or _contains_placeholder(body):
        return "content contains placeholder copy; write a substantive article before creating social drafts"
    if len(re.sub(r"\s+", "", body or "")) < 180:
        return "content is too short to create a useful social post"
    if not summary:
        return "content has no substantive introductory paragraph for social copy"
    return None


def _social_post_quality_error(title: str, text: str) -> str | None:
    if not title or len(title.strip()) < 12:
        return "social draft needs a specific title before publishing"
    if len(re.sub(r"\s+", "", text or "")) < 100:
        return "social draft is too short to publish"
    if _contains_placeholder(title) or _contains_placeholder(text):
        return "social draft contains placeholder copy and cannot be published"
    title_terms = set(re.findall(r"[a-z0-9]+", title.lower()))
    post_terms = re.findall(r"[a-z0-9]+", text.lower())
    non_title_terms = [term for term in post_terms if term not in title_terms]
    if title.lower() in text.lower() and len(non_title_terms) < 18:
        return "social draft mostly repeats its headline and cannot be published"
    return None


def _format_hashtags(tags: list[str]) -> list[str]:
    cleaned = [re.sub(r"[^a-zA-Z0-9]", "", tag) for tag in tags if tag]
    cleaned = [tag for tag in cleaned if tag]
    if not any(tag.lower() == "buildwithabdallah" for tag in cleaned):
        cleaned.append("BuildWithAbdallah")
    return cleaned[:5]


def _platform_copy(title: str, summary: str, blog_url: str, hashtags: list[str]) -> tuple[str, str, str]:
    """Compose social-native copy from the article's own summary.

    NOTE: this deliberately contains no per-article special cases. An earlier
    revision dispatched three hardcoded narratives on loose substring matches
    ("code review" in subject, etc.), which meant any future article whose
    title+summary happened to contain those words would publish factually
    unrelated copy verbatim to LinkedIn/Facebook/X. Keep this generic — the
    LLM-written variants live in scripts/social_copy.py.
    """
    hashtag_str = " ".join(f"#{tag}" for tag in hashtags)
    linkedin = (
        f"{summary}\n\n"
        "The interesting part is not the headline. It is the implementation decision that changes how this "
        "behaves in a real project.\n\n"
        f"I break that down in the full guide: {blog_url}\n\n{hashtag_str}"
    )
    facebook = (
        f"{summary}\n\n"
        "I focused on the practical implementation choices, not just the demo.\n\n"
        f"Read the full guide: {blog_url}\n\n{hashtag_str}"
    )
    return linkedin, facebook, f"{_truncate(summary, 115)}\n{blog_url}\n{hashtag_str}"


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

    summary = _extract_summary(body, 280)
    if _quality_error(title, body, summary):
        return []
    hashtags = _format_hashtags(tags or [])
    hashtag_str = " ".join(f"#{tag}" for tag in hashtags)
    linkedin_text, facebook_text, x_text = _platform_copy(title, summary, blog_url, hashtags)

    builders = {
        "linkedin": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="linkedin",
            blog_url=blog_url,
            title=title,
            text=linkedin_text,
            description=summary,
            hashtags=hashtags,
        ),
        "facebook": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="facebook",
            blog_url=blog_url,
            title=title,
            text=facebook_text,
            description=summary,
            hashtags=hashtags,
        ),
        "x": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="x",
            blog_url=blog_url,
            title=title,
            text=x_text,
            description=_truncate(summary, 180),
            hashtags=hashtags,
        ),
        "threads": lambda: SocialDraft(
            source_draft_id=source_draft_id,
            platform="threads",
            blog_url=blog_url,
            title=title,
            text=f"{summary}\n\nThe full implementation is here: {blog_url}\n\n{hashtag_str}",
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
            text=f"{summary}\n\nFull guide: {blog_url}",
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
    old_status = draft.status
    if "status" in fields:
        new_status = _STATUS_ALIASES.get(fields["status"], fields["status"])
        fields = {**fields, "status": new_status}
        if new_status not in VALID_STATUSES:
            return None
    allowed = {"title", "text", "description", "tags", "hashtags", "status"}
    for key, value in fields.items():
        if key in allowed and hasattr(draft, key):
            if key in {"tags", "hashtags"} and isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            setattr(draft, key, value)
    if "status" in fields and draft.status != old_status:
        draft.history.append({
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "from": old_status,
            "to": draft.status,
        })
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


def schedule_social_drafts(draft_ids: list[str], scheduled_at: str) -> dict[str, Any]:
    """Schedule approved social drafts for future publishing.

    Only drafts with status=approved can be scheduled. Sets status=scheduled
    and stores the ISO datetime. Immediate publishing does not happen.
    """
    results = {}
    for draft_id in draft_ids:
        draft = load_social_draft(draft_id)
        if draft is None:
            results[draft_id] = {"ok": False, "error": "social draft not found"}
            continue
        if draft.status != "approved":
            results[draft_id] = {"ok": False, "error": f"draft must be approved, current status: {draft.status}"}
            continue
        try:
            dt.datetime.fromisoformat(scheduled_at)
        except ValueError:
            results[draft_id] = {"ok": False, "error": "invalid scheduled_at datetime"}
            continue
        draft.status = "scheduled"
        draft.scheduled_at = scheduled_at
        save_social_draft(draft)
        results[draft_id] = {"ok": True, "draft": draft.to_dict()}
    return {"ok": True, "results": results}


def publish_social_draft(draft_id: str, dry_run: bool = False) -> dict[str, Any]:
    """Publish a single approved/scheduled social draft to its platform.

    Returns ok, published_url, error. On success, updates the draft with
    published_url, published_at, and status=published. On failure, sets
    status=failed and stores error.
    """
    from .social_publishers import publish

    draft = load_social_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "social draft not found"}
    if draft.status not in {"approved", "scheduled"}:
        return {"ok": False, "error": f"social draft must be approved or scheduled, current status: {draft.status}"}
    error = _social_post_quality_error(draft.title, draft.text)
    if error:
        return {"ok": False, "error": error}

    result = publish(draft.platform, draft.to_dict(), dry_run=dry_run)
    if result.get("ok"):
        draft.status = "published"
        draft.published_url = result.get("published_url", "")
        draft.published_at = dt.datetime.now(dt.timezone.utc).isoformat()
        draft.error = ""
    else:
        draft.status = "failed"
        draft.error = result.get("error", "publish failed")
    save_social_draft(draft)
    return result


def publish_due_social_drafts(dry_run: bool = False) -> dict[str, Any]:
    """Publish scheduled social drafts whose scheduled_at has passed.

    Skips future scheduled drafts. Returns per-id results.
    """
    now = dt.datetime.now(dt.timezone.utc)
    results = {}
    for data in list_social_drafts(status="scheduled"):
        draft_id = data.get("draft_id")
        scheduled_at = data.get("scheduled_at", "")
        try:
            when = dt.datetime.fromisoformat(scheduled_at)
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            results[draft_id] = {"ok": False, "error": "invalid scheduled_at"}
            continue
        if when > now:
            results[draft_id] = {"ok": False, "error": "scheduled for the future", "skipped": True}
            continue
        results[draft_id] = publish_social_draft(draft_id, dry_run=dry_run)
    return {"ok": True, "results": results}


def publish_selected_social_drafts(draft_ids: list[str], dry_run: bool = False) -> dict[str, Any]:
    """Publish multiple approved social drafts. Returns per-id results."""
    results = {}
    for draft_id in draft_ids:
        results[draft_id] = publish_social_draft(draft_id, dry_run=dry_run)
    return {"ok": True, "results": results}


def retry_social_draft(draft_id: str) -> dict[str, Any]:
    """Reset a failed draft back to approved so it can be retried."""
    draft = load_social_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "social draft not found"}
    if draft.status != "failed":
        return {"ok": False, "error": f"only failed drafts can be retried, current status: {draft.status}"}
    old_status = draft.status
    draft.status = "approved"
    draft.error = ""
    draft.history.append({
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "from": old_status,
        "to": "approved",
        "note": "manual retry",
    })
    draft.touch()
    save_social_draft(draft)
    return {"ok": True, "draft": draft.to_dict()}


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
