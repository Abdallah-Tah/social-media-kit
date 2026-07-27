"""Core Content Intelligence Engine orchestration."""
from __future__ import annotations

from .audience import collect_audience_pain
from .audience_sources import collect_telegram_signals, collect_website_signals, collect_youtube_signals
from .config import IntelligenceConfig
from .content_gap import detect_content_gap, load_existing_content
from .knowledge import load_knowledge_base
from .models import ContentOpportunity, TrendSignal
from .newsletter_mining import collect_newsletter_items, score_newsletter_items, items_to_trend_signals
from .performance import collect_performance_insights, score_by_performance
from .report import generate_report
from .scoring import (
    compute_authority_with_knowledge,
    compute_opportunity_score,
    content_guard_adjustment,
    passes_authority_filter,
    score_social_potential,
    score_tutorial_potential,
)
from .sources import collect_trend_signals


def _signals_to_opportunities(
    signals: list[TrendSignal],
    audience_pains: list,
    performance_insights: list,
    existing_content: list,
    config: IntelligenceConfig,
    kb,
) -> list[ContentOpportunity]:
    """Convert trend signals into scored opportunities using the BWA knowledge base."""
    opportunities: list[ContentOpportunity] = []

    # Build quick lookup for audience pain boost.
    pain_text = " ".join(p.label.lower() for p in audience_pains)

    for signal in signals:
        if not passes_authority_filter(signal, config.min_authority_score):
            continue

        authority, knowledge = compute_authority_with_knowledge(signal, kb)

        # Audience score: does this signal overlap with known pains?
        signal_text = f"{signal.title} {signal.summary}".lower()
        audience_score = 45
        for pain in audience_pains:
            pain_words = set(pain.label.lower().rstrip("?").split())
            overlap = pain_words & set(signal_text.split())
            if overlap:
                audience_score = min(audience_score + 12, 100)
            # Cross-platform pain gets extra weight.
            if pain.cross_platform:
                audience_score = min(audience_score + 8, 100)
            # Recent pain gets extra weight.
            if pain.recency_days is not None and pain.recency_days <= 7:
                audience_score = min(audience_score + 8, 100)
            # High engagement gets extra weight.
            if pain.engagement_total >= 5:
                audience_score = min(audience_score + 5, 100)
        if pain_text and any(word in pain_text for word in signal_text.split()):
            audience_score = min(audience_score + 10, 100)

        # Trend score decays with volume of overlapping topics; keep simple here.
        trend_score = min(50 + len(signal.topics) * 10, 100)

        # Performance score from historical data.
        performance_score = score_by_performance(signal, performance_insights)

        tutorial = score_tutorial_potential(signal)
        social = score_social_potential(signal)

        # Content gap detection.
        gap_result = detect_content_gap(signal.title, signal.summary, existing_content)

        why = _build_why_it_matters(signal, authority, tutorial, social, knowledge, kb, audience_pains)

        opp = ContentOpportunity(
            title=signal.title,
            trend_score=trend_score,
            audience_score=audience_score,
            authority_score=authority.total,
            knowledge_score=knowledge["total_knowledge_score"],
            gap_score=gap_result.gap_score,
            performance_score=performance_score,
            tutorial_potential=tutorial,
            social_potential=social,
            why_it_matters=why,
            evidence=[f"source: {signal.source}"] + signal.topics,
            suggested_format=_pick_format(tutorial, social, knowledge, gap_result),
            tutorial_angles=_tutorial_angles(signal, tutorial),
            social_angles=_social_angles(signal, social),
            source_urls=[signal.url],
            related_projects=knowledge["matched_projects"],
            knowledge_matches=[m[0] for m in knowledge.get("expertise_matches", [])]
            + [m[0] for m in knowledge.get("stack_matches", [])],
            risk_notes=[],
            gap_result=gap_result,
        )
        compute_opportunity_score(opp)

        # Apply brand guardrails after scoring so they show in the report.
        penalty, guard_note = content_guard_adjustment(signal, kb)
        if penalty:
            opp.opportunity_score = max(0, opp.opportunity_score + penalty)
            opp.risk_notes.append(guard_note)

        opportunities.append(opp)

    # Add audience-pain-only opportunities if no signal matched them.
    for pain in audience_pains[:5]:
        if not any(pain.label.lower() in opp.title.lower() for opp in opportunities):
            full_question = pain.evidence[0].split("]", 1)[-1].strip() if pain.evidence else pain.label
            from .knowledge import match_text_against_knowledge
            pain_knowledge = match_text_against_knowledge(pain.label.lower(), kb)
            knowledge_score = pain_knowledge["total_knowledge_score"]
            related_projects = pain_knowledge["matched_projects"]
            knowledge_matches = [m[0] for m in pain_knowledge.get("expertise_matches", [])]
            gap_result = detect_content_gap(pain.label, "", existing_content)
            opp = ContentOpportunity(
                title=pain.label,
                trend_score=40,
                audience_score=min(60 + pain.frequency * 5, 100),
                authority_score=70,
                knowledge_score=knowledge_score,
                gap_score=gap_result.gap_score,
                performance_score=50,
                tutorial_potential=85,
                social_potential=60,
                why_it_matters=f"Recurring audience question: '{full_question}'",
                evidence=pain.evidence[:3],
                suggested_format=_pick_format(85, 60, None, gap_result),
                tutorial_angles=pain.suggested_angles,
                social_angles=[f"LinkedIn/FB post: {pain.label} — what's your take?"],
                related_projects=related_projects,
                knowledge_matches=knowledge_matches,
                risk_notes=[],
                gap_result=gap_result,
            )
            compute_opportunity_score(opp)
            opportunities.append(opp)

    return sorted(opportunities, key=lambda o: o.opportunity_score, reverse=True)


def _build_why_it_matters(
    signal: TrendSignal,
    authority,
    tutorial: int,
    social: int,
    knowledge: dict,
    kb,
    audience_pains: list | None = None,
) -> str:
    """Generate a concise, specific reason this opportunity matters for BWA."""
    signal_text = f"{signal.title} {signal.summary}".lower()
    parts = [f"Strong BWA authority fit ({authority.total}/100)."]
    if knowledge.get("matched_projects"):
        projects = ", ".join(knowledge["matched_projects"][:3])
        parts.append(f"Connects to existing BWA projects: {projects}.")
    if knowledge.get("expertise_matches"):
        areas = ", ".join({m[0] for m in knowledge["expertise_matches"]})
        parts.append(f"Matches core expertise: {areas}.")

    if audience_pains:
        matched_pains = []
        for pain in audience_pains:
            pain_words = set(pain.label.lower().rstrip("?").split())
            if pain_words & set(signal_text.split()):
                matched_pains.append(pain)
        if matched_pains:
            top = matched_pains[0]
            parts.append(
                f"Audience demand ({top.frequency}x on {top.channel}, "
                f"{'cross-platform' if top.cross_platform else 'single platform'})."
            )

    if tutorial >= 75:
        parts.append(f"High tutorial potential ({tutorial}/100) — can become a build-and-deploy post.")
    elif tutorial >= 55:
        parts.append(f"Tutorial potential ({tutorial}/100) — can become a hands-on walkthrough.")
    if social >= 65:
        parts.append(f"Strong social hook ({social}/100) — works well for LinkedIn/FB/Shorts.")
    if signal.source.startswith("hacker-news"):
        parts.append("HN launch signal — timely discussion topic.")
    elif signal.source.startswith("github-trending"):
        parts.append("Trending on GitHub — developer tooling momentum.")
    return " ".join(parts)


def _pick_format(
    tutorial: int,
    social: int,
    knowledge: dict | None = None,
    gap_result = None,
) -> str:
    # Respect high duplicate risk from gap detection.
    if gap_result and gap_result.duplicate_risk == "high":
        return "skip — duplicate content exists"
    if gap_result and gap_result.action == "update":
        return "update existing tutorial + LinkedIn/FB post"
    if gap_result and gap_result.action == "create-short":
        return "LinkedIn/FB post + YouTube Short"

    kb_bonus = 0
    if knowledge and knowledge.get("total_knowledge_score", 0) >= 50:
        kb_bonus = 10
    effective_tutorial = tutorial + kb_bonus
    effective_social = social + kb_bonus
    if effective_tutorial >= 65 and effective_social >= 45:
        return "long-form tutorial + LinkedIn/FB post + YouTube Short"
    if effective_tutorial >= 65:
        return "long-form tutorial + YouTube Short"
    if effective_social >= 55:
        return "LinkedIn/FB post + YouTube Short"
    return "LinkedIn/FB post"


def _tutorial_angles(signal: TrendSignal, tutorial: int) -> list[str]:
    if tutorial < 45:
        return []
    base = signal.title.rstrip("?")
    return [
        f"Step-by-step guide: {base}",
        f"Build a minimal working example for {base}",
        f"Deploy {base} on a Raspberry Pi or VPS",
        f"Common pitfalls when working with {base}",
    ]


def _social_angles(signal: TrendSignal, social: int) -> list[str]:
    if social < 50:
        return []
    return [
        f"LinkedIn post: 'What I learned from {signal.title}'",
        f"YouTube Short: 60-second demo of {signal.title}",
    ]


class IntelligenceEngine:
    """Runs the 5-layer intelligence pipeline."""

    def __init__(
        self,
        config: IntelligenceConfig | None = None,
        audience_live: bool | None = None,
        audience_text: bool | None = None,
        audience_sources: list[str] | None = None,
        enable_content_gap: bool | None = None,
        sitemap_url: str | None = None,
        existing_content_file: str | None = None,
        enable_newsletter_mining: bool | None = None,
    ) -> None:
        self.config = config or IntelligenceConfig()
        if audience_live is not None:
            self.config.audience_live = audience_live
        if audience_text is not None:
            self.config.audience_text = audience_text
        if audience_sources is not None:
            self.config.audience_sources = audience_sources
        if enable_content_gap is not None:
            self.config.enable_content_gap = enable_content_gap
        if sitemap_url is not None:
            self.config.sitemap_url = sitemap_url
        if existing_content_file is not None:
            self.config.existing_content_file = existing_content_file
        if enable_newsletter_mining is not None:
            self.config.enable_newsletter_mining = enable_newsletter_mining
        self.kb = load_knowledge_base()

    def run(self) -> Path:
        """Execute the full pipeline and return the report path."""
        print("📚 Loading BuildWithAbdallah knowledge base")
        print(f"   expertise: {len(self.kb.expertise)} | projects: {len(self.kb.projects)} | stack: {len(self.kb.stack)} | rules: {len(self.kb.rules)}")

        existing_content: list = []
        if self.config.enable_content_gap:
            print("🔍 Layer 0: Content Gap Detection — scanning existing content")
            existing_content = load_existing_content(self.config)
            print(f"   {len(existing_content)} existing items loaded")

        print("🔭 Layer 1: Trend Radar")
        trend_signals = collect_trend_signals(self.config)
        # Newsletter / release mining for Layer 1b.
        newsletter_items: list = []
        if self.config.enable_newsletter_mining:
            print("📰 Layer 1b: Newsletter / Release Mining")
            newsletter_items = score_newsletter_items(
                collect_newsletter_items(), self.kb, existing_content=existing_content
            )
            print(f"   {len(newsletter_items)} newsletter items mined")
            trend_signals.extend(items_to_trend_signals(newsletter_items[:30]))
        print(f"   {len(trend_signals)} signals collected")

        print("🗣️  Layer 2: Audience Pain Radar")
        audience_pains = collect_audience_pain(
            self.config,
            live=self.config.audience_live,
            text_fallback=self.config.audience_text,
            sources=self.config.audience_sources,
        )
        print(f"   {len(audience_pains)} pain clusters found")

        print("🎓 Layer 3: Authority Filter + Knowledge Match")
        filtered = [s for s in trend_signals if passes_authority_filter(s, self.config.min_authority_score)]
        print(f"   {len(filtered)} signals passed authority filter")

        print("📈 Layer 4: Performance Intelligence")
        performance_insights = collect_performance_insights(self.config)
        print(f"   {len(performance_insights)} insights loaded")

        print("🎯 Layer 5: Opportunity Engine")
        opportunities = _signals_to_opportunities(
            trend_signals, audience_pains, performance_insights, existing_content, self.config, self.kb
        )
        top = opportunities[: self.config.top_n]
        print(f"   {len(top)} opportunities ranked")

        report_path = generate_report(
            top,
            trend_signals,
            audience_pains,
            performance_insights,
            existing_content,
            self.config.report_path,
            newsletter_items=newsletter_items if self.config.enable_newsletter_mining else None,
        )
        print(f"\n📝 Report written: {report_path}")
        return report_path


def run_intelligence(
    report_path: str | None = None,
    top_n: int = 10,
    dry_run: bool = False,
    min_authority_score: int = 50,
    audience_live: bool = False,
    audience_text: bool = True,
    audience_sources: list[str] | None = None,
    enable_content_gap: bool = True,
    sitemap_url: str | None = None,
    existing_content_file: str | None = None,
    enable_newsletter_mining: bool = False,
) -> Path:
    """Convenience entry point used by the CLI."""
    config = IntelligenceConfig(
        top_n=top_n,
        dry_run=dry_run,
        min_authority_score=min_authority_score,
    )
    if report_path:
        config.report_path = Path(report_path)
    engine = IntelligenceEngine(
        config,
        audience_live=audience_live,
        audience_text=audience_text,
        audience_sources=audience_sources,
        enable_content_gap=enable_content_gap,
        sitemap_url=sitemap_url,
        existing_content_file=existing_content_file,
        enable_newsletter_mining=enable_newsletter_mining,
    )
    return engine.run()
