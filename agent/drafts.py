"""Draft workspace for smkit intelligence.

Persistent draft records that bridge intelligence opportunities to later
content publishing. No live publishing here.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DRAFTS_DIR = ROOT / "content" / "drafts"
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)


VALID_STATUSES = {"idea", "draft", "needs_review", "approved", "published"}
# Legacy status alias kept for backward compat — mapped on load.
_STATUS_ALIASES = {"reviewed": "needs_review"}


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
    blog_url: str = ""
    cover_image_url: str = ""
    published_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    seo_title: str = ""
    seo_description: str = ""
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
            "blog_url": self.blog_url,
            "cover_image_url": self.cover_image_url,
            "published_at": self.published_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": self.history,
            "seo_title": self.seo_title,
            "seo_description": self.seo_description,
            "campaign_id": self.campaign_id,
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
    """Create a new draft from intelligence card + brief data."""
    cluster = card.get("cluster", {})
    rec = card.get("recommendation", {})
    content_type = brief.get("content_type", rec.get("recommendation", "blog"))
    title = brief.get("title", "Untitled Draft")
    draft = ContentDraft(
        source_cluster=cluster,
        recommendation=rec,
        content_type=content_type,
        title=title,
        brief=brief,
        body=_brief_to_markdown(brief, cluster, content_type, title),
        source_urls=cluster.get("urls", []),
    )
    save_draft(draft)
    return draft


def _brief_to_markdown(brief: dict[str, Any], cluster: dict[str, Any], content_type: str, title: str) -> str:
    """Build an editable starter body when the brief is structured only."""
    explicit_body = brief.get("markdown", "") or brief.get("draft_body", "")
    if explicit_body:
        return str(explicit_body)

    hook = str(brief.get("hook", "")).strip()
    angle = str(brief.get("angle", "")).strip()
    cta = str(brief.get("call_to_action", "")).strip()
    points = [str(p).strip() for p in brief.get("key_points", []) if str(p).strip()]
    source_urls = brief.get("source_urls") or cluster.get("urls", []) or []
    sources = cluster.get("sources", []) or []

    if content_type == "youtube_short":
        lines = [f"# {title}", "", "## Hook", hook or title, "", "## 60-second script"]
        script_beats = points or [angle or "Explain the core story in one clear takeaway."]
        for index, point in enumerate(script_beats, start=1):
            lines.append(f"{index}. {point}")
        lines.extend(["", "## Visual notes"])
        lines.extend(_asset_lines(brief.get("suggested_assets", [])))
        lines.extend(["", "## CTA", cta or "Follow for more builder news."])
    elif content_type in {"linkedin_post", "twitter_thread", "newsletter"}:
        lines = [f"# {title}", "", hook or title]
        if angle:
            lines.extend(["", angle])
        if points:
            lines.extend(["", "## Key points"])
            lines.extend(f"- {point}" for point in points)
        if cta:
            lines.extend(["", cta])
    else:
        lines = [f"# {title}", "", hook or title]
        if angle:
            lines.extend(["", "## Angle", angle])
        if points:
            lines.extend(["", "## What to cover"])
            lines.extend(f"- {point}" for point in points)
        lines.extend(["", "## Builder takeaway", "Explain why this matters and what the reader should do next."])
        if cta:
            lines.extend(["", "## Call to action", cta])

    if sources:
        lines.extend(["", "## Sources", f"- {', '.join(str(s) for s in sources)}"])
    if source_urls:
        lines.extend(["", "## Source links"])
        lines.extend(f"- {url}" for url in source_urls if url)
    return "\n".join(lines).strip() + "\n"


def _asset_lines(assets: Any) -> list[str]:
    if not assets:
        return ["- Add source screenshot or branded visual."]
    return [f"- {asset}" for asset in assets if str(asset).strip()]


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
    old_status = draft.status
    if "status" in fields:
        new_status = _STATUS_ALIASES.get(fields["status"], fields["status"])
        fields = {**fields, "status": new_status}
        if new_status not in VALID_STATUSES:
            return None
        if new_status == "published" and not draft.blog_url:
            return None
    allowed = {"title", "slug", "body", "status", "seo_title", "seo_description"}
    for key, value in fields.items():
        if key in allowed and hasattr(draft, key):
            setattr(draft, key, value)
    if "status" in fields and draft.status != old_status:
        draft.history.append({
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "from": old_status,
            "to": draft.status,
        })
    draft.touch()
    save_draft(draft)
    return draft


def transition_status(draft_id: str, new_status: str) -> ContentDraft | None:
    """Move a draft through its status workflow."""
    new_status = _STATUS_ALIASES.get(new_status, new_status)
    if new_status not in VALID_STATUSES:
        return None
    return update_draft(draft_id, {"status": new_status})


def publish_blog(draft_id: str) -> dict[str, Any]:
    """Publish an approved draft to the blog. No-op if not approved.

    Returns a dict with ok, blog_url, post, and error.
    """
    draft = load_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "draft not found"}
    if draft.status != "approved":
        return {"ok": False, "error": f"draft must be approved, current status: {draft.status}"}

    # Import blog publisher lazily to keep draft module light.
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from blog_publisher import publish_article

    cover = _generate_cover_for_draft(draft)
    cover_image_url = cover.get("url") or cover.get("path") or draft.cover_image_url
    post = publish_article(
        title=draft.title,
        slug=draft.slug,
        content=draft.body,
        excerpt=draft.brief.get("excerpt", ""),
        publish=True,
        cover_image_url=cover_image_url,
    )
    if not post:
        return {"ok": False, "error": "blog publish failed"}

    base_url = _blog_base_url()
    slug = post.get("slug") or draft.slug
    blog_url = f"{base_url}/tutorials/{slug}"

    draft.blog_url = blog_url
    draft.cover_image_url = (
        post.get("cover_image")
        or post.get("featured_image")
        or post.get("feature_image")
        or cover_image_url
        or ""
    )
    draft.published_at = dt.datetime.now(dt.timezone.utc).isoformat()
    draft.status = "published"
    save_draft(draft)

    try:
        from .notify import notify_publish
        notify_publish(f"✅ Published blog post: {draft.title}\n{blog_url}")
    except Exception:
        pass

    return {"ok": True, "blog_url": blog_url, "cover_image_url": draft.cover_image_url, "post": post}


def _generate_cover_for_draft(draft: ContentDraft, extra_prompt: str | None = None) -> dict[str, Any]:
    """Generate a cover for a blog publish, falling back gracefully."""
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        from image_generator import generate_cover

        assets_dir = ROOT / "content" / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        out_path = assets_dir / f"{dt.date.today().isoformat()}_{draft.slug or draft.draft_id}-cover.png"
        result = generate_cover(
            draft.title,
            prompt=extra_prompt,
            out_path=str(out_path),
            branding={"accent_color": "#2563eb"},
        )
        return result or {}
    except Exception as exc:
        print(f"cover generation failed for draft {draft.draft_id}: {exc}")
        return {}


def _blog_base_url() -> str:
    """Derive public blog base URL from BLOG_API_URL env."""
    api_url = os.environ.get("BLOG_API_URL", "")
    if "/api" in api_url:
        return api_url.split("/api")[0].rstrip("/")
    return api_url.rstrip("/")


COVER_STYLE_PROMPTS: dict[str, str] = {
    "clean_tech": (
        "Clean minimal tech article cover, white background, bold typography, "
        "subtle blue accent, professional developer content"
    ),
    "editorial": (
        "Editorial magazine-style cover, strong typography, dramatic layout, "
        "developer/engineering theme, high contrast"
    ),
    "diagram": (
        "Technical diagram cover, flowchart aesthetic, clean lines, node-graph style, "
        "software architecture visualization, minimal color palette"
    ),
    "thumbnail": (
        "YouTube video thumbnail style, vibrant colors, bold text area on left, "
        "eye-catching visual on right, high contrast, developer channel"
    ),
    "social_card": (
        "Social media card cover, modern gradient background, clean centered text area, "
        "branded developer content, square-friendly composition"
    ),
}


def generate_cover_for_draft(draft_id: str, style: str = "clean_tech") -> dict[str, Any]:
    """Public wrapper: generate or regenerate a cover image for a draft."""
    draft = load_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "draft not found"}
    prompt = COVER_STYLE_PROMPTS.get(style, COVER_STYLE_PROMPTS["clean_tech"])
    result = _generate_cover_for_draft(draft, extra_prompt=prompt)
    url = result.get("url") or result.get("path") or ""
    if url:
        draft.cover_image_url = url
        save_draft(draft)
        return {"ok": True, "cover_image_url": url, "style": style}
    return {"ok": False, "error": result.get("error", "cover generation failed")}


def get_cover_info(draft_id: str) -> dict[str, Any]:
    """Return current cover image info for a draft."""
    draft = load_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "draft not found"}
    return {
        "ok": True,
        "draft_id": draft_id,
        "cover_image_url": draft.cover_image_url,
        "exists": bool(draft.cover_image_url),
        "styles": list(COVER_STYLE_PROMPTS.keys()),
    }


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
