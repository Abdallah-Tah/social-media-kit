"""Recommendation engine for smkit feed (Phase 5).

Consumes OpportunityBreakdown from Phase 4 and recommends a content format,
platform fit, angle, and hook.

Supported recommendations:
    blog           - deep technical write-up for the website
    youtube_short  - 30-60s vertical video
    linkedin_post  - professional social post
    twitter_thread - short-form thread
    newsletter     - curated mention / analysis
    tutorial       - hands-on step-by-step (often a blog variant)
    skip           - not worth covering

Returns:
    recommendation      - one of the supported formats
    confidence_score    - 0-100
    reason              - human-readable rationale
    platform_fit_scores - per-platform 0-1 scores
    suggested_angle     - positioning angle
    suggested_hook      - opening line / headline idea

Not wired into smkit feed yet — independently mergeable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FormatRecommendation:
    recommendation: str = "skip"
    confidence_score: int = 0
    reason: str = ""
    platform_fit_scores: dict[str, float] = field(default_factory=dict)
    suggested_angle: str = ""
    suggested_hook: str = ""
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "confidence_score": self.confidence_score,
            "reason": self.reason,
            "platform_fit_scores": {
                k: round(v, 2) for k, v in self.platform_fit_scores.items()
            },
            "suggested_angle": self.suggested_angle,
            "suggested_hook": self.suggested_hook,
            "signals": self.signals,
        }


SUPPORTED_FORMATS = {
    "blog",
    "youtube_short",
    "linkedin_post",
    "twitter_thread",
    "newsletter",
    "tutorial",
    "skip",
}

PLATFORM_LABELS = ["blog", "youtube_short", "linkedin_post", "twitter_thread", "newsletter"]


# ── Topic / angle helpers ─────────────────────────────────────────────────────

def _extract_themes(text: str, interests: list[str]) -> list[str]:
    """Pick out the matched interests present in the text."""
    text = text.lower()
    return [i for i in interests if i.lower() in text]


def _has_tutorial_signal(title: str, summary: str = "") -> bool:
    text = f"{title} {summary}".lower()
    signals = [
        "how to", "guide", "tutorial", "step by step", "getting started",
        "build a", "deploy", "setup", "configure", "install", "use ", "with python",
        "with laravel", "in react", "in next.js", "in vue", "example",
    ]
    return any(s in text for s in signals)


def _has_news_signal(title: str) -> bool:
    text = title.lower()
    signals = [
        "releases", "released", "announces", "announced", "launches", "launched",
        "ships", "shipped", "unveils", "unveiled", "introduces", "new ", "now available",
    ]
    return any(s in text for s in signals)


def _has_opinion_signal(title: str, summary: str = "") -> bool:
    text = f"{title} {summary}".lower()
    signals = [
        "why ", "what ", "the future", "lessons", "opinion", "think", "analysis",
        "explained", "breakdown", "deep dive", "primer",
    ]
    return any(s in text for s in signals)


def _is_code_or_framework(title: str) -> bool:
    text = title.lower()
    tech = [
        "laravel", "php", "python", "django", "flask", "react", "vue", "nuxt",
        "next.js", "typescript", "javascript", "rust", "go ", "golang", "kubernetes",
        "docker", "terraform", "ansible", "github", "api", "sdk", "cli", "library",
    ]
    return any(t in text for t in tech)


# ── Platform fit scoring ────────────────────────────────────────────────────

def compute_platform_fit(
    opportunity: Any,
    trend_direction: str,
    title: str,
    summary: str = "",
    interests: list[str] | None = None,
) -> dict[str, float]:
    """Return per-format fit scores (0-1) without choosing a winner."""
    opp_score = getattr(opportunity, "opportunity_score", 0) / 100.0
    authority = getattr(opportunity, "authority_score", 0.0)
    novelty = getattr(opportunity, "novelty_score", 0.0)
    trend_s = getattr(opportunity, "trend_score", 0.0)
    gap = getattr(opportunity, "gap_score", 0.0)
    interest = getattr(opportunity, "interest_score", 0.0)

    is_news = _has_news_signal(title)
    is_tutorial = _has_tutorial_signal(title, summary)
    is_opinion = _has_opinion_signal(title, summary)
    is_tech = _is_code_or_framework(title)

    # YouTube Short: needs trend/virality + concrete hook.
    youtube_short = 0.1
    if trend_direction in ("exploding", "growing"):
        youtube_short += 0.35
    if is_news or is_tutorial:
        youtube_short += 0.20
    if novelty >= 0.6:
        youtube_short += 0.15
    youtube_short = min(1.0, youtube_short)

    # LinkedIn post: professional / business / engineering angle.
    linkedin = 0.1
    if is_tech or is_news:
        linkedin += 0.25
    if authority >= 0.6:
        linkedin += 0.15
    if "startups" in (interests or []) or "business" in (interests or []):
        linkedin += 0.10
    linkedin = min(1.0, linkedin + 0.1)

    # Twitter / X thread: hot takes, threads, concise news.
    twitter = 0.1
    if trend_direction == "exploding":
        twitter += 0.30
    if is_opinion:
        twitter += 0.15
    if is_news:
        twitter += 0.10
    twitter = min(1.0, twitter)

    # Blog / tutorial: deep technical + authoritative + gap.
    blog = 0.1
    if is_tutorial:
        blog += 0.30
    if is_tech:
        blog += 0.15
    if authority >= 0.6:
        blog += 0.15
    if gap >= 0.7:
        blog += 0.15
    blog = min(1.0, blog)

    # Newsletter: curated news / analysis, especially when blog isn't justified.
    newsletter = 0.1
    if is_news:
        newsletter += 0.25
    if interest >= 0.5:
        newsletter += 0.15
    if opp_score >= 0.45:
        newsletter += 0.10
    newsletter = min(1.0, newsletter)

    return {
        "blog": round(blog, 2),
        "youtube_short": round(youtube_short, 2),
        "linkedin_post": round(linkedin, 2),
        "twitter_thread": round(twitter, 2),
        "newsletter": round(newsletter, 2),
    }


# ── Angle / hook generators ─────────────────────────────────────────────────

def _suggest_angle(
    title: str,
    recommendation: str,
    trend_direction: str,
    interests: list[str],
) -> str:
    themes = _extract_themes(title, interests)
    if recommendation in ("blog", "tutorial"):
        if _has_tutorial_signal(title):
            return f"Hands-on guide showing builders how to apply this in {themes[0] if themes else 'their stack'}."
        return f"Deep technical analysis of the news and what it means for {themes[0] if themes else 'developers'}."
    if recommendation == "youtube_short":
        return "Fast, visual summary of the change with a clear before/after."
    if recommendation == "linkedin_post":
        return f"Professional angle: why this matters for engineering teams and {themes[0] if themes else 'builders'}."
    if recommendation == "twitter_thread":
        return "Thread of 3-5 bite-sized takeaways with a strong opening hook."
    if recommendation == "newsletter":
        return f"Curated mention with links and a one-paragraph builder's take on {themes[0] if themes else 'the topic'}."
    return ""


def _suggest_hook(title: str, recommendation: str, trend_direction: str) -> str:
    t = title.strip()
    if trend_direction == "exploding":
        prefix = "Breaking: "
    elif trend_direction == "growing":
        prefix = "Trending now — "
    else:
        prefix = ""

    if recommendation in ("blog", "tutorial"):
        return f"{prefix}{t}: a practical guide for builders."
    if recommendation == "youtube_short":
        return f"{prefix}{t} — here's what changed in 60 seconds."
    if recommendation == "linkedin_post":
        return f"{prefix}{t} — here's why engineering leaders should care."
    if recommendation == "twitter_thread":
        return f"{prefix}{t}\n\nA quick thread on what it means for builders 🧵"
    if recommendation == "newsletter":
        return f"This week: {t.lower()}"
    return t


# ── Recommendation selector ─────────────────────────────────────────────────

def recommend_format(
    opportunity: Any,
    trend_direction: str = "stable",
    title: str = "",
    summary: str = "",
    interests: list[str] | None = None,
) -> FormatRecommendation:
    """Select the best content format from an OpportunityBreakdown."""
    interests = interests or []
    opp_score = getattr(opportunity, "opportunity_score", 0)
    if opp_score < 35:
        return FormatRecommendation(
            recommendation="skip",
            confidence_score=opp_score,
            reason="Opportunity too low; not worth producing content.",
            platform_fit_scores=compute_platform_fit(
                opportunity, trend_direction, title, summary, interests
            ),
            suggested_angle="",
            suggested_hook="",
            signals=["opportunity_score < 35"],
        )

    fit = compute_platform_fit(opportunity, trend_direction, title, summary, interests)
    # Exclude skip; choose highest fit.
    ranked = sorted(
        [(fmt, score) for fmt, score in fit.items()],
        key=lambda x: x[1],
        reverse=True,
    )

    # If trend is exploding and youtube_short or twitter_thread lead, prefer short video.
    if trend_direction == "exploding" and ranked[0][0] in ("youtube_short", "twitter_thread"):
        # Boost short if novelty/trend is high.
        if getattr(opportunity, "trend_score", 0) >= 0.6 or getattr(opportunity, "novelty_score", 0) >= 0.6:
            recommendation = "youtube_short"
        else:
            recommendation = ranked[0][0]
    else:
        recommendation = ranked[0][0]

    # High-authority technical deep-dive can override to blog/tutorial.
    authority = getattr(opportunity, "authority_score", 0.0)
    gap = getattr(opportunity, "gap_score", 0.0)
    if authority >= 0.75 and gap >= 0.6 and _is_code_or_framework(title):
        recommendation = "tutorial"
        fit["tutorial"] = fit.get("blog", 0.0)
    elif authority >= 0.7 and gap >= 0.7:
        recommendation = "blog"

    confidence = int(round(fit[recommendation] * opp_score / 100 * 100))
    confidence = max(35, min(98, confidence))

    reason = (
        f"Selected {recommendation} because it has the highest platform fit ({fit[recommendation]:.0%}) "
        f"given opportunity score {opp_score} and trend '{trend_direction}'."
    )

    signals = [
        f"top fit: {recommendation} {fit[recommendation]:.0%}",
        f"opportunity_score: {opp_score}",
        f"trend: {trend_direction}",
    ]

    return FormatRecommendation(
        recommendation=recommendation,
        confidence_score=confidence,
        reason=reason,
        platform_fit_scores=fit,
        suggested_angle=_suggest_angle(title, recommendation, trend_direction, interests),
        suggested_hook=_suggest_hook(title, recommendation, trend_direction),
        signals=signals,
    )


# ── Batch recommendations ────────────────────────────────────────────────────

def recommend_for_opportunities(
    opportunities: list[tuple[Any, Any]],
    interests: list[str] | None = None,
) -> list[tuple[Any, FormatRecommendation]]:
    """Generate recommendations for a list of (item/opportunity) pairs.

    Each opportunity should be an OpportunityBreakdown; item should have title.
    """
    results: list[tuple[Any, FormatRecommendation]] = []
    for item, opp in opportunities:
        trend = getattr(opp, "trend_score", 0.0)
        # Convert trend score back to direction label.
        if trend >= 0.85:
            direction = "exploding"
        elif trend >= 0.55:
            direction = "growing"
        elif trend >= 0.25:
            direction = "stable"
        elif trend > 0.0:
            direction = "declining"
        else:
            direction = "dead"
        title = getattr(item, "title", "")
        summary = getattr(item, "summary", "")
        rec = recommend_format(opp, trend_direction=direction, title=title, summary=summary, interests=interests)
        results.append((item, rec))
    return results
