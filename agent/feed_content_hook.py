"""Content generator hook for smkit feed (Phase 6).

Turns a story cluster + recommendation into a structured content brief.
NO PUBLISHING happens here. The output is a ready-to-use brief that can be
handed to the existing SMKit pipeline later (e.g., `smkit run`, Remotion,
social_copy).

Supported briefs:
    blog             - long-form article outline
    youtube_short    - 30-60s Short script brief
    linkedin_post    - professional post brief
    twitter_thread   - thread brief
    newsletter       - curated newsletter mention brief
    tutorial         - hands-on tutorial brief

Output:
    content_type
    title
    hook
    angle
    key_points
    source_urls
    call_to_action
    suggested_assets
    publish_ready: false

Not wired into smkit feed yet — independently mergeable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ContentBrief:
    content_type: str = ""
    title: str = ""
    hook: str = ""
    angle: str = ""
    key_points: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    call_to_action: str = ""
    suggested_assets: list[str] = field(default_factory=list)
    publish_ready: bool = False
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_type": self.content_type,
            "title": self.title,
            "hook": self.hook,
            "angle": self.angle,
            "key_points": self.key_points,
            "source_urls": self.source_urls,
            "call_to_action": self.call_to_action,
            "suggested_assets": self.suggested_assets,
            "publish_ready": False,
            "signals": self.signals,
        }


# ── Input helpers ───────────────────────────────────────────────────────────

def _cluster_headline(cluster: Any) -> str:
    return getattr(cluster, "headline", "") or getattr(cluster.representative if hasattr(cluster, "representative") else cluster, "title", "")


def _cluster_urls(cluster: Any) -> list[str]:
    urls = getattr(cluster, "urls", [])
    if urls:
        return list(urls)
    rep = getattr(cluster, "representative", cluster)
    return [getattr(rep, "url", "")] if getattr(rep, "url", "") else []


def _cluster_sources(cluster: Any) -> list[str]:
    return list(getattr(cluster, "sources", []))


def _cluster_summary(cluster: Any) -> str:
    rep = getattr(cluster, "representative", cluster)
    return getattr(rep, "summary", "") or ""


def _extract_themes(title: str, interests: list[str]) -> list[str]:
    text = title.lower()
    return [i for i in interests if i.lower() in text]


# ── Title / hook generators per format ──────────────────────────────────────

def _blog_title(headline: str) -> str:
    return f"What {headline} Means for Builders"


def _blog_hook(headline: str, angle: str) -> str:
    return f"{headline} just landed. Here's what changed and why it matters if you ship software."


def _short_title(headline: str) -> str:
    return f"{headline} in 60 Seconds"


def _short_hook(headline: str) -> str:
    return f"{headline} — here's the one thing you actually need to know."


def _linkedin_title(headline: str) -> str:
    return headline


def _linkedin_hook(headline: str) -> str:
    return f"Engineering teams should pay attention to {headline.lower()}. Here's why."


def _thread_title(headline: str) -> str:
    return headline


def _thread_hook(headline: str) -> str:
    return f"{headline}\n\nA 5-tweet breakdown for builders 🧵"


def _newsletter_title(headline: str) -> str:
    return f"This Week: {headline}"


def _newsletter_hook(headline: str) -> str:
    return f"Last week's most interesting builder story: {headline.lower()}."


def _tutorial_title(headline: str) -> str:
    return f"How to Use {headline} in Your Next Project"


def _tutorial_hook(headline: str) -> str:
    return f"Want to try {headline.lower()}? Here's a step-by-step guide you can follow today."


# ── Key point extraction ─────────────────────────────────────────────────────

def _generate_key_points(headline: str, summary: str, sources: list[str], content_type: str) -> list[str]:
    points: list[str] = []
    if summary:
        # Split summary into sentences; use first 2 as points.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary) if s.strip()]
        points.extend(sentences[:2])
    points.append(f"Source coverage from: {', '.join(sources[:3]) if sources else 'unknown'}")
    if content_type in ("blog", "tutorial"):
        points.append("Include a concrete code example or workflow.")
    if content_type in ("youtube_short", "linkedin_post"):
        points.append("Lead with the single most important takeaway.")
    if content_type == "twitter_thread":
        points.append("Each tweet should stand alone; thread builds to a CTA.")
    if content_type == "newsletter":
        points.append("Add 1-2 related links and a short builder's take.")
    return points[:5]


# ── CTA generator ────────────────────────────────────────────────────────────

def _call_to_action(content_type: str, brand_link: str = "https://buildwithabdallah.com") -> str:
    ctas = {
        "blog": f"Read the full breakdown on {brand_link} and subscribe for weekly builder notes.",
        "youtube_short": "Follow for 60-second builder news every day.",
        "linkedin_post": "What do you think — will this change how your team ships? Drop a comment.",
        "twitter_thread": "Follow @buildwithabdallah for more bite-sized builder takes.",
        "newsletter": "Subscribe for the weekly builder digest.",
        "tutorial": "Try the steps and reply with what you build.",
    }
    return ctas.get(content_type, f"Follow {brand_link} for more.")


# ── Asset suggestions ──────────────────────────────────────────────────────

def _suggested_assets(content_type: str, source_count: int, title: str) -> list[str]:
    base = []
    if content_type == "youtube_short":
        base.append("Vertical 9:16 brand card cover (BrandFrame)")
        base.append("60s voiceover with Jarnathan (ElevenLabs)")
        if source_count >= 2:
            base.append("B-roll or screenshot montage from source URLs")
    if content_type in ("blog", "tutorial"):
        base.append("Hero cover image (3840x2160 landscape)")
        base.append("Code screenshot / diagram")
    if content_type == "linkedin_post":
        base.append("Square or landscape branded card")
    if content_type == "twitter_thread":
        base.append("Lead image / branded card")
    if content_type == "newsletter":
        base.append("Curated link preview card")
    return base


# ── Brief builders ───────────────────────────────────────────────────────────

def build_brief(cluster: Any, recommendation: Any, interests: list[str] | None = None) -> ContentBrief:
    """Generate a structured content brief from a cluster + format recommendation.

    `recommendation` can be a FormatRecommendation object or a plain string like
    "blog", "youtube_short", etc.
    """
    interests = interests or []
    content_type = (
        recommendation.recommendation
        if hasattr(recommendation, "recommendation")
        else str(recommendation)
    )
    if content_type not in {
        "blog", "youtube_short", "linkedin_post", "twitter_thread", "newsletter", "tutorial", "skip",
    }:
        content_type = "blog"

    if content_type == "skip":
        return ContentBrief(
            content_type="skip",
            title="",
            hook="",
            angle="",
            key_points=["Recommendation was to skip this story."],
            source_urls=[],
            call_to_action="",
            suggested_assets=[],
            publish_ready=False,
            signals=["recommendation = skip"],
        )

    headline = _cluster_headline(cluster)
    summary = _cluster_summary(cluster)
    sources = _cluster_sources(cluster)
    urls = _cluster_urls(cluster)
    source_count = getattr(cluster, "size", len(urls))

    title = _title_for(content_type, headline)
    hook = _hook_for(content_type, headline)
    angle = recommendation.suggested_angle if hasattr(recommendation, "suggested_angle") else _default_angle(content_type, headline, interests)

    key_points = _generate_key_points(headline, summary, sources, content_type)
    cta = _call_to_action(content_type)
    assets = _suggested_assets(content_type, source_count, title)

    signals = [
        f"content_type: {content_type}",
        f"sources: {len(sources)}",
        f"cluster size: {source_count}",
    ]
    if hasattr(recommendation, "confidence_score"):
        signals.append(f"confidence: {recommendation.confidence_score}")

    return ContentBrief(
        content_type=content_type,
        title=title,
        hook=hook,
        angle=angle,
        key_points=key_points,
        source_urls=urls,
        call_to_action=cta,
        suggested_assets=assets,
        publish_ready=False,
        signals=signals,
    )


def _title_for(content_type: str, headline: str) -> str:
    return {
        "blog": _blog_title(headline),
        "youtube_short": _short_title(headline),
        "linkedin_post": _linkedin_title(headline),
        "twitter_thread": _thread_title(headline),
        "newsletter": _newsletter_title(headline),
        "tutorial": _tutorial_title(headline),
    }.get(content_type, headline)


def _hook_for(content_type: str, headline: str) -> str:
    return {
        "blog": _blog_hook(headline, ""),
        "youtube_short": _short_hook(headline),
        "linkedin_post": _linkedin_hook(headline),
        "twitter_thread": _thread_hook(headline),
        "newsletter": _newsletter_hook(headline),
        "tutorial": _tutorial_hook(headline),
    }.get(content_type, headline)


def _default_angle(content_type: str, headline: str, interests: list[str]) -> str:
    themes = _extract_themes(headline, interests)
    if content_type in ("blog", "tutorial"):
        return f"Hands-on angle for builders working with {themes[0] if themes else 'this technology'}."
    if content_type == "youtube_short":
        return "Fast visual summary with before/after framing."
    if content_type == "linkedin_post":
        return f"Professional angle on what this means for {themes[0] if themes else 'engineering teams'}."
    if content_type == "twitter_thread":
        return "Bite-sized takeaways in a numbered thread."
    if content_type == "newsletter":
        return f"Curated mention with a short builder's take on {themes[0] if themes else 'the topic'}."
    return ""


# ── SMKit pipeline interface ────────────────────────────────────────────────

def to_smkit_args(brief: ContentBrief, profile: str = "default", dry_run: bool = True) -> dict[str, Any]:
    """Convert a brief into arguments for existing SMKit commands.

    This does NOT run anything; it returns a dict that a later phase can pass to
    `subprocess.run([...])` or `agent.cli.main([...])`.
    """
    cmd = ["smkit", "run", "--topic", brief.title, "--profile", profile]
    if dry_run:
        cmd.append("--dry-run")
    else:
        cmd.append("--yes")
    return {
        "command": cmd,
        "cwd": str(Path(__file__).resolve().parents[1]),
        "brief": brief.to_dict(),
        "dry_run": dry_run,
    }


def generate_briefs_for_clusters(
    cluster_recommendations: list[tuple[Any, Any]],
    interests: list[str] | None = None,
) -> list[ContentBrief]:
    """Batch generate briefs from (cluster, recommendation) pairs."""
    briefs: list[ContentBrief] = []
    for cluster, recommendation in cluster_recommendations:
        brief = build_brief(cluster, recommendation, interests=interests)
        if brief.content_type != "skip":
            briefs.append(brief)
    return briefs
