"""Performance intelligence for Layer 4."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import history
from .config import IntelligenceConfig
from .models import PerformanceInsight
from .performance_sources.pitch_agent import (
    collect_pitch_agent_metrics,
    summarize_pitch_agent_metrics,
)


def _load_smkit_history() -> list[dict[str, Any]]:
    """Load published runs from smkit history if available."""
    try:
        return history.load()
    except Exception:
        return []


def _load_performance_json(config: IntelligenceConfig) -> list[PerformanceInsight]:
    """Load optional performance.json from workspace."""
    path = (
        Path.home()
        / ".openclaw"
        / "workspace"
        / "content"
        / "intelligence"
        / "performance.json"
    )
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [PerformanceInsight(**item) for item in raw if isinstance(item, dict)]
    except Exception:
        return []


def _pitch_agent_performance_insights(config: IntelligenceConfig) -> list[PerformanceInsight]:
    """Derive performance insights from Pitch Agent / World Cup metrics."""
    if not getattr(config, "enable_pitch_agent", False):
        return []
    posts = collect_pitch_agent_metrics()
    if not posts:
        return []
    summary = summarize_pitch_agent_metrics(posts)
    insights: list[PerformanceInsight] = []

    # Only boost if the recommendation is YES or CONDITIONAL.
    if summary.recommendation in {"YES", "CONDITIONAL"}:
        technical_keywords = {
            "sports analytics",
            "ai prediction",
            "prediction model",
            "playwright",
            "ffmpeg",
            "telegram",
            "automation",
            "raspberry pi",
            "api pipeline",
            "data pipeline",
            "video pipeline",
        }
        total_views = sum(p.views for p in posts) or 1
        avg_views = total_views / len(posts)
        for keyword in technical_keywords:
            insights.append(
                PerformanceInsight(
                    category=keyword,
                    format="short",
                    hits=int(avg_views),
                    pattern=(
                        f"Pitch Agent technical content performing: recommendation={summary.recommendation}, "
                        f"website_ctr={summary.website_ctr:.2%}"
                    ),
                )
            )
    return insights


def collect_performance_insights(config: IntelligenceConfig) -> list[PerformanceInsight]:
    """Build performance intelligence from history + optional metrics + Pitch Agent."""
    if not config.enable_performance:
        return []
    insights: list[PerformanceInsight] = []

    # Optional explicit performance file takes precedence.
    insights.extend(_load_performance_json(config))

    # Derive coarse insights from smkit history.
    hist = _load_smkit_history()
    if hist:
        topic_buckets: dict[str, int] = {}
        for entry in hist:
            topic = entry.get("topic", "").lower()
            for keyword in ["laravel", "python", "raspberry", "ai", "agent", "automation"]:
                if keyword in topic:
                    topic_buckets[keyword] = topic_buckets.get(keyword, 0) + 1
        for keyword, count in sorted(topic_buckets.items(), key=lambda x: x[1], reverse=True):
            insights.append(
                PerformanceInsight(
                    category=keyword,
                    format="tutorial",
                    hits=count,
                    pattern=f"{keyword.title()} topics appear frequently in publishing history",
                )
            )

    # Pitch Agent / World Cup metrics.
    insights.extend(_pitch_agent_performance_insights(config))
    return insights


def score_by_performance(signal: Any, insights: list[PerformanceInsight]) -> int:
    """Return a 0-100 score based on how well a signal matches winning categories."""
    text = f"{getattr(signal, 'title', '')} {getattr(signal, 'summary', '')}".lower()
    if not insights:
        return 50  # neutral when no data
    total_hits = sum(insight.hits or 1 for insight in insights)
    if total_hits == 0:
        return 50
    score = 0
    for insight in insights:
        category = insight.category.lower()
        if category in text:
            weight = (insight.hits or 1) / total_hits
            score += int(80 * weight)
    return min(score + 20, 100)
