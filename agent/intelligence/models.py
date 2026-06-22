"""Data models for content intelligence."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrendSignal:
    """A raw trend or release signal from Layer 1."""

    title: str
    source: str
    url: str
    summary: str = ""
    topics: list[str] = field(default_factory=list)
    published: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExistingContentItem:
    """A piece of existing BuildWithAbdallah content."""

    title: str
    url: str
    slug: str = ""
    category: str = ""
    published_at: str | None = None
    source: str = ""
    topics: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class ContentGapResult:
    """Result of comparing an opportunity to existing content."""

    gap_score: int = 0
    duplicate_risk: str = "unknown"
    action: str = "create"
    related_items: list[ExistingContentItem] = field(default_factory=list)
    reason: str = ""


@dataclass
class AudienceSignal:
    """A normalized audience message from any platform."""

    platform: str
    text: str
    author: str = ""
    url: str = ""
    published_at: str | None = None
    source_id: str = ""
    engagement_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AudiencePain:
    """A recurring audience pain point from Layer 2."""

    label: str
    evidence: list[str] = field(default_factory=list)
    channel: str = ""
    frequency: int = 1
    suggested_angles: list[str] = field(default_factory=list)
    platforms: set[str] = field(default_factory=set)
    recency_days: int | None = None
    cross_platform: bool = False
    engagement_total: int = 0


@dataclass
class AuthorityScores:
    """Layer 3 authority scoring for a candidate topic."""

    laravel: int = 0
    python: int = 0
    raspberry_pi: int = 0
    ai_automation: int = 0
    software_engineering: int = 0
    practical_build_potential: int = 0
    total: int = 0


@dataclass
class PerformanceInsight:
    """Layer 4 insight from historical content performance."""

    category: str
    format: str
    avg_engagement: float = 0.0
    hits: int = 0
    pattern: str = ""


@dataclass
class ContentOpportunity:
    """Layer 5 final ranked opportunity."""

    title: str
    trend_score: int = 0
    audience_score: int = 0
    authority_score: int = 0
    performance_score: int = 0
    knowledge_score: int = 0
    gap_score: int = 0
    tutorial_potential: int = 0
    social_potential: int = 0
    opportunity_score: int = 0
    why_it_matters: str = ""
    evidence: list[str] = field(default_factory=list)
    suggested_format: str = ""
    tutorial_angles: list[str] = field(default_factory=list)
    social_angles: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    related_projects: list[str] = field(default_factory=list)
    knowledge_matches: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    gap_result: ContentGapResult | None = None

    @property
    def score_breakdown(self) -> str:
        return (
            f"trend={self.trend_score} audience={self.audience_score} "
            f"authority={self.authority_score} knowledge={self.knowledge_score} "
            f"gap={self.gap_score} performance={self.performance_score} "
            f"tutorial={self.tutorial_potential} social={self.social_potential}"
        )
