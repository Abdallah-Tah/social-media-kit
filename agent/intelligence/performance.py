"""Performance intelligence for Layer 4."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import history
from .config import IntelligenceConfig
from .models import PerformanceInsight


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
