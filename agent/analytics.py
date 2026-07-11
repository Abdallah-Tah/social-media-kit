"""Read-only analytics engine for smkit intelligence + publishing pipeline.

Derives metrics from persisted records:
    content/feed/intelligence/*.json
    content/drafts/*.json
    content/social_drafts/*.json

No publishing side effects. No invented performance data.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ANALYTICS_DIR = ROOT / "content" / "analytics"
ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)

INTEL_DIR = ROOT / "content" / "feed" / "intelligence"
DRAFTS_DIR = ROOT / "content" / "drafts"
SOCIAL_DIR = ROOT / "content" / "social_drafts"

EXTERNAL_PLATFORMS = [
    "linkedin", "facebook", "x", "threads", "reddit",
    "newsletter", "youtube", "blog",
]


@dataclass
class AnalyticsSnapshot:
    generated_at: str
    start_date: str
    end_date: str
    platform_filter: str | None
    intelligence: dict[str, Any] = field(default_factory=dict)
    editorial_funnel: dict[str, Any] = field(default_factory=dict)
    social: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    performance: dict[str, Any] = field(default_factory=dict)
    recent_activity: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "platform_filter": self.platform_filter,
            "intelligence": self.intelligence,
            "editorial_funnel": self.editorial_funnel,
            "social": self.social,
            "timing": self.timing,
            "performance": self.performance,
            "recent_activity": self.recent_activity,
        }


def _parse_iso(ts: str) -> dt.datetime | None:
    if not ts:
        return None
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_json_files(directory: Path) -> list[dict[str, Any]]:
    records = []
    if not directory.exists():
        return records
    for p in sorted(directory.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            records.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return records


def _within_range(ts: str, start: dt.datetime, end: dt.datetime) -> bool:
    parsed = _parse_iso(ts)
    if not parsed:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return start <= parsed <= end


def _snapshot_card_count(records: list[dict[str, Any]]) -> int:
    total = 0
    for r in records:
        cards = r.get("cards", [])
        total += len(cards)
    return total


def _intelligence_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    scores: list[float] = []
    trending = 0
    exploding = 0
    formats: dict[str, int] = {}
    topics: dict[str, int] = {}
    for r in records:
        for card in r.get("cards", []):
            opp = card.get("opportunity", {})
            score = opp.get("opportunity_score", 0)
            scores.append(score)
            if score >= 70:
                trending += 1
            if score >= 85:
                exploding += 1
            rec = card.get("recommendation", {})
            fmt = rec.get("recommendation", "unknown")
            formats[fmt] = formats.get(fmt, 0) + 1
            headline = card.get("cluster", {}).get("headline", "")
            # Very cheap topic heuristic: first meaningful word.
            first_word = headline.split()[0].lower() if headline else "unknown"
            topics[first_word] = topics.get(first_word, 0) + 1
    return {
        "opportunities_processed": _snapshot_card_count(records),
        "average_opportunity_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "high_opportunities": trending,
        "exploding_count": exploding,
        "top_formats": sorted(formats.items(), key=lambda x: x[1], reverse=True)[:5],
        "top_topics": sorted(topics.items(), key=lambda x: x[1], reverse=True)[:5],
    }


def _editorial_funnel(drafts: list[dict[str, Any]]) -> dict[str, Any]:
    all_statuses = {"idea", "draft", "needs_review", "reviewed", "approved", "published"}
    status_counts: dict[str, int] = {s: 0 for s in all_statuses}
    for d in drafts:
        s = d.get("status", "draft")
        status_counts[s] = status_counts.get(s, 0) + 1
    total = len(drafts)
    created = total
    # reviewed = needs_review + reviewed (legacy) + approved + published
    reviewed = (
        status_counts.get("needs_review", 0)
        + status_counts.get("reviewed", 0)
        + status_counts.get("approved", 0)
        + status_counts.get("published", 0)
    )
    approved = status_counts.get("approved", 0) + status_counts.get("published", 0)
    published = status_counts.get("published", 0)
    def rate(a: int, b: int) -> float:
        return round(a / b * 100, 1) if b else 0
    return {
        "drafts_created": created,
        "drafts_reviewed": reviewed,
        "drafts_approved": approved,
        "blogs_published": published,
        "draft_to_reviewed_rate": rate(reviewed, created),
        "reviewed_to_approved_rate": rate(approved, reviewed),
        "approved_to_published_rate": rate(published, approved),
        "overall_conversion_rate": rate(published, created),
        "status_counts": {k: v for k, v in status_counts.items() if v > 0},
    }


def _social_metrics(socials: list[dict[str, Any]], platform_filter: str | None) -> dict[str, Any]:
    if platform_filter:
        socials = [s for s in socials if s.get("platform") == platform_filter]
    by_platform: dict[str, dict[str, int]] = {}
    for s in socials:
        p = s.get("platform", "unknown")
        by_platform.setdefault(p, {"created": 0, "approved": 0, "scheduled": 0, "published": 0, "failed": 0, "draft": 0})
        by_platform[p]["created"] += 1
        by_platform[p][s.get("status", "draft")] += 1
    total_published = sum(p.get("published", 0) for p in by_platform.values())
    total_attempts = total_published + sum(p.get("failed", 0) for p in by_platform.values())
    success_rate = round(total_published / total_attempts * 100, 1) if total_attempts else 0
    return {
        "total_social_drafts": len(socials),
        "by_platform": by_platform,
        "success_rate": success_rate,
        "total_published": total_published,
        "total_failed": sum(p.get("failed", 0) for p in by_platform.values()),
    }


def _avg_minutes(timestamps: list[str]) -> float | None:
    diffs: list[float] = []
    for pair in timestamps:
        a = _parse_iso(pair[0])
        b = _parse_iso(pair[1])
        if a and b:
            if a.tzinfo is None:
                a = a.replace(tzinfo=dt.timezone.utc)
            if b.tzinfo is None:
                b = b.replace(tzinfo=dt.timezone.utc)
            diff = (b - a).total_seconds() / 60
            if diff >= 0:
                diffs.append(diff)
    if not diffs:
        return None
    return round(sum(diffs) / len(diffs), 1)


def _timing_metrics(drafts: list[dict[str, Any]], socials: list[dict[str, Any]]) -> dict[str, Any]:
    opp_to_draft: list[tuple[str, str]] = []
    draft_to_approval: list[tuple[str, str]] = []
    approval_to_publish: list[tuple[str, str]] = []
    blog_to_social: list[tuple[str, str]] = []
    scheduled_immediate: {"scheduled": 0, "immediate": 0} = {"scheduled": 0, "immediate": 0}

    for d in drafts:
        created = d.get("created_at")
        updated = d.get("updated_at")
        published = d.get("published_at")
        if d.get("status") == "published":
            draft_to_approval.append((created, updated))
            approval_to_publish.append((updated, published))
        elif d.get("status") == "approved":
            draft_to_approval.append((created, updated))

    for s in socials:
        if s.get("scheduled_at"):
            scheduled_immediate["scheduled"] += 1
        else:
            scheduled_immediate["immediate"] += 1
        if s.get("status") == "published" and s.get("published_at"):
            # Approximate source draft creation from source_draft_id if present.
            pass

    return {
        "opportunity_to_draft_minutes": _avg_minutes(opp_to_draft),
        "draft_to_approval_minutes": _avg_minutes(draft_to_approval),
        "approval_to_publish_minutes": _avg_minutes(approval_to_publish),
        "scheduled_vs_immediate": scheduled_immediate,
    }


def _performance_placeholder() -> dict[str, Any]:
    return {
        "status": "not_connected",
        "message": "Platform APIs not connected. Performance values are placeholders.",
        "metrics": {p: {"impressions": None, "clicks": None, "ctr": None, "likes": None,
                        "comments": None, "shares": None, "views": None,
                        "watch_time": None, "page_views": None} for p in EXTERNAL_PLATFORMS},
        "blog_metrics": [],
    }


def _recent_activity(drafts: list[dict[str, Any]], socials: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    events = []
    for d in drafts:
        if d.get("published_at") and d.get("blog_url"):
            events.append({
                "type": "blog_published",
                "title": d.get("title"),
                "url": d.get("blog_url"),
                "platform": "blog",
                "published_at": d.get("published_at"),
            })
    for s in socials:
        if s.get("published_at") and s.get("published_url"):
            events.append({
                "type": "social_published",
                "title": s.get("title"),
                "url": s.get("published_url"),
                "platform": s.get("platform"),
                "published_at": s.get("published_at"),
            })
    events.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return events[:limit]


def compute_analytics(
    days: int | None = None,
    platform_filter: str | None = None,
) -> AnalyticsSnapshot:
    """Compute analytics from persisted records over the requested window."""
    now = dt.datetime.now(dt.timezone.utc)
    if days is None:
        start = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    else:
        start = now - dt.timedelta(days=days)
    end = now

    intel_records = _load_json_files(INTEL_DIR)
    # Filter intelligence snapshots by generated_at.
    intel_records = [r for r in intel_records if _within_range(r.get("generated_at", ""), start, end)]

    drafts = _load_json_files(DRAFTS_DIR)
    drafts = [d for d in drafts if _within_range(d.get("created_at", ""), start, end)]

    socials = _load_json_files(SOCIAL_DIR)
    socials = [s for s in socials if _within_range(s.get("created_at", ""), start, end)]

    performance = _performance_placeholder()
    # Merge external blog metrics if cached.
    from_date_str = start.strftime("%Y-%m-%d") if start != dt.datetime.min.replace(tzinfo=dt.timezone.utc) else None
    to_date_str = end.strftime("%Y-%m-%d")
    performance["blog_metrics"] = _load_blog_metrics(drafts, from_date_str, to_date_str)

    return AnalyticsSnapshot(
        generated_at=now.isoformat(),
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        platform_filter=platform_filter,
        intelligence=_intelligence_metrics(intel_records),
        editorial_funnel=_editorial_funnel(drafts),
        social=_social_metrics(socials, platform_filter),
        timing=_timing_metrics(drafts, socials),
        performance=performance,
        recent_activity=_recent_activity(drafts, socials),
    )


def _load_blog_metrics(drafts: list[dict[str, Any]], from_date: str | None = None, to_date: str | None = None) -> list[dict[str, Any]]:
    """Load any cached blog analytics for published drafts in this window."""
    from .analytics_connectors.blog import _cache_path
    metrics = []
    for d in drafts:
        if d.get("status") != "published" or not d.get("blog_url"):
            continue
        cache = _cache_path(d["blog_url"], from_date, to_date)
        if not cache.exists():
            continue
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        metrics.append({
            "draft_id": d.get("draft_id"),
            "blog_url": d.get("blog_url"),
            "status": data.get("status"),
            "page_views": data.get("page_views"),
            "unique_visitors": data.get("unique_visitors"),
            "clicks": data.get("clicks"),
            "average_read_time_seconds": data.get("average_read_time_seconds"),
            "referrers": data.get("referrers", []),
            "period": data.get("period", {}),
            "last_sync_at": data.get("last_sync_at"),
        })
    return metrics


def campaign_analytics() -> list[dict[str, Any]]:
    """Return campaign-linked publish data for analytics loop-closing."""
    campaigns_dir = ROOT / "content" / "campaigns"
    if not campaigns_dir.exists():
        return []
    drafts_dir = ROOT / "content" / "drafts"
    out = []
    for p in sorted(campaigns_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
        try:
            campaign = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        content_draft_id = campaign.get("content_draft_id", "")
        content_status = "unknown"
        blog_url = ""
        if content_draft_id:
            dp = drafts_dir / f"{content_draft_id}.json"
            if dp.exists():
                try:
                    d = json.loads(dp.read_text(encoding="utf-8"))
                    content_status = d.get("status", "unknown")
                    blog_url = d.get("blog_url", "")
                except (json.JSONDecodeError, OSError):
                    pass
        out.append({
            "campaign_id": campaign.get("campaign_id"),
            "headline": campaign.get("headline", ""),
            "created_at": campaign.get("created_at", ""),
            "content_status": content_status,
            "blog_url": blog_url,
            "platforms": list(campaign.get("social_draft_ids", {}).keys()),
            "source_card": campaign.get("source_card", {}),
        })
    return out


def save_analytics(snapshot: AnalyticsSnapshot, path: Path | None = None) -> Path:
    if path is None:
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M")
        path = ANALYTICS_DIR / f"{now}.json"
    path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    return path


def export_csv(snapshot: AnalyticsSnapshot) -> str:
    """Export a simplified CSV of social-by-platform metrics."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["platform", "created", "approved", "scheduled", "published", "failed"])
    for platform, counts in snapshot.social.get("by_platform", {}).items():
        writer.writerow([
            platform,
            counts.get("created", 0),
            counts.get("approved", 0),
            counts.get("scheduled", 0),
            counts.get("published", 0),
            counts.get("failed", 0),
        ])
    return output.getvalue()


def export_json(snapshot: AnalyticsSnapshot) -> str:
    return json.dumps(snapshot.to_dict(), indent=2)
