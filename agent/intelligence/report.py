"""Markdown report generation for the Content Intelligence Engine."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .newsletter_mining import NewsletterItem, generate_newsletter_report
from .performance_sources.pitch_agent import summarize_pitch_agent_metrics
from .models import (
    AudiencePain,
    ContentGapResult,
    ContentOpportunity,
    ExistingContentItem,
    PerformanceInsight,
    TrendSignal,
)


def _fmt_date(value: str | None) -> str:
    return value or "unknown"


def generate_report(
    opportunities: list[ContentOpportunity],
    trend_signals: list[TrendSignal],
    audience_pains: list[AudiencePain],
    performance_insights: list[PerformanceInsight],
    existing_content: list[ExistingContentItem],
    report_path: Path,
    pitch_posts: list | None = None,
    newsletter_items: list[NewsletterItem] | None = None,
) -> Path:
    """Write the content intelligence report to disk."""
    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines.append("# Build With Abdallah — Content Intelligence Report")
    lines.append(f"Generated: {now}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(
        f"- **Trend signals scanned:** {len(trend_signals)}\n"
        f"- **Audience pain clusters:** {len(audience_pains)}\n"
        f"- **Performance insights:** {len(performance_insights)}\n"
        f"- **Ranked opportunities:** {len(opportunities)}\n"
    )
    lines.append("")
    lines.append(
        "This report is **intelligence only**. It surfaces and scores content "
        "opportunities for the BuildWithAbdallah brand. It does not generate or "
        "publish content."
    )
    lines.append("")
    lines.append("### Methodology")
    lines.append("")
    lines.append(
        "Opportunities are scored across five layers: Trend Radar, "
        "Audience Pain Radar, Authority Filter, Performance Intelligence, "
        "and Opportunity Engine. Tutorial potential is weighted heavily. "
        "A content guard reduces scores for topics containing "
        "trading/forex/leverage/gambling keywords."
    )
    lines.append("")

    lines.append("## Top Opportunities")
    lines.append("")
    if not opportunities:
        lines.append("_No opportunities met the authority filter this run._")
        lines.append("")
    for idx, opp in enumerate(opportunities, 1):
        lines.append(f"### {idx}. {opp.title}")
        lines.append("")
        lines.append(f"**Opportunity Score:** {opp.opportunity_score}/100")
        lines.append("")
        lines.append(f"**Score Breakdown:** {opp.score_breakdown}")
        lines.append("")
        if opp.gap_result:
            gap = opp.gap_result
            lines.append(f"**Content Gap Score:** {gap.gap_score}/100")
            lines.append(f"**Duplicate Risk:** {gap.duplicate_risk}")
            lines.append(f"**Suggested Action:** {gap.action}")
            if gap.reason:
                lines.append(f"**Gap Reason:** {gap.reason}")
            if gap.related_items:
                lines.append("**Existing Related Content:**")
                for item in gap.related_items[:3]:
                    lines.append(f"- [{item.title}]({item.url})")
            lines.append("")
        lines.append(f"**Why It Matters:** {opp.why_it_matters}")
        lines.append("")
        if opp.knowledge_matches:
            lines.append(f"**Knowledge Match:** {', '.join(sorted(set(opp.knowledge_matches)))}")
            lines.append("")
        if opp.related_projects:
            lines.append(f"**Related BWA Projects:** {', '.join(opp.related_projects)}")
            lines.append("")
        if opp.risk_notes:
            lines.append("**Risk / Guardrail Notes:**")
            for note in opp.risk_notes:
                lines.append(f"- {note}")
            lines.append("")
        if opp.evidence:
            lines.append("**Evidence:**")
            for item in opp.evidence:
                lines.append(f"- {item}")
            lines.append("")
        lines.append(f"**Suggested Format:** {opp.suggested_format}")
        lines.append("")
        if opp.tutorial_angles:
            lines.append("**Tutorial Potential:**")
            for angle in opp.tutorial_angles:
                lines.append(f"- {angle}")
            lines.append("")
        if opp.social_angles:
            lines.append("**Social Media Potential:**")
            for angle in opp.social_angles:
                lines.append(f"- {angle}")
            lines.append("")
        if opp.source_urls:
            lines.append("**Sources:**")
            for url in opp.source_urls[:5]:
                lines.append(f"- {url}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Pitch Agent / World Cup Performance")
    lines.append("")
    if pitch_posts:
        summary = summarize_pitch_agent_metrics(pitch_posts)
        lines.append(f"**Should Continue?** {summary.recommendation}")
        lines.append("")
        lines.append(f"**Reason:** {summary.reason}")
        lines.append("")
        total_views = sum(p.views for p in pitch_posts)
        lines.append(
            f"- **Posts analyzed:** {len(pitch_posts)} | **Views:** {total_views} | "
            f"**Website CTR:** {summary.website_ctr:.2%}"
        )
        if summary.best_posts:
            lines.append("- **Best-aligned posts:**")
            for post in summary.best_posts:
                fit = post.metadata.get("fit_score", 0)
                lines.append(
                    f"  - {post.title} ({post.content_type}) — fit {fit}/100"
                )
        if summary.worst_posts:
            lines.append("- **Worst-aligned posts:**")
            for post in summary.worst_posts:
                fit = post.metadata.get("fit_score", 0)
                lines.append(
                    f"  - {post.title} ({post.content_type}) — fit {fit}/100"
                )
    else:
        lines.append("_Pitch Agent metrics not loaded. Add data to `~/.openclaw/workspace/performance/`._")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Newsletter / Release Mining")
    lines.append("")
    if newsletter_items:
        lines.append(f"**Newsletter items mined:** {len(newsletter_items)}")
        lines.append("")
        if not newsletter_items:
            lines.append("_No newsletter items met the minimum score this run._")
        for idx, item in enumerate(newsletter_items[:10], 1):
            lines.append(f"### {idx}. {item.title}")
            lines.append(f"- **Source:** {item.source}")
            lines.append(f"- **URL:** {item.url}")
            if item.published_at:
                lines.append(f"- **Published:** {item.published_at}")
            lines.append(f"- **Why Developers Care:** {item.why_developers_care}")
            lines.append(f"- **BWA Angle:** {item.possible_bwa_angle}")
            lines.append(f"- **Tutorial Potential:** {item.tutorial_potential}/100")
            lines.append(f"- **Urgency Score:** {item.urgency_score}/100")
            if item.gap_status and item.gap_status != "unknown":
                lines.append(f"- **Content Gap Status:** {item.gap_status}")
            lines.append(f"- **Suggested Action:** {item.action.replace('_', ' ')}")
            if item.related_projects:
                lines.append(f"- **Related BWA Projects:** {', '.join(item.related_projects)}")
            if item.metadata.get("guard_note"):
                lines.append(f"- **Guard Note:** {item.metadata['guard_note']}")
            lines.append("")
    else:
        lines.append("_Newsletter mining not enabled. Run with `--newsletter-mining`._")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## High-Demand Content Gaps")
    lines.append("")
    gaps = [opp for opp in opportunities if opp.gap_result and opp.gap_result.gap_score >= 70]
    if not gaps:
        lines.append("_No high-demand content gaps detected this run._")
    else:
        for idx, opp in enumerate(gaps, 1):
            gap = opp.gap_result
            lines.append(f"### {idx}. {opp.title}")
            lines.append(f"- **Gap Score:** {gap.gap_score}/100")
            lines.append(f"- **Audience Demand:** {opp.audience_score}/100")
            lines.append(f"- **Knowledge Match:** {', '.join(sorted(set(opp.knowledge_matches))) or 'none'}")
            if gap.related_items:
                lines.append("- **Existing Related Content:**")
                for item in gap.related_items[:3]:
                    lines.append(f"  - [{item.title}]({item.url})")
            else:
                lines.append("- **Existing Related Content:** none")
            lines.append(f"- **Why This Is A Gap:** {gap.reason}")
            lines.append(f"- **Recommended Next Action:** {gap.action}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Appendix A — Trend Signals")
    lines.append("")
    if not trend_signals:
        lines.append("_No trend signals collected._")
    else:
        for sig in trend_signals[:30]:
            lines.append(f"- **[{sig.source}]** [{sig.title}]({sig.url})")
            if sig.summary:
                lines.append(f"  - {sig.summary[:200]}")
            if sig.topics:
                lines.append(f"  - topics: {', '.join(sig.topics)}")
    lines.append("")

    lines.append("## Appendix B — Audience Pain Points")
    lines.append("")
    if not audience_pains:
        lines.append("_No audience samples loaded. Drop comments into `~/.openclaw/workspace/audience/`*")
    else:
        for pain in audience_pains:
            lines.append(f"### {pain.label}")
            lines.append(f"- channels: {pain.channel}")
            lines.append(f"- frequency: {pain.frequency}")
            lines.append(f"- cross-platform: {'yes' if pain.cross_platform else 'no'}")
            if pain.recency_days is not None:
                lines.append(f"- recency: {pain.recency_days} days ago")
            if pain.engagement_total:
                lines.append(f"- total engagement: {pain.engagement_total}")
            if pain.evidence:
                lines.append("- evidence:")
                for ev in pain.evidence[:3]:
                    lines.append(f"  - {ev}")
            lines.append("")

    lines.append("## Appendix C — Performance Insights")
    lines.append("")
    if not performance_insights:
        lines.append("_No historical performance data available._")
    else:
        for insight in performance_insights:
            lines.append(f"- **{insight.category}** ({insight.format}) — hits: {insight.hits}")
            lines.append(f"  - {insight.pattern}")
    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
