"""Opportunity calendar for the Content Intelligence Engine.

Phase 1 scope:
- Consume ranked opportunities, newsletter items, and audience pain signals.
- Build a 7-day editorial plan with primary content + secondary social posts per day.
- Never generate actual articles or scripts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import IntelligenceConfig
from .content_gap import load_existing_content
from .engine import IntelligenceEngine
from .knowledge import load_knowledge_base
from .models import AudiencePain, ContentOpportunity
from .newsletter_mining import NewsletterItem, collect_newsletter_items, score_newsletter_items

WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

DEFAULT_DAY_TEMPLATES: dict[str, str] = {
    "Monday": "main_tutorial_or_build_log",
    "Tuesday": "short_explainer",
    "Wednesday": "newsletter_reaction",
    "Thursday": "audience_question_tutorial",
    "Friday": "open_source_roundup",
    "Saturday": "quick_practical_tip",
    "Sunday": "weekly_recap",
}


@dataclass
class CalendarSlot:
    """A single content slot in the weekly plan."""

    title: str
    format: str
    reason: str
    evidence: str
    source_signal: str
    action: str
    related_projects: list[str] = field(default_factory=list)
    gap_status: str = ""
    risk_notes: list[str] = field(default_factory=list)
    secondary_angles: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


@dataclass
class DayPlan:
    """Plan for one day of the week."""

    day: str
    theme: str
    primary: CalendarSlot | None = None
    secondary: list[CalendarSlot] = field(default_factory=list)


@dataclass
class WeeklyCalendar:
    """Full 7-day editorial plan."""

    days: list[DayPlan]
    generated_at: str = ""


def _extract_topics_from_text(text: str) -> set[str]:
    """Extract simple topic tokens from text for duplicate detection."""
    lowered = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return set(lowered.split())


def _is_duplicate_or_similar(
    candidate: str,
    used: list[str],
    existing_content: list[Any],
    used_threshold: int = 3,
    existing_threshold: int = 2,
) -> bool:
    """Return True if candidate is too similar to already-used or existing content."""
    candidate_clean = candidate.strip().lower()
    # Exact title match.
    for title in used:
        if candidate_clean == title.strip().lower():
            return True
    candidate_tokens = _extract_topics_from_text(candidate)
    # A single-token title that exactly matches a used single token is a duplicate.
    if len(candidate_tokens) == 1:
        token = next(iter(candidate_tokens))
        for title in used:
            if _extract_topics_from_text(title) == {token}:
                return True
    for title in used:
        overlap = candidate_tokens & _extract_topics_from_text(title)
        if len(overlap) >= used_threshold:
            return True
    for item in existing_content:
        overlap = candidate_tokens & _extract_topics_from_text(item.title)
        if len(overlap) >= existing_threshold:
            return True
    return False


def _score_calendar_fitness(
    opp: ContentOpportunity | NewsletterItem | AudiencePain,
    prefer_tutorial: bool = False,
    prefer_newsletter: bool = False,
    prefer_audience: bool = False,
) -> int:
    """Score an item for calendar placement based on slot preference."""
    score = 0
    if isinstance(opp, ContentOpportunity):
        score += opp.opportunity_score * 0.5
        score += (opp.gap_score or 0) * 0.2
        score += opp.tutorial_potential * 0.15
        score += opp.knowledge_score * 0.15
        if prefer_tutorial:
            score += opp.tutorial_potential * 0.3
        if opp.gap_result and opp.gap_result.action == "create" and (opp.gap_score or 0) >= 80:
            score += 10
    elif isinstance(opp, NewsletterItem):
        score += opp.urgency_score * 0.5
        score += opp.tutorial_potential * 0.25
        score += opp.knowledge_score * 0.25
        if prefer_newsletter:
            score += 15
    elif isinstance(opp, AudiencePain):
        score += 70  # base
        score += min(opp.frequency * 5, 30)
        if opp.cross_platform:
            score += 10
        if prefer_audience:
            score += 20
    return int(score)


def _slot_from_opportunity(
    opp: ContentOpportunity | NewsletterItem | AudiencePain,
    slot_format: str,
    source_signal: str,
) -> CalendarSlot:
    """Convert an opportunity-like item into a CalendarSlot."""
    if isinstance(opp, ContentOpportunity):
        return CalendarSlot(
            title=opp.title,
            format=slot_format,
            reason=opp.why_it_matters,
            evidence="; ".join(opp.evidence[:3]) if opp.evidence else "ranked opportunity",
            source_signal=source_signal,
            action=opp.suggested_format,
            related_projects=opp.related_projects,
            gap_status=opp.gap_result.action if opp.gap_result else "unknown",
            risk_notes=opp.risk_notes,
            secondary_angles=opp.social_angles[:3] if opp.social_angles else [],
            topics=opp.knowledge_matches,
        )
    if isinstance(opp, NewsletterItem):
        return CalendarSlot(
            title=opp.title,
            format=slot_format,
            reason=opp.why_developers_care,
            evidence=f"source: {opp.source}",
            source_signal=source_signal,
            action=opp.action.replace("_", " "),
            related_projects=opp.related_projects,
            gap_status=opp.gap_status,
            risk_notes=[opp.metadata.get("guard_note", "")] if opp.metadata.get("guard_note") else [],
            secondary_angles=[f"LinkedIn post: {opp.title}"] if opp.social_potential else [],
            topics=opp.detected_technologies,
        )
    if isinstance(opp, AudiencePain):
        return CalendarSlot(
            title=opp.label,
            format=slot_format,
            reason=f"Recurring audience question ({opp.frequency}x)",
            evidence="; ".join(opp.evidence[:2]) if opp.evidence else "audience pain cluster",
            source_signal=source_signal,
            action="create tutorial",
            related_projects=[],
            gap_status="",
            risk_notes=[],
            secondary_angles=opp.suggested_angles[:3] if opp.suggested_angles else [],
            topics=list(opp.platforms),
        )
    raise TypeError(f"Unsupported opportunity type: {type(opp)}")


def _guard_ok(item: Any) -> bool:
    """Return False if item conflicts with guardrails."""
    text = ""
    risk_notes: list[str] = []
    if isinstance(item, ContentOpportunity):
        text = f"{item.title} {item.why_it_matters}"
        risk_notes = item.risk_notes
    elif isinstance(item, NewsletterItem):
        text = f"{item.title} {item.summary}"
        if item.metadata.get("guard_note"):
            risk_notes.append(item.metadata["guard_note"])
    elif isinstance(item, AudiencePain):
        text = item.label
    lower = text.lower()
    bad = {"trading", "forex", "margin", "leverage", "binary options", "gambling", "betting", "casino", "odds", "wagering"}
    if any(kw in lower for kw in bad):
        return False
    if any("guard" in note.lower() for note in risk_notes):
        return False
    return True


def build_weekly_calendar(
    opportunities: list[ContentOpportunity],
    newsletter_items: list[NewsletterItem],
    audience_pains: list[AudiencePain],
    existing_content: list[Any] | None = None,
    days: int = 7,
) -> WeeklyCalendar:
    """Build a 7-day editorial plan from intelligence outputs."""
    existing_content = existing_content or []
    used_titles: list[str] = []
    calendar_days: list[DayPlan] = []

    # Pre-score and filter.
    scored_opps = [(o, _score_calendar_fitness(o)) for o in opportunities if _guard_ok(o)]
    scored_opps.sort(key=lambda x: x[1], reverse=True)
    available_opps = [o for o, _ in scored_opps]

    scored_news = [(n, _score_calendar_fitness(n, prefer_newsletter=True)) for n in newsletter_items if _guard_ok(n)]
    scored_news.sort(key=lambda x: x[1], reverse=True)
    available_news = [n for n, _ in scored_news]

    scored_pains = [(p, _score_calendar_fitness(p, prefer_audience=True)) for p in audience_pains if _guard_ok(p)]
    scored_pains.sort(key=lambda x: x[1], reverse=True)
    available_pains = [p for p, _ in scored_pains]


    for idx, day in enumerate(WEEKDAYS[:days]):
        theme = DEFAULT_DAY_TEMPLATES[day]
        plan = DayPlan(day=day, theme=theme)

        if day == "Monday":
            primary = _pick_first_available(
                available_opps,
                used_titles,
                existing_content,
                prefer_tutorial=True,
                consume=True,
            )
            if primary:
                plan.primary = _slot_from_opportunity(primary, "long-form tutorial + LinkedIn/FB + YouTube Short", "top opportunity")
                used_titles.append(primary.title)

        elif day == "Tuesday" and plan.primary is None:
            # Secondary short based on Monday's primary if possible.
            if calendar_days and calendar_days[-1].primary:
                prev = calendar_days[-1].primary
                short_slot = CalendarSlot(
                    title=f"Short: {prev.title}",
                    format="YouTube Short + LinkedIn/FB post",
                    reason=f"Quick explainer derived from Monday's tutorial: {prev.title}",
                    evidence=prev.evidence,
                    source_signal=prev.source_signal,
                    action="create short",
                    related_projects=prev.related_projects,
                    gap_status=prev.gap_status,
                    risk_notes=prev.risk_notes,
                    secondary_angles=["YouTube Short 60s demo", "LinkedIn carousel key points"],
                    topics=prev.topics,
                )
                plan.primary = short_slot

        elif day == "Wednesday":
            if available_news:
                primary = available_news.pop(0)
                plan.primary = _slot_from_opportunity(primary, "LinkedIn/FB post + newsletter note", "newsletter mining")
                used_titles.append(primary.title)
            elif available_opps:
                primary = _pick_first_available(available_opps, used_titles, existing_content, prefer_newsletter=True, consume=True)
                if primary:
                    plan.primary = _slot_from_opportunity(primary, "LinkedIn/FB post", "ranked opportunity")
                    used_titles.append(primary.title)

        elif day == "Thursday":
            if available_pains:
                primary = available_pains.pop(0)
                plan.primary = _slot_from_opportunity(primary, "long-form tutorial", "audience pain radar")
            elif available_opps:
                primary = _pick_first_available(available_opps, used_titles, existing_content, prefer_audience=True, consume=True)
                if primary:
                    plan.primary = _slot_from_opportunity(primary, "long-form tutorial", "ranked opportunity")
                    used_titles.append(primary.title)

        elif day == "Friday":
            if plan.primary is None and available_opps:
                primary = _pick_first_available(available_opps, used_titles, existing_content, consume=True)
                if primary:
                    plan.primary = _slot_from_opportunity(primary, "technical build-log", "ranked opportunity")
                    used_titles.append(primary.title)

        elif day == "Saturday":
            primary = _pick_first_available(
                available_opps,
                used_titles,
                existing_content,
                prefer_tutorial=True,
                min_tutorial=55,
                consume=True,
            )
            if primary:
                plan.primary = _slot_from_opportunity(primary, "quick practical tip / LinkedIn post", "ranked opportunity")
                used_titles.append(primary.title)

        elif day == "Sunday":
            # Recap slot: summarize the week or use a low-friction opportunity.
            if available_opps:
                primary = _pick_first_available(available_opps, used_titles, existing_content, consume=True)
                if primary:
                    plan.primary = _slot_from_opportunity(primary, "weekly recap / what I learned", "ranked opportunity")
                    used_titles.append(primary.title)

        # Fallback: any remaining opportunity to avoid empty days.
        if plan.primary is None:
            if available_opps:
                primary = _pick_first_available(available_opps, used_titles, existing_content, consume=True)
                if primary:
                    plan.primary = _slot_from_opportunity(primary, "LinkedIn/FB post", "fallback opportunity")
                    used_titles.append(primary.title)
            elif available_news:
                primary = available_news.pop(0)
                plan.primary = _slot_from_opportunity(primary, "newsletter note", "fallback newsletter")
                used_titles.append(primary.title)
            elif available_pains and (day == "Thursday" or any(d.day == "Thursday" and d.primary for d in calendar_days)):
                primary = available_pains.pop(0)
                plan.primary = _slot_from_opportunity(primary, "audience tutorial", "fallback audience pain")

        # Add a secondary social slot if primary exists and has social potential.
        if plan.primary:
            plan.secondary = _derive_secondary_slots(plan.primary)

        calendar_days.append(plan)

    calendar = WeeklyCalendar(
        days=calendar_days,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    return calendar


def _pick_first_available(
    opportunities: list[Any],
    used_titles: list[str],
    existing_content: list[Any],
    prefer_tutorial: bool = False,
    prefer_newsletter: bool = False,
    prefer_audience: bool = False,
    topic_keywords: set[str] | None = None,
    min_tutorial: int = 0,
    consume: bool = False,
) -> Any | None:
    """Pick the best available opportunity that is not a duplicate."""
    scored = []
    for opp in opportunities:
        if _is_duplicate_or_similar(_title(opp), used_titles, existing_content):
            continue
        if isinstance(opp, ContentOpportunity) and opp.tutorial_potential < min_tutorial:
            continue
        score = _score_calendar_fitness(
            opp,
            prefer_tutorial=prefer_tutorial,
            prefer_newsletter=prefer_newsletter,
            prefer_audience=prefer_audience,
        )
        if topic_keywords and isinstance(opp, ContentOpportunity):
            text = f"{opp.title} {opp.why_it_matters}".lower()
            if any(kw in text for kw in topic_keywords):
                score += 20
        scored.append((opp, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored:
        return None
    selected = scored[0][0]
    if consume:
        opportunities.remove(selected)
    return selected


def _title(item: Any) -> str:
    return getattr(item, "title", getattr(item, "label", str(item)))


def _derive_secondary_slots(primary: CalendarSlot) -> list[CalendarSlot]:
    """Derive secondary social media angles from a primary slot."""
    slots: list[CalendarSlot] = []
    if "LinkedIn" not in primary.format:
        slots.append(
            CalendarSlot(
                title=f"LinkedIn/FB: {primary.title}",
                format="LinkedIn/FB post",
                reason=f"Distribution angle for {primary.title}",
                evidence=primary.evidence,
                source_signal=primary.source_signal,
                action="social post",
                related_projects=primary.related_projects,
                topics=primary.topics,
            )
        )
    if "YouTube Short" not in primary.format:
        slots.append(
            CalendarSlot(
                title=f"YouTube Short: {primary.title}",
                format="YouTube Short",
                reason=f"60-second demo or hook from {primary.title}",
                evidence=primary.evidence,
                source_signal=primary.source_signal,
                action="create short",
                related_projects=primary.related_projects,
                topics=primary.topics,
            )
        )
    slots.append(
        CalendarSlot(
            title=f"Telegram: {primary.title}",
            format="Telegram notification/preview",
            reason=f"Notify subscribers about {primary.title}",
            evidence=primary.evidence,
            source_signal=primary.source_signal,
            action="telegram notify",
            related_projects=primary.related_projects,
            topics=primary.topics,
        )
    )
    return slots


def generate_calendar_report(
    calendar: WeeklyCalendar,
    report_path: Path | None = None,
) -> Path:
    """Write the weekly editorial plan to a markdown report."""
    if report_path is None:
        report_path = (
            Path.home()
            / ".openclaw"
            / "workspace"
            / "performance"
            / "content-opportunity-calendar.md"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Build With Abdallah — Content Opportunity Calendar",
        f"Generated: {calendar.generated_at}",
        "",
        "> Editorial planning only. No content generated.",
        "",
    ]

    for day in calendar.days:
        lines.append(f"## {day.day}")
        lines.append(f"**Theme:** {day.theme}")
        lines.append("")
        if day.primary:
            p = day.primary
            lines.append("### Primary")
            lines.append(f"- **Title:** {p.title}")
            lines.append(f"- **Format:** {p.format}")
            lines.append(f"- **Why this topic:** {p.reason}")
            lines.append(f"- **Evidence:** {p.evidence}")
            lines.append(f"- **Source signal:** {p.source_signal}")
            lines.append(f"- **Suggested action:** {p.action}")
            if p.related_projects:
                lines.append(f"- **Related BWA projects:** {', '.join(p.related_projects)}")
            if p.gap_status:
                lines.append(f"- **Content gap status:** {p.gap_status}")
            if p.risk_notes:
                lines.append("- **Guardrails:**")
                for note in p.risk_notes:
                    if note:
                        lines.append(f"  - {note}")
            if p.topics:
                lines.append(f"- **Knowledge match:** {', '.join(sorted(set(p.topics)))}")
            lines.append("")
        else:
            lines.append("_No primary slot assigned._")
            lines.append("")

        if day.secondary:
            lines.append("### Secondary / Social")
            for s in day.secondary:
                lines.append(f"- **{s.format}:** {s.title}")
                if s.action:
                    lines.append(f"  - action: {s.action}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Weekly Guardrails")
    lines.append("")
    lines.append("- No duplicate topics across primary slots.")
    lines.append("- No betting/gambling/leverage/trading content.")
    lines.append("- High-gap-score tutorials prioritized early in the week.")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def run_calendar_pipeline(
    days: int = 7,
    report_path: str | None = None,
    include_newsletter: bool = True,
    include_audience: bool = True,
    top_n: int = 20,
) -> Path:
    """Run the intelligence engine if needed, then build the weekly calendar."""
    config = IntelligenceConfig()

    print("📚 Loading BuildWithAbdallah knowledge base")
    kb = load_knowledge_base()

    print("🔍 Loading existing content")
    existing_content = load_existing_content(config)

    print("🔭 Collecting trend signals")
    from .sources import collect_trend_signals
    all_signals = collect_trend_signals(config)

    print("📰 Collecting newsletter items")
    newsletter_items: list[NewsletterItem] = []
    if include_newsletter:
        newsletter_items = score_newsletter_items(
            collect_newsletter_items(), kb, existing_content=existing_content
        )
        all_signals.extend(_newsletter_to_trend_signals(newsletter_items[:30]))

    print("🗣️  Collecting audience pain signals")
    from .audience import collect_audience_pain
    audience_pains = collect_audience_pain(config, live=False, text_fallback=True, sources=None)

    print("📈 Collecting performance insights")
    from .performance import collect_performance_insights
    performance_insights = collect_performance_insights(config)

    print("🎯 Building ranked opportunities")
    from .engine import _signals_to_opportunities
    opportunities = _signals_to_opportunities(
        all_signals, audience_pains, performance_insights, existing_content, config, kb
    )

    print("📅 Building weekly calendar")
    calendar = build_weekly_calendar(
        opportunities[:top_n],
        newsletter_items if include_newsletter else [],
        audience_pains if include_audience else [],
        existing_content,
        days=days,
    )

    path = Path(report_path) if report_path else None
    return generate_calendar_report(calendar, path)


def _newsletter_to_trend_signals(items: list[NewsletterItem]) -> list[Any]:
    from .models import TrendSignal
    return [
        TrendSignal(
            title=item.title,
            source=f"newsletter:{item.source}",
            url=item.url,
            summary=item.summary,
            topics=item.detected_technologies,
            published=item.published_at,
            raw={"action": item.action, "urgency_score": item.urgency_score},
        )
        for item in items
    ]
