"""Trend detection for smkit feed (Phase 3).

Classifies a story cluster as:
    exploding   - many sources, very recent, strong engagement
    growing     - increasing coverage and recent activity
    stable      - steady coverage, not accelerating
    declining   - old cluster tail, fewer fresh items
    dead        - no fresh items in a while

Returns an explainable TrendBreakdown with the direction, a velocity score,
and a human-readable explanation.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrendBreakdown:
    direction: str = "stable"
    velocity: float = 0.0  # -1.0 to +1.0
    freshness_score: float = 0.0
    coverage_score: float = 0.0
    diversity_score: float = 0.0
    engagement_score: float = 0.0
    signals: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "velocity": round(self.velocity, 2),
            "freshness_score": round(self.freshness_score, 2),
            "coverage_score": round(self.coverage_score, 2),
            "diversity_score": round(self.diversity_score, 2),
            "engagement_score": round(self.engagement_score, 2),
            "signals": self.signals,
            "recommendation": self.recommendation,
            "sparkline": self._sparkline(),
        }

    def _sparkline(self) -> list[float]:
        """Generate a 7-point sparkline from velocity and component scores."""
        base = max(0.0, (self.velocity + 1) / 2)
        points = [
            base * 0.6,
            base * 0.75,
            base * 0.9,
            base * 1.0,
            base * self.freshness_score,
            base * self.coverage_score,
            base * self.diversity_score,
        ]
        return [round(min(1.0, p) * 100, 1) for p in points]


# ── Time-window helpers ─────────────────────────────────────────────────────

def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        v = value
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        d = dt.datetime.fromisoformat(v)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d
    except Exception:
        return None


# ── Signal extraction ────────────────────────────────────────────────────────

def _extract_engagement(items: list[Any]) -> tuple[int, int]:
    """Sum upvotes/scores and comments across items if metadata present."""
    upvotes = 0
    comments = 0
    for item in items:
        meta = getattr(item, "metadata", None) or {}
        if not meta:
            # Try direct attributes
            upvotes += int(getattr(item, "upvotes", 0) or 0)
            comments += int(getattr(item, "comments", 0) or 0)
            continue
        upvotes += int(meta.get("upvotes") or meta.get("score") or 0)
        comments += int(meta.get("comments") or meta.get("num_comments") or 0)
    return upvotes, comments


# ── Component scores ─────────────────────────────────────────────────────────

def _freshness_score(latest: str, earliest: str | None = None) -> tuple[float, list[str]]:
    """Score how fresh / active the cluster is (0-1)."""
    signals: list[str] = []
    latest_dt = _parse_iso(latest)
    if not latest_dt:
        return 0.0, ["no date"]

    hours = (_now() - latest_dt).total_seconds() / 3600.0
    if hours < 0:
        hours = 0.0

    if hours <= 2:
        score = 1.0
        signals.append("< 2h old")
    elif hours <= 6:
        score = 0.90
        signals.append("< 6h old")
    elif hours <= 24:
        score = 0.75
        signals.append("< 24h old")
    elif hours <= 72:
        score = 0.50
        signals.append("1-3 days old")
    elif hours <= 168:
        score = 0.25
        signals.append("3-7 days old")
    else:
        score = 0.0
        signals.append("> 7 days old")

    # Active span bonus: clusters that started recently are hotter.
    if earliest:
        earliest_dt = _parse_iso(earliest)
        if earliest_dt:
            span_hours = (latest_dt - earliest_dt).total_seconds() / 3600.0
            if span_hours <= 2 and score > 0.5:
                signals.append("burst: started and peaked within 2h")
                score = min(1.0, score + 0.10)

    return score, signals


def _coverage_score(item_count: int) -> tuple[float, list[str]]:
    signals: list[str] = []
    if item_count >= 10:
        score = 1.0
        signals.append(f"{item_count} articles (viral)")
    elif item_count >= 5:
        score = 0.80
        signals.append(f"{item_count} articles (high)")
    elif item_count >= 3:
        score = 0.55
        signals.append(f"{item_count} articles (moderate)")
    elif item_count == 2:
        score = 0.30
        signals.append("2 articles")
    else:
        score = 0.10
        signals.append("single article")
    return score, signals


def _diversity_score(source_count: int) -> tuple[float, list[str]]:
    signals: list[str] = []
    if source_count >= 4:
        score = 1.0
        signals.append(f"{source_count} unique sources")
    elif source_count == 3:
        score = 0.75
        signals.append("3 sources")
    elif source_count == 2:
        score = 0.45
        signals.append("2 sources")
    else:
        score = 0.15
        signals.append("single source")
    return score, signals


def _engagement_score(upvotes: int, comments: int) -> tuple[float, list[str]]:
    signals: list[str] = []
    score = 0.0
    if upvotes >= 1000:
        score += 0.35
        signals.append(f"{upvotes} upvotes")
    elif upvotes >= 200:
        score += 0.25
        signals.append(f"{upvotes} upvotes")
    elif upvotes >= 50:
        score += 0.15
        signals.append(f"{upvotes} upvotes")
    elif upvotes >= 10:
        score += 0.05
        signals.append(f"{upvotes} upvotes")

    if comments >= 200:
        score += 0.15
        signals.append(f"{comments} comments")
    elif comments >= 50:
        score += 0.10
        signals.append(f"{comments} comments")
    elif comments >= 10:
        score += 0.05
        signals.append(f"{comments} comments")

    return min(0.50, score), signals


# ── Trend classifier ──────────────────────────────────────────────────────────

def detect_trend(
    items: list[Any],
    latest: str = "",
    earliest: str = "",
) -> TrendBreakdown:
    """Classify trend direction from cluster signals."""
    item_count = len(items)
    sources = {getattr(item, "source", "") for item in items if getattr(item, "source", "")}
    source_count = len(sources)

    freshness, freshness_signals = _freshness_score(latest, earliest)
    coverage, coverage_signals = _coverage_score(item_count)
    diversity, diversity_signals = _diversity_score(source_count)
    upvotes, comments = _extract_engagement(items)
    engagement, engagement_signals = _engagement_score(upvotes, comments)

    # Velocity: weighted combination. Freshness matters most for trend direction.
    velocity = (
        0.40 * freshness
        + 0.25 * coverage
        + 0.20 * diversity
        + 0.15 * engagement
        - 0.10  # baseline so single old items are declining, not stable
    )
    velocity = max(-1.0, min(1.0, velocity))

    # Direction thresholds
    if freshness >= 0.85 and coverage >= 0.55 and (source_count >= 3 or engagement >= 0.25):
        direction = "exploding"
        recommendation = "Immediate social post + notification. Story is breaking."
    elif velocity >= 0.25 and freshness >= 0.50:
        direction = "growing"
        recommendation = "Strong candidate for daily feed or newsletter mention."
    elif velocity <= -0.35 or freshness == 0.0:
        direction = "dead"
        recommendation = "Skip. Story is stale or single-source."
    elif velocity <= -0.10:
        direction = "declining"
        recommendation = "Only include if highly relevant to interests."
    else:
        direction = "stable"
        recommendation = "Rank normally by interest + authority."

    signals = freshness_signals + coverage_signals + diversity_signals + engagement_signals

    return TrendBreakdown(
        direction=direction,
        velocity=round(velocity, 2),
        freshness_score=round(freshness, 2),
        coverage_score=round(coverage, 2),
        diversity_score=round(diversity, 2),
        engagement_score=round(engagement, 2),
        signals=signals,
        recommendation=recommendation,
    )


# ── Convenience for clusters ─────────────────────────────────────────────────

def trend_for_cluster(cluster: Any) -> TrendBreakdown:
    """Run trend detection on a StoryCluster-like object."""
    items = getattr(cluster, "items", []) or []
    latest = getattr(cluster, "latest", "")
    earliest = getattr(cluster, "earliest", "")
    return detect_trend(items, latest=latest, earliest=earliest)
