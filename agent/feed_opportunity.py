"""Opportunity engine for smkit feed (Phase 4).

Combines authority, clustering, trend, freshness, novelty, interest match,
content gap, competition estimate, and virality estimate into a single
explainable opportunity score and a recommended next action.

Not wired into smkit feed yet — independently mergeable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OpportunityBreakdown:
    opportunity_score: int = 0  # 0–100
    authority_score: float = 0.0
    cluster_score: float = 0.0
    trend_score: float = 0.0
    freshness_score: float = 0.0
    novelty_score: float = 0.0
    interest_score: float = 0.0
    gap_score: float = 0.0
    competition_score: float = 0.0
    virality_score: float = 0.0
    recommendation_reason: str = ""
    score_breakdown: dict[str, float] = field(default_factory=dict)
    suggested_next_action: str = "skip"
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "opportunity_score": self.opportunity_score,
            "suggested_next_action": self.suggested_next_action,
            "recommendation_reason": self.recommendation_reason,
            "signals": self.signals,
            "score_breakdown": {
                k: round(v, 2) for k, v in self.score_breakdown.items()
            },
        }


VALID_ACTIONS = {
    "create_blog",
    "create_short",
    "create_linkedin_post",
    "create_thread",
    "create_newsletter",
    "skip",
}


# ── Input helpers ────────────────────────────────────────────────────────────

def _title_text(item: Any) -> str:
    title = getattr(item, "title", "") or ""
    summary = getattr(item, "summary", "") or ""
    return f"{title} {summary}".lower()


def _matches(text: str, phrase: str) -> bool:
    phrase = phrase.lower().strip()
    if not phrase:
        return False
    if phrase in text:
        return True
    return any(w in text for w in re.split(r"[^a-z0-9]+", phrase) if w)


# ── Component scorers ────────────────────────────────────────────────────────

def score_interest(item: Any, interests: list[str]) -> tuple[float, list[str]]:
    text = _title_text(item)
    matched = [i for i in interests if _matches(text, i)]
    # Score rises quickly with first matches, then plateaus.
    score = min(1.0, 0.15 + 0.22 * len(matched))
    signals = [f"matches: {', '.join(matched)}"] if matched else []
    return score, signals


def score_freshness(published_at: str) -> tuple[float, list[str]]:
    """Same decay curve as feed_ranker but exposed for explainability."""
    if not published_at:
        return 0.35, ["no date"]
    from scripts.feed_ranker import _freshness_score

    s = _freshness_score(published_at)
    signals = []
    if s >= 0.9:
        signals.append("very fresh")
    elif s >= 0.6:
        signals.append("recent")
    elif s >= 0.3:
        signals.append("older")
    else:
        signals.append("stale")
    return s, signals


def score_novelty(item: Any) -> tuple[float, list[str]]:
    title = (getattr(item, "title", "") or "").lower()
    from scripts.feed_ranker import _novelty_score

    s = _novelty_score(title)
    signals = ["specific/technical"] if s >= 0.7 else []
    return s, signals


def score_authority(item: Any) -> tuple[float, list[str]]:
    from agent.feed_authority import item_authority

    breakdown = item_authority(item.url, item.source, metadata=getattr(item, "metadata", None))
    return breakdown.final_score, breakdown.signals


def score_cluster(cluster: Any | None) -> tuple[float, list[str]]:
    if cluster is None:
        return 0.1, ["no cluster data"]
    size = getattr(cluster, "size", 1)
    source_count = len(set(getattr(cluster, "sources", [])))
    signals = []
    if size >= 5:
        score = 1.0
        signals.append(f"cluster of {size} articles")
    elif size >= 3:
        score = 0.7
        signals.append(f"cluster of {size} articles")
    elif size == 2:
        score = 0.4
        signals.append("2-article cluster")
    else:
        score = 0.15
        signals.append("single article")

    if source_count >= 3:
        score = min(1.0, score + 0.15)
        signals.append(f"{source_count} sources covering")
    elif source_count == 2:
        score = min(1.0, score + 0.05)
        signals.append("2 sources covering")
    return score, signals


def score_trend(trend: Any | None) -> tuple[float, list[str]]:
    if trend is None:
        return 0.3, ["no trend data"]
    direction = getattr(trend, "direction", "stable")
    velocity = getattr(trend, "velocity", 0.0)
    mapping = {
        "exploding": 1.0,
        "growing": 0.75,
        "stable": 0.45,
        "declining": 0.15,
        "dead": 0.0,
    }
    score = mapping.get(direction, 0.3)
    # Blend with velocity for nuance.
    score = 0.7 * score + 0.3 * max(0.0, min(1.0, (velocity + 1) / 2))
    return score, [f"trend: {direction} (v={velocity:.2f})"]


def score_content_gap(item: Any, existing_content: list[Any] | None = None) -> tuple[float, list[str]]:
    """Return gap score: higher means less competition / true gap."""
    if existing_content is None:
        # No index available -> assume open field.
        return 1.0, ["no existing-content index"]
    if not existing_content:
        return 1.0, ["no existing content found"]

    text = _title_text(item)
    item_tokens = _token_set(text)
    if not item_tokens:
        return 0.7, ["empty title"]

    best_score = 0.0
    best_match = None
    for existing in existing_content:
        et = f"{getattr(existing, 'title', '')} {getattr(existing, 'summary', '')} {' '.join(getattr(existing, 'topics', []))}"
        existing_tokens = _token_set(et)
        if not existing_tokens:
            continue
        overlap = item_tokens & existing_tokens
        union = item_tokens | existing_tokens
        jaccard = len(overlap) / len(union)
        if jaccard > best_score:
            best_score = jaccard
            best_match = existing

    if best_score >= 0.65:
        return 0.15, [f"close match: {getattr(best_match, 'url', '')}"]
    if best_score >= 0.30:
        return 0.55, [f"related content exists ({getattr(best_match, 'url', '')})"]
    if best_score >= 0.10:
        return 0.80, ["weak overlap with existing content"]
    return 1.0, ["true content gap"]


def score_competition(cluster: Any | None) -> tuple[float, list[str]]:
    """Estimate how crowded the story is.

    More coverage and more mainstream sources = higher competition = lower score.
    """
    if cluster is None:
        return 0.7, ["single story; unknown competition"]
    size = getattr(cluster, "size", 1)
    sources = set(getattr(cluster, "sources", []))
    mainstream = {"google_news", "reuters.com", "bloomberg.com", "techcrunch.com", "theverge.com"}
    mainstream_hits = sources & mainstream
    if size >= 8 or len(mainstream_hits) >= 3:
        return 0.25, ["high competition (mainstream coverage)"]
    if size >= 4 or len(mainstream_hits) >= 1:
        return 0.55, ["moderate competition"]
    return 0.85, ["low competition (niche coverage)"]


def score_virality(trend: Any | None, cluster: Any | None) -> tuple[float, list[str]]:
    """Estimate viral potential from trend velocity and cluster engagement."""
    score = 0.0
    signals = []
    if trend is not None:
        direction = getattr(trend, "direction", "stable")
        if direction == "exploding":
            score += 0.45
            signals.append("exploding trend")
        elif direction == "growing":
            score += 0.25
            signals.append("growing trend")
    if cluster is not None:
        from agent.feed_trends import _extract_engagement

        upvotes, comments = _extract_engagement(getattr(cluster, "items", []))
        if upvotes >= 500 or comments >= 100:
            score += 0.30
            signals.append("high engagement")
        elif upvotes >= 100 or comments >= 30:
            score += 0.15
            signals.append("decent engagement")
    return min(1.0, score), signals


# ── Token helper for gap detection ──────────────────────────────────────────

def _token_set(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9]{3,}", text.lower())
        if w not in _STOP_WORDS
    }


_STOP_WORDS = {
    "the", "and", "for", "with", "you", "this", "that", "from", "have", "has",
    "been", "are", "was", "were", "will", "would", "could", "should", "they",
    "their", "them", "than", "then", "when", "what", "where", "which", "who",
    "how", "why", "new", "old", "way", "use", "using", "used", "one", "two",
    "three", "first", "last", "best", "most", "more", "some", "many", "much",
    "can", "may", "might", "must", "shall", "about", "over", "into", "onto",
    "but", "not", "only", "just", "now", "today", "news", "latest", "update",
}


# ── Opportunity scorer ─────────────────────────────────────────────────────

def score_opportunity(
    item: Any,
    interests: list[str] | None = None,
    cluster: Any | None = None,
    trend: Any | None = None,
    existing_content: list[Any] | None = None,
) -> OpportunityBreakdown:
    """Compute a holistic opportunity score and recommended action.

    Args:
        item: A FeedItem / StoryCluster representative with url, source, title, etc.
        interests: Profile interests to match against.
        cluster: Optional StoryCluster for coverage / diversity signals.
        trend: Optional TrendBreakdown for trend signals.
        existing_content: Optional list of existing site content for gap analysis.
    """
    interests = interests or []

    authority, auth_signals = score_authority(item)
    cluster_s, cluster_signals = score_cluster(cluster)
    trend_s, trend_signals = score_trend(trend)
    fresh, fresh_signals = score_freshness(getattr(item, "published_at", "") or "")
    novel, novel_signals = score_novelty(item)
    interest_s, interest_signals = score_interest(item, interests)
    gap_s, gap_signals = score_content_gap(item, existing_content)
    comp_s, comp_signals = score_competition(cluster)
    viral_s, viral_signals = score_virality(trend, cluster)

    # Weighted opportunity score (0-1 then scaled).
    weights = {
        "authority": 0.15,
        "cluster": 0.10,
        "trend": 0.15,
        "freshness": 0.15,
        "novelty": 0.10,
        "interest": 0.20,
        "gap": 0.10,
        "competition": 0.05,
    }

    raw = (
        weights["authority"] * authority
        + weights["cluster"] * cluster_s
        + weights["trend"] * trend_s
        + weights["freshness"] * fresh
        + weights["novelty"] * novel
        + weights["interest"] * interest_s
        + weights["gap"] * gap_s
        + weights["competition"] * comp_s
    )

    # Virality is a bonus, not a penalty.
    opportunity = min(1.0, raw + 0.10 * viral_s)

    score_breakdown = {
        "authority": round(authority, 2),
        "cluster": round(cluster_s, 2),
        "trend": round(trend_s, 2),
        "freshness": round(fresh, 2),
        "novelty": round(novel, 2),
        "interest": round(interest_s, 2),
        "gap": round(gap_s, 2),
        "competition": round(comp_s, 2),
        "virality": round(viral_s, 2),
        "weighted_raw": round(raw, 2),
    }

    signals = (
        auth_signals
        + cluster_signals
        + trend_signals
        + fresh_signals
        + novel_signals
        + interest_signals
        + gap_signals
        + comp_signals
        + viral_signals
    )

    action, reason = _select_action(opportunity, trend_s, fresh, authority, gap_s, novel)

    return OpportunityBreakdown(
        opportunity_score=int(round(opportunity * 100)),
        authority_score=authority,
        cluster_score=cluster_s,
        trend_score=trend_s,
        freshness_score=fresh,
        novelty_score=novel,
        interest_score=interest_s,
        gap_score=gap_s,
        competition_score=comp_s,
        virality_score=viral_s,
        recommendation_reason=reason,
        score_breakdown=score_breakdown,
        suggested_next_action=action,
        signals=signals,
    )


def _select_action(
    opportunity: float,
    trend_s: float,
    fresh: float,
    authority: float,
    gap_s: float,
    novel: float,
) -> tuple[str, str]:
    """Pick the best action from the opportunity profile."""
    if opportunity < 0.35:
        return "skip", f"Low opportunity ({opportunity:.0%}); better to skip."

    if trend_s >= 0.75 and fresh >= 0.7:
        if opportunity >= 0.75 and novel >= 0.6:
            return "create_short", f"Hot, fresh story with high opportunity ({opportunity:.0%}); fast short."
        return "create_thread", f"Trending topic ({opportunity:.0%}); thread or short."

    if authority >= 0.7 and gap_s >= 0.7:
        return "create_blog", f"Authoritative + true gap ({opportunity:.0%}); long-form blog."

    if opportunity >= 0.65:
        return "create_linkedin_post", f"Strong evergreen angle ({opportunity:.0%}); LinkedIn post."

    if fresh >= 0.5 and gap_s >= 0.6:
        return "create_newsletter", f"Fresh angle with room to cover ({opportunity:.0%}); newsletter mention."

    return "skip", f"Borderline opportunity ({opportunity:.0%}); no clear format fit."


# ── Convenience wrappers ─────────────────────────────────────────────────────

def opportunity_for_cluster(cluster: Any, interests: list[str] | None = None) -> OpportunityBreakdown:
    """Score a StoryCluster using its own representative, trend, and metadata."""
    item = getattr(cluster, "representative", cluster)
    from agent.feed_trends import trend_for_cluster

    trend = trend_for_cluster(cluster)
    return score_opportunity(item, interests=interests, cluster=cluster, trend=trend)


def rank_opportunities(clusters: list[Any], interests: list[str] | None = None) -> list[tuple[Any, OpportunityBreakdown]]:
    """Score a list of clusters and return them sorted by opportunity."""
    scored = [(c, opportunity_for_cluster(c, interests)) for c in clusters]
    scored.sort(key=lambda x: x[1].opportunity_score, reverse=True)
    return scored
