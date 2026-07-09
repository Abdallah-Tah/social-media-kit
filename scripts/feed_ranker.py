"""Rank and deduplicate feed items for smkit feed.

Scoring dimensions:
    keyword match      – title/summary against profile interests/topic
    freshness          – recency of published_at
    source authority   – trust weight per source
    user interests     – intersection with profile interests
    novelty            – penalty for overly common or generic titles

Deduplication:
    canonical URL + similar title (normalized word overlap).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from agent.feed import FeedItem
from scripts.feed_sources import source_authority


def rank_items(items: list[FeedItem], interests: list[str], topic: str | None = None, limit: int = 20) -> list[FeedItem]:
    """Deduplicate and score a raw list of feed items."""
    unique = dedupe_items(items)
    scored = [score_item(item, interests, topic=topic) for item in unique]
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:limit]


def dedupe_items(items: list[FeedItem]) -> list[FeedItem]:
    """Remove exact-URL and near-duplicate-title items, keeping first seen."""
    out: list[FeedItem] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    for item in items:
        if not item.title or not item.url:
            continue
        if item.url in seen_urls:
            continue
        if any(_title_similarity(item.title, seen) >= 0.55 for seen in seen_titles):
            continue
        seen_urls.add(item.url)
        seen_titles.append(item.title)
        out.append(item)
    return out


def score_item(item: FeedItem, interests: list[str], topic: str | None = None) -> FeedItem:
    """Score a single item and populate matched_interests + reason."""
    title = item.title.lower()
    text = (title + " " + (item.summary or "").lower()).strip()

    # Keyword / interest match
    matched: list[str] = []
    for interest in interests:
        if _matches(text, interest):
            matched.append(interest)
    topic_bonus = 0.0
    if topic:
        topic_terms = [t.strip().lower() for t in topic.split(",")]
        for term in topic_terms:
            if _matches(text, term):
                topic_bonus += 0.15

    interest_score = min(1.0, 0.25 + (0.18 * len(matched)) + topic_bonus)

    # Freshness
    freshness = _freshness_score(item.published_at)

    # Source authority
    authority = source_authority(item.source)

    # Novelty (penalize clickbaity/generic words, reward specific tech terms)
    novelty = _novelty_score(title)

    # Combine
    score = (
        0.35 * interest_score
        + 0.25 * freshness
        + 0.25 * authority
        + 0.15 * novelty
    )

    item.score = round(score * 100, 2)
    item.matched_interests = matched
    item.reason = _build_reason(item, freshness, authority, novelty)
    return item


def _matches(text: str, phrase: str) -> bool:
    phrase = phrase.lower().strip()
    if not phrase:
        return False
    # Direct phrase match is stronger.
    if phrase in text:
        return True
    # Word-level partial match for multi-word interests.
    words = [w for w in re.split(r"[^a-z0-9]+", phrase) if w]
    return any(w in text for w in words)


def _freshness_score(published_at: str) -> float:
    if not published_at:
        return 0.35
    try:
        if published_at.endswith("Z"):
            published_at = published_at[:-1] + "+00:00"
        pub = dt.datetime.fromisoformat(published_at)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=dt.timezone.utc)
        now = dt.datetime.now(dt.timezone.utc)
        hours = (now - pub).total_seconds() / 3600.0
    except Exception:
        return 0.35
    if hours < 0:
        return 0.35
    if hours <= 2:
        return 1.0
    if hours <= 6:
        return 0.90
    if hours <= 24:
        return 0.75
    if hours <= 72:
        return 0.55
    if hours <= 168:
        return 0.35
    return 0.15


def _novelty_score(title: str) -> float:
    generic_words = {
        "amazing", "incredible", "unbelievable", "you won\u0027t believe",
        "must read", "top", "best", "worst", "ultimate", "simple", "easy",
        "how to", "guide", "explained", "everything you need", "the complete",
    }
    specific_tech = {
        "laravel", "php", "python", "django", "flask", "react", "vue", "nuxt",
        "next.js", "typescript", "javascript", "rust", "go ", "golang",
        "kubernetes", "docker", "ai ", "llm", "openai", "anthropic", "claude",
        "gemini", "api", "release", "changelog", "github", "oss",
    }
    t = title.lower()
    generic_hits = sum(1 for w in generic_words if w in t)
    tech_hits = sum(1 for w in specific_tech if w in t)
    score = 0.50 + (0.08 * tech_hits) - (0.10 * generic_hits)
    return max(0.0, min(1.0, score))


def _title_similarity(a: str, b: str) -> float:
    """Normalized word-overlap similarity."""
    def words(s: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]{3,}", s.lower()))

    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    inter = wa & wb
    union = wa | wb
    return len(inter) / len(union)


def _build_reason(item: FeedItem, freshness: float, authority: float, novelty: float) -> str:
    parts: list[str] = []
    if item.matched_interests:
        parts.append(f"matches interests: {', '.join(item.matched_interests)}")
    else:
        parts.append("broadly relevant")
    if freshness >= 0.9:
        parts.append("very fresh")
    elif freshness >= 0.6:
        parts.append("recent")
    parts.append(f"authority {authority:.0%}")
    if novelty >= 0.7:
        parts.append("specific / technical")
    return "; ".join(parts)
