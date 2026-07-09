"""Intelligent feed orchestration for smkit feed.

Wires together all six phases:
    1. Authority scoring      (agent.feed_authority)
    2. Story clustering       (agent.feed_clustering)
    3. Trend detection        (agent.feed_trends)
    4. Opportunity engine     (agent.feed_opportunity)
    5. Recommendation engine  (agent.feed_recommendations)
    6. Content brief hook     (agent.feed_content_hook)

Produces ranked "intelligent feed cards" for `smkit feed --intelligence`.

No publishing happens here. Cards are data only.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.feed import FeedItem, build_feed, load_profile_with_interests
from agent.feed_authority import item_authority
from agent.feed_clustering import StoryCluster, cluster_items
from agent.feed_content_hook import ContentBrief, build_brief
from agent.feed_opportunity import OpportunityBreakdown, opportunity_for_cluster
from agent.feed_recommendations import FormatRecommendation, recommend_format
from agent.feed_trends import TrendBreakdown, trend_for_cluster

INTELLIGENCE_DIR = Path(__file__).resolve().parents[1] / "content" / "feed" / "intelligence"


@dataclass
class IntelligenceCard:
    cluster: StoryCluster | None = None
    authority: dict[str, Any] = field(default_factory=dict)
    trend: dict[str, Any] = field(default_factory=dict)
    opportunity: dict[str, Any] = field(default_factory=dict)
    recommendation: dict[str, Any] = field(default_factory=dict)
    brief: dict[str, Any] | None = None
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "cluster": self.cluster.to_dict() if self.cluster else {},
            "authority": self.authority,
            "trend": self.trend,
            "opportunity": self.opportunity,
            "recommendation": self.recommendation,
            "brief": self.brief,
        }


def run_intelligent_feed(
    topic: str | None = None,
    profile_name: str = "default",
    limit: int = 10,
    excluded_sources: list[str] | None = None,
    use_llm: bool = False,
    existing_content: list[Any] | None = None,
) -> list[IntelligenceCard]:
    """Run the full intelligence pipeline and return ranked cards."""
    profile = load_profile_with_interests(profile_name)
    interests = [i.lower() for i in profile.get("interests", [])]

    # Phase 0: fetch raw feed items.
    items = build_feed(
        topic=topic,
        profile_name=profile_name,
        limit=max(limit * 3, 30),
        excluded_sources=excluded_sources,
        use_llm=use_llm,
    )

    # Phase 1/2: cluster stories.
    clusters = cluster_items(items)

    cards: list[IntelligenceCard] = []
    for cluster in clusters:
        rep = cluster.representative
        if not rep:
            continue

        # Phase 1: authority breakdown.
        auth_breakdown = item_authority(rep.url, rep.source, metadata=getattr(rep, "metadata", None))

        # Phase 3: trend detection.
        trend_breakdown = trend_for_cluster(cluster)

        # Phase 4: opportunity scoring.
        opp_breakdown = opportunity_for_cluster(cluster, interests=interests)
        if existing_content is not None:
            opp_breakdown = opportunity_for_cluster(cluster, interests=interests)

        # Phase 5: content format recommendation.
        rec = recommend_format(
            opp_breakdown,
            trend_direction=trend_breakdown.direction,
            title=getattr(rep, "title", ""),
            summary=getattr(rep, "summary", ""),
            interests=interests,
        )

        card = IntelligenceCard(
            cluster=cluster,
            authority=auth_breakdown.to_dict(),
            trend=trend_breakdown.to_dict(),
            opportunity=opp_breakdown.to_dict(),
            recommendation=rec.to_dict(),
        )
        cards.append(card)

    # Rank by opportunity score descending.
    cards.sort(key=lambda c: c.opportunity.get("opportunity_score", 0), reverse=True)
    for i, card in enumerate(cards[:limit], 1):
        card.rank = i
    return cards[:limit]


def generate_brief_for_top(
    cards: list[IntelligenceCard],
    profile_name: str = "default",
) -> ContentBrief | None:
    """Generate a content brief for the top-ranked non-skip opportunity."""
    for card in cards:
        rec = card.recommendation
        if rec.get("recommendation") == "skip":
            continue
        cluster = card.cluster
        if not cluster:
            continue
        from agent.feed_recommendations import FormatRecommendation

        rec_obj = FormatRecommendation(
            recommendation=rec.get("recommendation", "blog"),
            confidence_score=rec.get("confidence_score", 0),
            suggested_angle=rec.get("suggested_angle", ""),
            suggested_hook=rec.get("suggested_hook", ""),
        )
        brief = build_brief(cluster, rec_obj)
        card.brief = brief.to_dict()
        return brief
    return None


def save_intelligence(
    cards: list[IntelligenceCard],
    path: Path | None = None,
    brief: ContentBrief | None = None,
) -> Path:
    INTELLIGENCE_DIR.mkdir(parents=True, exist_ok=True)
    if path is None:
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M")
        path = INTELLIGENCE_DIR / f"{today}.json"
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "count": len(cards),
        "cards": [card.to_dict() for card in cards],
    }
    if brief is not None:
        payload["top_brief"] = brief.to_dict()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def print_intelligence(cards: list[IntelligenceCard], brief: ContentBrief | None = None) -> None:
    if not cards:
        print("\nNo intelligent feed cards produced.")
        return
    print(f"\n🧠 smkit feed --intelligence — {len(cards)} cards\n")
    for card in cards:
        opp = card.opportunity
        rec = card.recommendation
        print(f"{card.rank}. {card.cluster.headline if card.cluster else '(no headline)'}")
        print(f"   Opportunity: {opp.get('opportunity_score')} | Trend: {card.trend.get('direction')} | Authority: {card.authority.get('final_score')}")
        print(f"   Recommendation: {rec.get('recommendation')} (confidence {rec.get('confidence_score')})")
        print(f"   Reason: {rec.get('reason')}")
        if card.cluster:
            print(f"   Sources: {', '.join(card.cluster.sources)} | URLs: {len(card.cluster.urls)}")
        print()
    if brief:
        print("=" * 50)
        print(f"📝 Top brief: {brief.content_type}")
        print(f"   Title: {brief.title}")
        print(f"   Hook: {brief.hook}")
        print(f"   Angle: {brief.angle}")
        print(f"   Key points: {', '.join(brief.key_points)}")
        print(f"   CTA: {brief.call_to_action}")
