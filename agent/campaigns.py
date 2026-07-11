"""Campaign manager — fan-out from a single intelligence card to all outputs.

A Campaign links one intelligence card to its generated children:
  - one ContentDraft (blog / article)
  - one SocialDraft per platform

Campaigns are stored as JSON in content/campaigns/<campaign_id>.json.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .drafts import ContentDraft, create_draft, load_draft, VALID_STATUSES as DRAFT_STATUSES
from .social_drafts import SocialDraft, save_social_draft, load_social_draft, generate_social_drafts, SUPPORTED_PLATFORMS

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS_DIR = ROOT / "content" / "campaigns"
CAMPAIGNS_DIR.mkdir(parents=True, exist_ok=True)

ALL_PLATFORMS = sorted(SUPPORTED_PLATFORMS)


@dataclass
class Campaign:
    campaign_id: str = ""
    headline: str = ""
    content_draft_id: str = ""
    social_draft_ids: dict[str, str] = field(default_factory=dict)
    source_card: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.campaign_id:
            self.campaign_id = str(uuid.uuid4())[:8]
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "headline": self.headline,
            "content_draft_id": self.content_draft_id,
            "social_draft_ids": self.social_draft_ids,
            "source_card": self.source_card,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _campaign_path(campaign_id: str) -> Path:
    if ".." in campaign_id or "/" in campaign_id or "\\" in campaign_id:
        raise ValueError("invalid campaign id")
    return CAMPAIGNS_DIR / f"{campaign_id}.json"


def save_campaign(campaign: Campaign) -> Path:
    campaign.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    path = _campaign_path(campaign.campaign_id)
    path.write_text(json.dumps(campaign.to_dict(), indent=2), encoding="utf-8")
    return path


def load_campaign(campaign_id: str) -> Campaign | None:
    path = _campaign_path(campaign_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Campaign(**data)
    except (json.JSONDecodeError, TypeError):
        return None


def list_campaigns() -> list[dict[str, Any]]:
    out = []
    for p in sorted(CAMPAIGNS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def get_campaign_pipeline(campaign: Campaign) -> dict[str, Any]:
    """Return live pipeline status by reading child draft records."""
    content = load_draft(campaign.content_draft_id)
    content_status = content.status if content else "missing"

    social: dict[str, Any] = {}
    for platform, draft_id in campaign.social_draft_ids.items():
        sd = load_social_draft(draft_id)
        social[platform] = {
            "draft_id": draft_id,
            "status": sd.status if sd else "missing",
            "published_url": sd.published_url if sd else "",
            "scheduled_at": sd.scheduled_at if sd else "",
        }

    all_statuses = [content_status] + [v["status"] for v in social.values()]
    if any(s == "missing" for s in all_statuses):
        overall = "incomplete"
    elif all(s == "published" for s in all_statuses):
        overall = "published"
    elif any(s == "failed" for s in all_statuses):
        overall = "failed"
    elif any(s in {"approved", "scheduled"} for s in all_statuses):
        overall = "in_progress"
    elif any(s in {"needs_review"} for s in all_statuses):
        overall = "needs_review"
    else:
        overall = "draft"

    return {
        "content": {"draft_id": campaign.content_draft_id, "status": content_status},
        "social": social,
        "overall": overall,
    }


def create_campaign(
    card: dict[str, Any],
    brief: dict[str, Any] | None = None,
    platforms: list[str] | None = None,
) -> Campaign:
    """Fan out a single intelligence card into a full campaign.

    Creates a ContentDraft and one SocialDraft per platform, then links
    them in a Campaign record. Social drafts start with blog_url='pending'
    (updated when the blog is published).

    Returns the saved Campaign.
    """
    if platforms is None:
        platforms = ALL_PLATFORMS

    # Resolve the brief: use provided, fall back to card.brief, or build minimal
    if brief is None:
        brief = card.get("brief") or {}
    if not brief:
        cluster = card.get("cluster", {})
        rec = card.get("recommendation", {})
        brief = {
            "content_type": rec.get("recommendation", "blog"),
            "title": cluster.get("headline", "Untitled"),
            "hook": cluster.get("summary", ""),
            "angle": rec.get("suggested_angle", ""),
            "key_points": [],
            "call_to_action": "Read the full article.",
        }

    # Create the content draft (blog)
    content_draft = create_draft(card, brief)

    # Create social drafts with placeholder blog_url
    placeholder_url = f"https://buildwithabdallah.com/tutorials/{content_draft.slug}"
    valid_platforms = [p for p in platforms if p in SUPPORTED_PLATFORMS]
    social_drafts = generate_social_drafts(
        source_draft_id=content_draft.draft_id,
        blog_url=placeholder_url,
        title=content_draft.title,
        body=content_draft.body,
        platforms=valid_platforms,
        tags=brief.get("tags", []),
    )
    social_draft_ids: dict[str, str] = {}
    for sd in social_drafts:
        sd.campaign_id = ""  # will be set after campaign is created
        save_social_draft(sd)
        social_draft_ids[sd.platform] = sd.draft_id

    # Set campaign_id on content draft
    content_draft.campaign_id = ""  # set after save below

    headline = card.get("cluster", {}).get("headline", brief.get("title", "Campaign"))
    campaign = Campaign(
        headline=headline,
        content_draft_id=content_draft.draft_id,
        social_draft_ids=social_draft_ids,
        source_card=card,
    )
    save_campaign(campaign)

    # Back-link campaign_id onto child drafts
    from .drafts import load_draft, save_draft as _save_draft
    c_draft = load_draft(content_draft.draft_id)
    if c_draft:
        c_draft.campaign_id = campaign.campaign_id
        _save_draft(c_draft)

    from .social_drafts import load_social_draft as _load_sd, save_social_draft as _save_sd
    for platform, sd_id in social_draft_ids.items():
        sd = _load_sd(sd_id)
        if sd:
            sd.campaign_id = campaign.campaign_id
            _save_sd(sd)

    return campaign
