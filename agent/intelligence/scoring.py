"""Scoring utilities for the Content Intelligence Engine."""
from __future__ import annotations

from .models import AuthorityScores, ContentOpportunity, TrendSignal


def score_authority(signal: TrendSignal) -> AuthorityScores:
    """Score a candidate by how well it fits the BWA brand.

    We use the MAX dimension score as the total because a signal that is
    strongly Laravel, strongly Python, or strongly AI-agent is exactly what
    Build With Abdallah needs. The other dimensions are recorded for detail.
    """
    title_and_summary = f"{signal.title} {signal.summary}".lower()
    topics_blob = " ".join(signal.topics).lower().replace("-", " ")

    def dim_score(keywords: set[str]) -> int:
        matches = [kw for kw in keywords if kw in title_and_summary]
        # Base score from keyword matches in title/summary.
        base = min(len(matches) * 25, 60)
        # Strong boost if a brand-relevant topic tag is attached.
        topic_boost = 30 if any(kw in topics_blob for kw in keywords) else 0
        return min(base + topic_boost, 100)

    laravel = dim_score({"laravel", "php", "eloquent", "livewire", "filament"})
    python = dim_score({"python", "django", "fastapi", "flask", "pandas"})
    raspberry_pi = dim_score({"raspberry pi", "rpi", "gpio", "pi 5", "pi4", "embedded"})
    ai_automation = dim_score({"ai", "agent", "automation", "llm", "openai", "claude", "mcp", "workflow"})
    software_engineering = dim_score({"engineering", "tutorial", "devops", "testing", "architecture"})
    practical_build = dim_score({"build", "tutorial", "project", "deploy", "setup", "guide"})

    dimensions = [laravel, python, raspberry_pi, ai_automation, software_engineering, practical_build]
    # Max rewards clear specialization; average smooths jack-of-all-trades signals.
    total = int(max(dimensions) * 0.7 + (sum(dimensions) / len(dimensions)) * 0.3)
    return AuthorityScores(
        laravel=laravel,
        python=python,
        raspberry_pi=raspberry_pi,
        ai_automation=ai_automation,
        software_engineering=software_engineering,
        practical_build_potential=practical_build,
        total=min(total, 100),
    )


def passes_authority_filter(signal: TrendSignal, min_score: int = 50) -> bool:
    """Return True if a signal clears the authority floor."""
    return score_authority(signal).total >= min_score


# Keywords that conflict with the Build With Abdallah halal/ethical guardrails.
CONTENT_GUARD_KEYWORDS = {
    "trading", "forex", "margin", "leverage", "crypto trading",
    "binary options", "gambling", "betting", "casino",
}


def content_guard_adjustment(signal, kb=None) -> tuple[int, str]:
    """Return (score_penalty, note) for signals that may conflict with brand values."""
    text = f"{getattr(signal, 'title', '')} {getattr(signal, 'summary', '')}".lower()
    hits = [kw for kw in CONTENT_GUARD_KEYWORDS if kw in text]
    if hits:
        return -25, f"Guard: contains '{', '.join(hits)}' — verify alignment with halal goals."
    if kb:
        for rule in kb.rules:
            rkws = [k.lower() for k in rule.keywords]
            rule_hits = [k for k in rkws if k in text]
            if rule_hits and rule.weight < 0:
                return rule.weight, f"Guard ({rule.id}): '{', '.join(rule_hits)}'"
    return 0, ""


def compute_authority_with_knowledge(signal, kb=None) -> tuple[AuthorityScores, dict[str, Any]]:
    """Score authority using both generic brand dimensions and the BWA knowledge base."""
    base = score_authority(signal)
    knowledge_result: dict[str, Any] = {
        "expertise_score": 0,
        "stack_score": 0,
        "project_score": 0,
        "total_knowledge_score": 0,
        "matched_projects": [],
        "matches": [],
    }
    if kb is not None:
        from .knowledge import match_text_against_knowledge
        text = f"{signal.title} {signal.summary}".lower()
        knowledge_result = match_text_against_knowledge(text, kb)
        blended = int(base.total * 0.4 + knowledge_result["total_knowledge_score"] * 0.6)
        base.total = min(blended, 100)
    return base, knowledge_result


def score_tutorial_potential(signal: TrendSignal) -> int:
    """How well can this become a hands-on tutorial? 0-100."""
    text = f"{signal.title} {signal.summary}".lower()
    tutorial_markers = {
        "tutorial", "how to", "guide", "setup", "build", "deploy",
        "step-by-step", "example", "project", "from scratch", "walkthrough",
        "platform", "framework", "open-source", "self-host", "self-hostable",
    }
    matches = sum(1 for marker in tutorial_markers if marker in text)
    # Tool/framework names are inherently tutorial-able for BWA.
    tool_markers = {
        "n8n", "filament", "dify", "laravel", "livewire", "nextcloud",
        "coolify", "playwright", "puppeteer", "home assistant", "pi-hole",
        "autogpt", "openhands", "lobehub", "transformers",
    }
    tool_matches = sum(1 for marker in tool_markers if marker in text)
    return min(matches * 12 + tool_matches * 18 + 35, 100)


def score_social_potential(signal: TrendSignal) -> int:
    """How well does this translate to LinkedIn/FB/Shorts? 0-100."""
    text = f"{signal.title} {signal.summary}".lower()
    social_markers = {
        "new", "release", "launched", "announced", "comparison",
        "mistake", "secret", "nobody tells", "you should", "stop doing",
        "vs", "top", "best", "fastest", "free", "open source", "yc", "launch",
    }
    matches = sum(1 for marker in social_markers if marker in text)
    return min(matches * 12 + 40, 100)


def compute_opportunity_score(
    opp: ContentOpportunity,
    authority_weight: float = 1.0,
    audience_weight: float = 0.9,
    trend_weight: float = 0.7,
    performance_weight: float = 0.6,
    tutorial_weight: float = 1.4,
    social_weight: float = 0.5,
    gap_weight: float = 0.9,
) -> int:
    """Calculate a weighted opportunity score with heavy tutorial + gap weighting."""
    weighted = (
        opp.trend_score * trend_weight
        + opp.audience_score * audience_weight
        + opp.authority_score * authority_weight
        + opp.performance_score * performance_weight
        + opp.tutorial_potential * tutorial_weight
        + opp.social_potential * social_weight
        + (opp.gap_score or 0) * gap_weight
    )
    total_weight = (
        trend_weight + audience_weight + authority_weight
        + performance_weight + tutorial_weight + social_weight + gap_weight
    )
    opp.opportunity_score = int(weighted / total_weight)
    return opp.opportunity_score
