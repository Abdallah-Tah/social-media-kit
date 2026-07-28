"""Phase 1 Stage 7A — deterministic artifact builders.

Three builders that consume existing decision, admission, saturation, quality,
readiness, and publication records and assemble structured artifacts.

Builders are pure functions:
  * no LLM calls
  * no network calls
  * no publishing calls
  * no notification calls
  * no live-history writes
  * same structured input → byte-identical semantic output
  * missing data displayed explicitly, never invented
  * confirmed and unverified claims always separated

Artifact output is stored only in content/feed/intelligence/ (git-ignored).

Artifact distinction:
  intelligence_brief        — daily, what was scanned/rejected/selected
  weekly_trend_analysis     — forward-looking, emerging themes
  weekly_intelligence_report — retrospective, decisions and performance
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .flags import editorial_timezone

KIT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = KIT / "content" / "feed" / "intelligence"

ARTIFACT_VERSION = 1


# ── Input dataclasses ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BriefSource:
    """One source scanned during the day."""
    name: str
    candidate_count: int = 0


@dataclass(frozen=True)
class BriefCandidate:
    """One candidate evaluated during the day."""
    candidate_id: str
    title: str
    entity: str = ""
    development_type: str = ""
    source_confidence: int | None = None
    opportunity_score: int | None = None
    saturation_status: str = ""
    admission_status: str = ""
    rejection_reasons: tuple[str, ...] = ()
    primary_source_url: str = ""
    corroborating_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class BriefClaim:
    """One claim from the selected candidate."""
    text: str
    verification: str = ""
    source_url: str = ""


@dataclass(frozen=True)
class SourceConfidenceBreakdown:
    """Five-component source confidence breakdown."""
    primary_source: int = 0
    corroboration: int = 0
    domain_authority: int = 0
    recency: int = 0
    claim_traceability: int = 0
    total: int = 0


@dataclass(frozen=True)
class QualityBreakdown:
    """Five-component editorial quality breakdown."""
    format_conformance: int = 0
    specificity_evidence: int = 0
    practical_value: int = 0
    structure_readability: int = 0
    language_originality: int = 0
    total: int = 0
    hard_failures: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DailyBriefInput:
    """Complete input for one day's intelligence brief."""
    editorial_day: str
    sources_scanned: tuple[BriefSource, ...] = ()
    candidates: tuple[BriefCandidate, ...] = ()
    selected_candidate: BriefCandidate | None = None
    confirmed_claims: tuple[BriefClaim, ...] = ()
    unverified_claims: tuple[BriefClaim, ...] = ()
    source_confidence: SourceConfidenceBreakdown | None = None
    quality: QualityBreakdown | None = None
    readiness_status: str = ""
    readiness_reason_codes: tuple[str, ...] = ()
    duplicates_prevented: int = 0
    slot_id: str = ""
    format_id: str = ""


@dataclass(frozen=True)
class WeeklyTrendInput:
    """Complete input for one week's trend analysis."""
    week_start: str
    week_end: str
    entity_counts: tuple[tuple[str, int], ...] = ()
    theme_counts: tuple[tuple[str, int], ...] = ()
    source_activity: tuple[tuple[str, int], ...] = ()
    development_type_counts: tuple[tuple[str, int], ...] = ()
    emerging_entities: tuple[str, ...] = ()
    emerging_themes: tuple[str, ...] = ()
    total_candidates_evaluated: int = 0
    total_admitted: int = 0
    total_rejected: int = 0
    coverage_gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class WeeklyReportInput:
    """Complete input for one week's retrospective intelligence report."""
    week_start: str
    week_end: str
    total_decisions: int = 0
    accepted: int = 0
    rejected: int = 0
    rejected_by_reason: tuple[tuple[str, int], ...] = ()
    readiness_decisions: tuple[tuple[str, int], ...] = ()
    avg_source_confidence: float | None = None
    avg_editorial_quality: float | None = None
    source_confidence_range: tuple[int, int] | None = None
    quality_range: tuple[int, int] | None = None
    duplicates_prevented: int = 0
    saturation_rejections: int = 0
    material_exceptions: int = 0
    slots_filled: int = 0
    slots_skipped: int = 0
    quality_hard_failures: tuple[tuple[str, int], ...] = ()
    top_sources: tuple[tuple[str, int], ...] = ()


# ── Artifact output ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Artifact:
    """A structured artifact ready for serialization."""
    artifact_type: str
    format_id: str
    editorial_day: str
    version: int = ARTIFACT_VERSION
    title: str = ""
    sections: tuple[tuple[str, str], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "format_id": self.format_id,
            "editorial_day": self.editorial_day,
            "version": self.version,
            "title": self.title,
            "sections": [{"heading": h, "body": b} for h, b in self.sections],
            "metadata": self.metadata,
        }

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", ""]
        for heading, body in self.sections:
            lines.append(heading)
            lines.append("")
            lines.append(body)
            lines.append("")
        return "\n".join(lines)


# ── Builders ─────────────────────────────────────────────────────────────────

def build_intelligence_brief(inp: DailyBriefInput) -> Artifact:
    """Assemble the daily intelligence brief from structured records.

    Every section is filled from input fields only. No claim may appear that
    is not traceable to an input field. Missing data is shown explicitly.
    """
    admitted = [c for c in inp.candidates if c.admission_status == "admitted"]
    rejected = [c for c in inp.candidates if c.admission_status != "admitted"]

    # ── What I Scanned ─────────────────────────────────────────────────────
    if inp.sources_scanned:
        scan_lines = []
        for src in sorted(inp.sources_scanned, key=lambda s: s.name):
            scan_lines.append(f"- {src.name}: {src.candidate_count} candidate(s)")
        scanned_body = "\n".join(scan_lines)
    else:
        scanned_body = "(no sources recorded)"

    # ── What Surfaced ──────────────────────────────────────────────────────
    if admitted:
        surfaced_lines = []
        for c in sorted(admitted, key=lambda c: c.candidate_id):
            line = f"- {c.title}"
            if c.entity:
                line += f" [{c.entity}]"
            if c.source_confidence is not None:
                line += f" — source confidence {c.source_confidence}"
            surfaced_lines.append(line)
        surfaced_body = "\n".join(surfaced_lines)
    else:
        surfaced_body = "(no candidates admitted)"

    # ── What I Rejected ────────────────────────────────────────────────────
    if rejected:
        rejected_lines = []
        for c in sorted(rejected, key=lambda c: c.candidate_id):
            line = f"- {c.title}"
            if c.entity:
                line += f" [{c.entity}]"
            if c.rejection_reasons:
                line += f" — {', '.join(c.rejection_reasons)}"
            elif c.admission_status:
                line += f" — status: {c.admission_status}"
            rejected_lines.append(line)
        rejected_body = "\n".join(rejected_lines)
    else:
        rejected_body = "(no candidates rejected)"

    # ── Duplicates Prevented ───────────────────────────────────────────────
    if inp.duplicates_prevented > 0:
        dup_body = f"{inp.duplicates_prevented} duplicate or saturated topic(s) blocked."
    else:
        dup_body = "No duplicates or saturation blocks recorded."

    # ── The Lead Story ─────────────────────────────────────────────────────
    if inp.selected_candidate:
        sel = inp.selected_candidate
        lead_lines = [f"**{sel.title}**"]
        if sel.entity:
            lead_lines.append(f"- Entity: {sel.entity}")
        if sel.development_type:
            lead_lines.append(f"- Development type: {sel.development_type}")
        if sel.primary_source_url:
            lead_lines.append(f"- Primary source: {sel.primary_source_url}")
        if sel.corroborating_domains:
            lead_lines.append(
                f"- Corroborating domains: {', '.join(sel.corroborating_domains)}"
            )
        lead_body = "\n".join(lead_lines)
    else:
        lead_body = "(no candidate selected — slot skipped)"

    # ── Why This One ───────────────────────────────────────────────────────
    if inp.selected_candidate and rejected:
        sel = inp.selected_candidate
        why_lines = [f"Selected over {len(rejected)} other candidate(s)."]
        if sel.source_confidence is not None:
            why_lines.append(f"Source confidence: {sel.source_confidence}.")
        if sel.opportunity_score is not None:
            why_lines.append(f"Opportunity score: {sel.opportunity_score}.")
        if inp.readiness_status:
            why_lines.append(f"Readiness: {inp.readiness_status}.")
        why_body = "\n".join(why_lines)
    elif inp.selected_candidate:
        why_body = "Only admitted candidate for this slot."
    else:
        why_body = "(no candidate selected)"

    # ── Confirmed Facts ────────────────────────────────────────────────────
    if inp.confirmed_claims:
        confirmed_lines = []
        for cl in inp.confirmed_claims:
            line = f"- {cl.text}"
            if cl.source_url:
                line += f" (source: {cl.source_url})"
            confirmed_lines.append(line)
        confirmed_body = "\n".join(confirmed_lines)
    else:
        confirmed_body = "(no confirmed claims recorded)"

    # ── Unverified Or Vendor Claims ────────────────────────────────────────
    if inp.unverified_claims:
        unverified_lines = []
        for cl in inp.unverified_claims:
            line = f"- {cl.text}"
            if cl.verification:
                line += f" [{cl.verification}]"
            if cl.source_url:
                line += f" (source: {cl.source_url})"
            unverified_lines.append(line)
        unverified_body = "\n".join(unverified_lines)
    else:
        unverified_body = "(no unverified or vendor claims recorded)"

    # ── Source Confidence ──────────────────────────────────────────────────
    if inp.source_confidence:
        sc = inp.source_confidence
        sc_body = (
            f"| Component | Score |\n"
            f"|---|---|\n"
            f"| Primary source | {sc.primary_source} |\n"
            f"| Corroboration | {sc.corroboration} |\n"
            f"| Domain authority | {sc.domain_authority} |\n"
            f"| Recency | {sc.recency} |\n"
            f"| Claim traceability | {sc.claim_traceability} |\n"
            f"| **Total** | **{sc.total}** |"
        )
    else:
        sc_body = "(source confidence not computed)"

    # ── Primary Sources ────────────────────────────────────────────────────
    primary_urls = []
    if inp.selected_candidate and inp.selected_candidate.primary_source_url:
        primary_urls.append(inp.selected_candidate.primary_source_url)
    for c in inp.candidates:
        if c.primary_source_url and c.primary_source_url not in primary_urls:
            primary_urls.append(c.primary_source_url)
    if primary_urls:
        ps_body = "\n".join(f"- {url}" for url in primary_urls)
    else:
        ps_body = "(no primary source URLs recorded)"

    # ── Title ──────────────────────────────────────────────────────────────
    if inp.selected_candidate:
        title = f"Intelligence Brief — {inp.selected_candidate.title} ({inp.editorial_day})"
    else:
        title = f"Intelligence Brief — {inp.editorial_day} (no selection)"

    sections = (
        ("## What I Scanned", scanned_body),
        ("## What Surfaced", surfaced_body),
        ("## What I Rejected", rejected_body),
        ("## Duplicates Prevented", dup_body),
        ("## The Lead Story", lead_body),
        ("## Why This One", why_body),
        ("## Confirmed Facts", confirmed_body),
        ("## Unverified Or Vendor Claims", unverified_body),
        ("## Source Confidence", sc_body),
        ("## Primary Sources", ps_body),
    )

    return Artifact(
        artifact_type="intelligence_brief",
        format_id=inp.format_id or "intelligence_brief",
        editorial_day=inp.editorial_day,
        title=title,
        sections=sections,
        metadata={
            "slot_id": inp.slot_id,
            "readiness_status": inp.readiness_status,
            "readiness_reason_codes": list(inp.readiness_reason_codes),
            "candidates_evaluated": len(inp.candidates),
            "candidates_admitted": len(admitted),
            "candidates_rejected": len(rejected),
            "duplicates_prevented": inp.duplicates_prevented,
            "confirmed_claim_count": len(inp.confirmed_claims),
            "unverified_claim_count": len(inp.unverified_claims),
        },
    )


def build_weekly_trend_analysis(inp: WeeklyTrendInput) -> Artifact:
    """Assemble the weekly forward-looking trend analysis.

    Uses entity frequency, theme patterns, source activity, and emerging
    topics. Forward-looking: what may matter next week.
    """
    # ── Week Overview ──────────────────────────────────────────────────────
    overview_body = (
        f"Week: {inp.week_start} to {inp.week_end}\n"
        f"Candidates evaluated: {inp.total_candidates_evaluated}\n"
        f"Admitted: {inp.total_admitted}\n"
        f"Rejected: {inp.total_rejected}"
    )

    # ── Entity Activity ────────────────────────────────────────────────────
    if inp.entity_counts:
        entity_lines = []
        for entity, count in sorted(inp.entity_counts, key=lambda x: (-x[1], x[0])):
            entity_lines.append(f"- {entity}: {count} appearance(s)")
        entity_body = "\n".join(entity_lines)
    else:
        entity_body = "(no entity data recorded)"

    # ── Theme Distribution ─────────────────────────────────────────────────
    if inp.theme_counts:
        theme_lines = []
        for theme, count in sorted(inp.theme_counts, key=lambda x: (-x[1], x[0])):
            theme_lines.append(f"- {theme}: {count} occurrence(s)")
        theme_body = "\n".join(theme_lines)
    else:
        theme_body = "(no theme data recorded)"

    # ── Development Types ──────────────────────────────────────────────────
    if inp.development_type_counts:
        dt_lines = []
        for dt_name, count in sorted(
            inp.development_type_counts, key=lambda x: (-x[1], x[0])
        ):
            dt_lines.append(f"- {dt_name}: {count}")
        dt_body = "\n".join(dt_lines)
    else:
        dt_body = "(no development type data recorded)"

    # ── Source Activity ────────────────────────────────────────────────────
    if inp.source_activity:
        src_lines = []
        for src, count in sorted(inp.source_activity, key=lambda x: (-x[1], x[0])):
            src_lines.append(f"- {src}: {count} item(s)")
        src_body = "\n".join(src_lines)
    else:
        src_body = "(no source activity data recorded)"

    # ── Emerging Themes ────────────────────────────────────────────────────
    if inp.emerging_themes:
        emerging_body = "\n".join(f"- {t}" for t in sorted(inp.emerging_themes))
    else:
        emerging_body = "(no emerging themes identified)"

    # ── What May Matter Next Week ──────────────────────────────────────────
    if inp.emerging_entities:
        forward_lines = []
        for entity in sorted(inp.emerging_entities):
            forward_lines.append(f"- {entity}")
        forward_body = "\n".join(forward_lines)
    else:
        forward_body = "(no forward-looking signals recorded)"

    # ── Coverage Gaps ──────────────────────────────────────────────────────
    if inp.coverage_gaps:
        gap_body = "\n".join(f"- {g}" for g in sorted(inp.coverage_gaps))
    else:
        gap_body = "(no coverage gaps identified)"

    title = f"Weekly Trend Analysis — {inp.week_start} to {inp.week_end}"

    sections = (
        ("## Week Overview", overview_body),
        ("## Entity Activity", entity_body),
        ("## Theme Distribution", theme_body),
        ("## Development Types", dt_body),
        ("## Source Activity", src_body),
        ("## Emerging Themes", emerging_body),
        ("## What May Matter Next Week", forward_body),
        ("## Coverage Gaps", gap_body),
    )

    return Artifact(
        artifact_type="weekly_trend_analysis",
        format_id="weekly_trend_analysis",
        editorial_day=inp.week_end,
        title=title,
        sections=sections,
        metadata={
            "week_start": inp.week_start,
            "week_end": inp.week_end,
            "total_candidates_evaluated": inp.total_candidates_evaluated,
            "total_admitted": inp.total_admitted,
            "total_rejected": inp.total_rejected,
            "entity_count": len(inp.entity_counts),
            "theme_count": len(inp.theme_counts),
            "emerging_entity_count": len(inp.emerging_entities),
            "emerging_theme_count": len(inp.emerging_themes),
        },
    )


def build_weekly_intelligence_report(inp: WeeklyReportInput) -> Artifact:
    """Assemble the weekly retrospective intelligence report.

    Uses decision records, quality outcomes, and publishing performance.
    Retrospective: what happened, what was accepted/rejected, lessons.
    """
    # ── Week Overview ──────────────────────────────────────────────────────
    overview_body = (
        f"Week: {inp.week_start} to {inp.week_end}\n"
        f"Total decisions: {inp.total_decisions}\n"
        f"Accepted: {inp.accepted}\n"
        f"Rejected: {inp.rejected}\n"
        f"Slots filled: {inp.slots_filled}\n"
        f"Slots skipped: {inp.slots_skipped}"
    )

    # ── Rejection Breakdown ────────────────────────────────────────────────
    if inp.rejected_by_reason:
        rej_lines = []
        for reason, count in sorted(
            inp.rejected_by_reason, key=lambda x: (-x[1], x[0])
        ):
            rej_lines.append(f"- {reason}: {count}")
        rej_body = "\n".join(rej_lines)
    else:
        rej_body = "(no rejections recorded)"

    # ── Readiness Outcomes ─────────────────────────────────────────────────
    if inp.readiness_decisions:
        rd_lines = []
        for status, count in sorted(
            inp.readiness_decisions, key=lambda x: (-x[1], x[0])
        ):
            rd_lines.append(f"- {status}: {count}")
        rd_body = "\n".join(rd_lines)
    else:
        rd_body = "(no readiness decisions recorded)"

    # ── Source Confidence Distribution ──────────────────────────────────────
    if inp.avg_source_confidence is not None:
        sc_parts = [f"Average: {inp.avg_source_confidence:.1f}"]
        if inp.source_confidence_range:
            sc_parts.append(
                f"Range: {inp.source_confidence_range[0]}–{inp.source_confidence_range[1]}"
            )
        sc_body = " | ".join(sc_parts)
    else:
        sc_body = "(no source confidence data recorded)"

    # ── Editorial Quality Distribution ──────────────────────────────────────
    if inp.avg_editorial_quality is not None:
        eq_parts = [f"Average: {inp.avg_editorial_quality:.1f}"]
        if inp.quality_range:
            eq_parts.append(
                f"Range: {inp.quality_range[0]}–{inp.quality_range[1]}"
            )
        eq_body = " | ".join(eq_parts)
    else:
        eq_body = "(no editorial quality data recorded)"

    # ── Quality Hard Failures ──────────────────────────────────────────────
    if inp.quality_hard_failures:
        hf_lines = []
        for code, count in sorted(
            inp.quality_hard_failures, key=lambda x: (-x[1], x[0])
        ):
            hf_lines.append(f"- {code}: {count}")
        hf_body = "\n".join(hf_lines)
    else:
        hf_body = "(no hard failures recorded)"

    # ── Saturation And Duplicates ──────────────────────────────────────────
    sat_parts = []
    sat_parts.append(f"Duplicates prevented: {inp.duplicates_prevented}")
    sat_parts.append(f"Saturation rejections: {inp.saturation_rejections}")
    sat_parts.append(f"Material exceptions: {inp.material_exceptions}")
    sat_body = "\n".join(f"- {p}" for p in sat_parts)

    # ── Top Sources ────────────────────────────────────────────────────────
    if inp.top_sources:
        ts_lines = []
        for src, count in sorted(inp.top_sources, key=lambda x: (-x[1], x[0])):
            ts_lines.append(f"- {src}: {count} item(s)")
        ts_body = "\n".join(ts_lines)
    else:
        ts_body = "(no source data recorded)"

    # ── Lessons For Next Week ──────────────────────────────────────────────
    lessons_lines = []
    if inp.duplicates_prevented > 0:
        lessons_lines.append(
            f"- {inp.duplicates_prevented} duplicate(s) caught by saturation checks."
        )
    if inp.saturation_rejections > 0:
        lessons_lines.append(
            f"- {inp.saturation_rejections} rejection(s) from saturation rules."
        )
    if inp.slots_skipped > 0:
        lessons_lines.append(
            f"- {inp.slots_skipped} slot(s) skipped — no passing candidate."
        )
    if inp.quality_hard_failures:
        total_hf = sum(c for _, c in inp.quality_hard_failures)
        lessons_lines.append(
            f"- {total_hf} quality hard failure(s) — review generation prompts."
        )
    if not lessons_lines:
        lessons_body = "(no notable patterns this week)"
    else:
        lessons_body = "\n".join(lessons_lines)

    title = f"Weekly Intelligence Report — {inp.week_start} to {inp.week_end}"

    sections = (
        ("## Week Overview", overview_body),
        ("## Rejection Breakdown", rej_body),
        ("## Readiness Outcomes", rd_body),
        ("## Source Confidence Distribution", sc_body),
        ("## Editorial Quality Distribution", eq_body),
        ("## Quality Hard Failures", hf_body),
        ("## Saturation And Duplicates", sat_body),
        ("## Top Sources", ts_body),
        ("## Lessons For Next Week", lessons_body),
    )

    return Artifact(
        artifact_type="weekly_intelligence_report",
        format_id="weekly_intelligence_report",
        editorial_day=inp.week_end,
        title=title,
        sections=sections,
        metadata={
            "week_start": inp.week_start,
            "week_end": inp.week_end,
            "total_decisions": inp.total_decisions,
            "accepted": inp.accepted,
            "rejected": inp.rejected,
            "duplicates_prevented": inp.duplicates_prevented,
            "saturation_rejections": inp.saturation_rejections,
            "material_exceptions": inp.material_exceptions,
            "slots_filled": inp.slots_filled,
            "slots_skipped": inp.slots_skipped,
        },
    )


# ── Distinctness guard ───────────────────────────────────────────────────────

class ArtifactOverlapError(ValueError):
    """The weekly trend and weekly report are materially too similar."""


def validate_artifact_distinctness(
    trend: Artifact, report: Artifact, threshold: float = 0.6
) -> None:
    """Verify the two Sunday artifacts are materially distinct.

    Compares section headings. If the Jaccard similarity of heading sets
    exceeds the threshold, the artifacts overlap too much and must not be
    published.
    """
    trend_headings = {h for h, _ in trend.sections}
    report_headings = {h for h, _ in report.sections}
    if not trend_headings or not report_headings:
        return
    intersection = trend_headings & report_headings
    union = trend_headings | report_headings
    similarity = len(intersection) / len(union) if union else 0.0
    if similarity > threshold:
        raise ArtifactOverlapError(
            f"weekly_trend_analysis and weekly_intelligence_report share "
            f"{len(intersection)}/{len(union)} section headings "
            f"(Jaccard={similarity:.2f} > {threshold}). "
            f"Shared: {sorted(intersection)}"
        )


# ── Persistence ──────────────────────────────────────────────────────────────

def save_artifact(artifact: Artifact) -> Path:
    """Write an artifact to the git-ignored intelligence directory.

    Returns the output path. Never writes to any tracked location.
    """
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{artifact.artifact_type}_{artifact.editorial_day}.json"
    path = ARTIFACT_DIR / filename
    path.write_text(
        json.dumps(artifact.to_dict(), indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
