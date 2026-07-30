"""Phase 1 Stage 7B — dormant end-to-end editorial orchestrator.

Connects all pipeline stages (1–6 + 7A artifacts) into a single run that
evaluates every slot for a given date and persists the full decision trace.

Modes:
  shadow  — full pipeline, no publishing, no live history writes
  replay  — same as shadow but for a past date (re-evaluation of decisions)

Live mode is explicitly rejected. The orchestrator never:
  * publishes to the blog
  * publishes to social platforms
  * delivers newsletters
  * sends Telegram notifications
  * writes to live publication history
  * writes to live saturation history
  * mutates live format rotation

Persistence is only to git-ignored state paths:
  state/editorial/shadow/
  state/editorial/replay/

Pipeline sequence per slot:
  1. Slot policy resolution
  2. Ranked candidate loading
  3. Candidate normalization
  4. Source-relationship detection
  5. Source-confidence scoring
  6. Saturation evaluation
  7. Admission and backup selection
  8. Editorial format selection
  9. Draft generation
  10. Editorial-quality scoring
  11. Publication-readiness evaluation
  12. Deterministic artifact generation
  13. Shadow/replay persistence
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

KIT = Path(__file__).resolve().parents[2]
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from .flags import editorial_timezone

# ── Mode constants ───────────────────────────────────────────────────────────

MODE_SHADOW = "shadow"
MODE_REPLAY = "replay"
ALLOWED_MODES = frozenset({MODE_SHADOW, MODE_REPLAY})

# ── Outcome constants ────────────────────────────────────────────────────────

OUTCOME_READY_IN_SHADOW = "ready_in_shadow"
OUTCOME_READY_WITH_WARNINGS_HOLD = "ready_with_warnings_hold"
OUTCOME_REQUIRES_MANUAL_REVIEW = "requires_manual_review"
OUTCOME_QUALITY_REJECTED = "quality_rejected"
OUTCOME_SKIPPED_NO_CANDIDATE = "skipped_no_candidate"
OUTCOME_DRAFT_GENERATION_FAILED = "draft_generation_failed"
OUTCOME_INVALID_CONFIGURATION = "invalid_configuration"
OUTCOME_PIPELINE_FAILED = "pipeline_failed"

# ── Persistence paths ────────────────────────────────────────────────────────

STATE_DIR = KIT / "state" / "editorial"


def _mode_dir(mode: str) -> Path:
    return STATE_DIR / mode


# ── Input / output dataclasses ───────────────────────────────────────────────

@dataclass(frozen=True)
class PipelineInput:
    """Complete input for one orchestrator run."""
    mode: str
    date: str  # YYYY-MM-DD
    candidates: tuple[Any, ...] = ()
    history_rows: tuple[dict[str, Any], ...] = ()
    draft_builder: Callable[..., dict[str, Any]] | None = None
    now: dt.datetime | None = None


@dataclass(frozen=True)
class SlotResult:
    """The full decision trace for one slot."""
    slot_id: str
    content_type: str
    editorial_day: str
    outcome: str
    candidate_id: str = ""
    format_id: str = ""
    artifact_type: str = ""
    source_confidence: int | None = None
    editorial_quality: int | None = None
    readiness_status: str = ""
    reason_codes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    draft_title: str = ""
    draft_body: str = ""
    artifact: dict[str, Any] | None = None
    error: str = ""
    evaluations: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class PipelineResult:
    """The full result of one orchestrator run."""
    mode: str
    date: str
    editorial_day: str
    slot_results: tuple[SlotResult, ...]
    started_at: str = ""
    completed_at: str = ""
    config_errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "date": self.date,
            "editorial_day": self.editorial_day,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "config_errors": list(self.config_errors),
            "slot_results": [_slot_to_dict(sr) for sr in self.slot_results],
        }


def _slot_to_dict(sr: SlotResult) -> dict[str, Any]:
    return {
        "slot_id": sr.slot_id,
        "content_type": sr.content_type,
        "editorial_day": sr.editorial_day,
        "outcome": sr.outcome,
        "candidate_id": sr.candidate_id,
        "format_id": sr.format_id,
        "artifact_type": sr.artifact_type,
        "source_confidence": sr.source_confidence,
        "editorial_quality": sr.editorial_quality,
        "readiness_status": sr.readiness_status,
        "reason_codes": list(sr.reason_codes),
        "warnings": list(sr.warnings),
        "draft_title": sr.draft_title,
        "error": sr.error,
        "evaluations": list(sr.evaluations),
    }


# ── Default draft builder ────────────────────────────────────────────────────

def _default_draft_builder(
    candidate: Any,
    format_id: str,
    slot_objective: str,
    source_confidence: Any,
    quality_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic draft builder for shadow/replay.

    Produces a structured draft from the candidate and format metadata.
    No LLM call. Production shadow runs may override this with an LLM-backed
    builder via PipelineInput.draft_builder.
    """
    title = getattr(candidate, "title", "") or ""
    entity = getattr(candidate, "subject_org", "") or getattr(candidate, "subject_name", "") or ""
    dev_type = getattr(candidate, "development_type", "") or ""
    body_parts = [
        f"# {title}",
        "",
        f"Entity: {entity}" if entity else "Entity: (unknown)",
        f"Development type: {dev_type}" if dev_type else "",
        "",
        "## What Happened",
        "",
        f"Candidate {getattr(candidate, 'candidate_id', '')} was evaluated for format {format_id}.",
        "",
        "## Confirmed Facts",
        "",
    ]
    claims = getattr(candidate, "claims", ()) or ()
    for claim in claims:
        text = getattr(claim, "text", "") or str(claim)
        verification = getattr(claim, "verification", "")
        if verification in ("verified_independent", "verified_unknown"):
            body_parts.append(f"- {text}")
    body_parts.extend(["", "## Unverified Claims", ""])
    for claim in claims:
        text = getattr(claim, "text", "") or str(claim)
        verification = getattr(claim, "verification", "")
        if verification not in ("verified_independent", "verified_unknown"):
            label = f" [{verification}]" if verification else ""
            body_parts.append(f"- {text}{label}")

    body = "\n".join(p for p in body_parts if p is not None)
    summary = f"Shadow draft for {title}" if title else "Shadow draft"

    sources = []
    for src in (getattr(candidate, "sources", ()) or ()):
        url = getattr(src, "url", "") or ""
        if url:
            sources.append({"url": url, "kind": getattr(src, "kind", "secondary")})

    claim_dicts = []
    for claim in claims:
        claim_dicts.append({
            "text": getattr(claim, "text", "") or str(claim),
            "verification": getattr(claim, "verification", "unverified"),
            "source_url": getattr(claim, "source_url", ""),
        })

    return {
        "title": title,
        "body": body,
        "summary": summary,
        "format_id": format_id,
        "artifact_type": format_id,
        "slot_objective": slot_objective,
        "sources": tuple(sources),
        "claims": tuple(claim_dicts),
        "confirmed_facts": tuple(
            {"text": c["text"], "source_url": c["source_url"]}
            for c in claim_dicts
            if c["verification"] in ("verified_independent", "verified_unknown")
        ),
        "generation_mode": "deterministic_scaffold",
    }


# ── Artifact routing ─────────────────────────────────────────────────────────

def _generate_artifact(
    content_type: Any,
    slot_id: str,
    editorial_day: str,
    normalized: Sequence[Any],
    selected: Any,
    selected_id: str,
    sc_results: dict[str, Any],
    sc_result: Any,
    quality_result: Any,
    rd_status: str,
    rd_codes: tuple[str, ...],
    candidates: Sequence[Any],
    admission_result: Any,
    format_id: str,
) -> dict[str, Any] | None:
    """Route to the correct 7A artifact builder based on content type.

    - intelligence_brief slot → build_intelligence_brief()
    - Sunday weekly_trend_analysis → build_weekly_trend_analysis()
    - Sunday weekly_intelligence_report → build_weekly_intelligence_report()
    - Other slots → None (no system artifact)
    """
    from .artifacts import (
        BriefCandidate,
        BriefClaim,
        BriefSource,
        DailyBriefInput,
        QualityBreakdown,
        SourceConfidenceBreakdown,
        WeeklyReportInput,
        WeeklyTrendInput,
        build_intelligence_brief,
        build_weekly_intelligence_report,
        build_weekly_trend_analysis,
    )

    ct_name = content_type.name if hasattr(content_type, "name") else str(content_type)
    artifact_name = content_type.artifact if hasattr(content_type, "artifact") and content_type.artifact else None

    # ── Sunday weekly artifacts ────────────────────────────────────────────
    if artifact_name == "weekly_trend_analysis":
        trend_input = WeeklyTrendInput(
            week_start=editorial_day,
            week_end=editorial_day,
            entity_counts=tuple(
                (c.subject_org or c.subject_name or "unknown", 1)
                for c in normalized
            ),
            theme_counts=(),
            source_activity=tuple(
                (c.source or "unknown", 1) for c in normalized
            ),
            development_type_counts=tuple(
                (c.development_type, 1) for c in normalized
            ),
            total_candidates_evaluated=len(candidates),
            total_admitted=1 if selected_id else 0,
            total_rejected=len(candidates) - (1 if selected_id else 0),
        )
        return build_weekly_trend_analysis(trend_input).to_dict()

    if artifact_name == "weekly_intelligence_report":
        report_input = WeeklyReportInput(
            week_start=editorial_day,
            week_end=editorial_day,
            total_decisions=len(candidates),
            accepted=1 if selected_id else 0,
            rejected=len(candidates) - (1 if selected_id else 0),
            rejected_by_reason=(),
            readiness_decisions=((rd_status, 1),) if rd_status else (),
            avg_source_confidence=float(sc_result.score) if sc_result else None,
            avg_editorial_quality=float(quality_result.score) if quality_result else None,
            slots_filled=1 if selected_id else 0,
            slots_skipped=0 if selected_id else 1,
        )
        return build_weekly_intelligence_report(report_input).to_dict()

    # ── Morning intelligence_brief slot ────────────────────────────────────
    if ct_name == "intelligence_brief" or artifact_name == "intelligence_brief":
        brief_sources = (
            BriefSource(name="feed", candidate_count=len(candidates)),
        )
        brief_candidates = []
        for c in normalized:
            ev = None
            for e in (admission_result.evaluated_candidates
                      if hasattr(admission_result, "evaluated_candidates") else ()):
                if getattr(e, "candidate_id", "") == c.candidate_id:
                    ev = e
                    break
            brief_candidates.append(BriefCandidate(
                candidate_id=c.candidate_id,
                title=c.title,
                entity=c.subject_org or c.subject_name or "",
                development_type=c.development_type,
                source_confidence=sc_results[c.candidate_id].score
                    if c.candidate_id in sc_results else None,
                admission_status="admitted" if c.candidate_id == selected_id else "rejected",
                rejection_reasons=tuple(
                    getattr(ev, "reason_codes", ()) or ()
                ) if ev and c.candidate_id != selected_id else (),
                primary_source_url=(c.primary_source.url if c.primary_source else "")
                    if hasattr(c, "primary_source") and c.primary_source else "",
            ))

        sel_brief = None
        for bc in brief_candidates:
            if bc.candidate_id == selected_id:
                sel_brief = bc
                break

        confirmed = []
        unverified = []
        if selected is not None:
            for claim in (selected.claims or ()):
                bc = BriefClaim(
                    text=claim.text,
                    verification=getattr(claim, "verification", "unverified"),
                    source_url=getattr(claim, "source_url", ""),
                )
                if getattr(claim, "verification", "") in ("verified_independent", "verified_unknown"):
                    confirmed.append(bc)
                else:
                    unverified.append(bc)

        sc_breakdown = None
        if sc_result:
            comps = sc_result.components
            sc_breakdown = SourceConfidenceBreakdown(
                primary_source=getattr(comps.get("primary_source"), "score", 0) if comps.get("primary_source") else 0,
                corroboration=getattr(comps.get("corroboration"), "score", 0) if comps.get("corroboration") else 0,
                domain_authority=getattr(comps.get("domain_authority"), "score", 0) if comps.get("domain_authority") else 0,
                recency=getattr(comps.get("recency"), "score", 0) if comps.get("recency") else 0,
                claim_traceability=getattr(comps.get("claim_traceability"), "score", 0) if comps.get("claim_traceability") else 0,
                total=sc_result.score,
            )

        q_breakdown = None
        if quality_result:
            qcomps = {c.name: c for c in quality_result.components}
            q_breakdown = QualityBreakdown(
                format_conformance=getattr(qcomps.get("format_conformance"), "score", 0),
                specificity_evidence=getattr(qcomps.get("specificity_evidence"), "score", 0),
                practical_value=getattr(qcomps.get("practical_value"), "score", 0),
                structure_readability=getattr(qcomps.get("structure_readability"), "score", 0),
                language_originality=getattr(qcomps.get("language_originality"), "score", 0),
                total=quality_result.score,
                hard_failures=tuple(quality_result.hard_failures or ()),
                issues=tuple(quality_result.issues or ()),
                warnings=tuple(quality_result.warnings or ()),
            )

        brief_input = DailyBriefInput(
            editorial_day=editorial_day,
            sources_scanned=brief_sources,
            candidates=tuple(brief_candidates),
            selected_candidate=sel_brief,
            confirmed_claims=tuple(confirmed),
            unverified_claims=tuple(unverified),
            source_confidence=sc_breakdown,
            quality=q_breakdown,
            readiness_status=rd_status,
            readiness_reason_codes=tuple(rd_codes),
            slot_id=slot_id,
            format_id=format_id,
        )
        return build_intelligence_brief(brief_input).to_dict()

    # ── Other slots: no system artifact ────────────────────────────────────
    return None


# ── Pipeline execution ───────────────────────────────────────────────────────

def _editorial_day_for(date_str: str, tz_name: str) -> str:
    """Return the weekday name for a date string."""
    d = dt.date.fromisoformat(date_str)
    days = ("monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday")
    return days[d.weekday()]


def _run_slot(
    slot: Any,
    content_type: Any,
    candidates: Sequence[Any],
    history_rows: Sequence[dict[str, Any]],
    date_str: str,
    draft_builder: Callable[..., dict[str, Any]],
    now: dt.datetime,
) -> SlotResult:
    """Run the full pipeline for one slot. Returns a SlotResult."""
    from . import (
        admission as ADM,
        quality as QUA,
        readiness as RDY,
        saturation as SAT,
        source_confidence as SC,
    )
    from .candidate_adapter import normalize_candidate
    from .slots import SlotConfig, load_slots

    editorial_day = _editorial_day_for(date_str, editorial_timezone())
    slot_id = slot.slot_id
    ct_name = content_type.name

    evaluations: list[dict[str, Any]] = []

    # ── Artifact slots: generate directly, skip candidate pipeline ─────────
    if content_type.is_artifact:
        artifact_dict = None
        try:
            artifact_dict = _generate_artifact(
                content_type, slot_id, editorial_day, (),
                None, "", {}, None,
                None, "", (), candidates,
                None, content_type.artifact,
            )
        except Exception:
            pass
        return SlotResult(
            slot_id=slot_id,
            content_type=ct_name,
            editorial_day=editorial_day,
            outcome=OUTCOME_READY_IN_SHADOW,
            format_id=content_type.artifact,
            artifact_type=content_type.artifact,
            readiness_status="artifact",
            artifact=artifact_dict,
        )

    # ── Load slot config for saturation/admission ──────────────────────────
    try:
        slot_config = load_slots()
    except Exception as exc:
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_INVALID_CONFIGURATION,
            error=str(exc),
        )

    # ── Build history view ─────────────────────────────────────────────────
    try:
        sat_config = SAT.load_saturation_config()
        history = SAT.build_history(history_rows, sat_config)
    except Exception as exc:
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_PIPELINE_FAILED,
            error=f"history build failed: {exc}",
        )

    # ── Normalize candidates ───────────────────────────────────────────────
    normalized: list[Any] = []
    for record in candidates:
        try:
            c = normalize_candidate(record)
            normalized.append(c)
        except Exception as exc:
            evaluations.append({
                "stage": "normalization",
                "candidate_id": getattr(record, "candidate_id", str(record)),
                "status": "failed",
                "error": str(exc),
            })

    if not normalized:
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_SKIPPED_NO_CANDIDATE,
            evaluations=tuple(evaluations),
        )

    # ── Score source confidence for each candidate ─────────────────────────
    sc_results: dict[str, Any] = {}
    for c in normalized:
        try:
            sc_result = SC.score_source_confidence(c, now=now)
            sc_results[c.candidate_id] = sc_result
            # Persist full source-confidence breakdown for observability
            evaluations.append({
                "stage": "source_confidence",
                "candidate_id": c.candidate_id,
                "status": "scored",
                "total_score": sc_result.score,
                "components": sc_result.to_dict()["components"],
                "warnings": list(sc_result.warnings),
            })
        except Exception as exc:
            evaluations.append({
                "stage": "source_confidence",
                "candidate_id": c.candidate_id,
                "status": "failed",
                "error": str(exc),
            })

    # ── Admission ──────────────────────────────────────────────────────────
    try:
        sat_config = SAT.load_saturation_config()
        admission_result = ADM.admit_to_slot(
            slot, normalized,
            history=history,
            saturation_config=sat_config,
            slot_config=slot_config,
            now=now,
            sc_results=sc_results,
        )
    except Exception as exc:
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_PIPELINE_FAILED,
            error=f"admission failed: {exc}",
            evaluations=tuple(evaluations),
        )

    # Record admission evaluations
    for ev in (admission_result.evaluated_candidates
               if hasattr(admission_result, "evaluated_candidates") else ()):
        evaluations.append({
            "stage": "admission",
            "candidate_id": getattr(ev, "candidate_id", ""),
            "status": getattr(ev, "status", ""),
            "rejection_reasons": list(getattr(ev, "reason_codes", ()) or ()),
            "opportunity_score": getattr(ev, "opportunity_score", None),
            "source_confidence": getattr(ev, "source_confidence", None),
        })

    selected_id = admission_result.selected_candidate_id or ""
    if not selected_id or admission_result.status != "admitted":
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_SKIPPED_NO_CANDIDATE,
            evaluations=tuple(evaluations),
            warnings=tuple(admission_result.warnings or ()),
        )

    # Find the selected candidate
    selected = None
    for c in normalized:
        if c.candidate_id == selected_id:
            selected = c
            break
    if selected is None:
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_PIPELINE_FAILED,
            error=f"selected candidate {selected_id} not found in normalized set",
            evaluations=tuple(evaluations),
        )

    sc_result = sc_results.get(selected_id)
    sc_score = sc_result.score if sc_result else None

    # ── Format selection ───────────────────────────────────────────────────
    try:
        if content_type.is_artifact:
            format_id = content_type.artifact
        elif content_type.formats:
            # Pick from the slot's content type format pool, not the global
            # editorial registry. Use the first format deterministically.
            format_id = content_type.formats[0]
        else:
            import content_formats as CF
            format_id = CF.pick_format("editorial")
    except Exception as exc:
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_PIPELINE_FAILED,
            candidate_id=selected_id,
            source_confidence=sc_score,
            error=f"format selection failed: {exc}",
            evaluations=tuple(evaluations),
        )

    # ── Draft generation ───────────────────────────────────────────────────
    slot_objective = getattr(slot, "purpose", "") or slot.label
    try:
        draft_data = draft_builder(
            selected, format_id, slot_objective, sc_result,
        )
    except Exception as exc:
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_DRAFT_GENERATION_FAILED,
            candidate_id=selected_id,
            format_id=format_id,
            source_confidence=sc_score,
            error=f"draft generation failed: {exc}",
            evaluations=tuple(evaluations),
        )

    draft_title = draft_data.get("title", "")
    draft_body = draft_data.get("body", "")

    # ── Quality scoring ────────────────────────────────────────────────────
    try:
        draft_input = QUA.DraftInput(
            title=draft_title,
            body=draft_body,
            summary=draft_data.get("summary", ""),
            artifact_type=draft_data.get("artifact_type", format_id),
            format_id=format_id,
            slot_objective=slot_objective,
            sources=tuple(draft_data.get("sources", ())),
            claims=tuple(draft_data.get("claims", ())),
            confirmed_facts=tuple(draft_data.get("confirmed_facts", ())),
        )
        quality_result = QUA.evaluate_quality(draft_input)
    except Exception as exc:
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_PIPELINE_FAILED,
            candidate_id=selected_id,
            format_id=format_id,
            source_confidence=sc_score,
            draft_title=draft_title,
            draft_body=draft_body,
            error=f"quality scoring failed: {exc}",
            evaluations=tuple(evaluations),
        )

    eq_score = quality_result.score

    if quality_result.status == "fail":
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_QUALITY_REJECTED,
            candidate_id=selected_id,
            format_id=format_id,
            artifact_type=format_id,
            source_confidence=sc_score,
            editorial_quality=eq_score,
            draft_title=draft_title,
            draft_body=draft_body,
            reason_codes=tuple(
                i.code for i in (quality_result.issue_details or ())
            ),
            warnings=tuple(quality_result.warnings or ()),
            evaluations=tuple(evaluations),
        )

    # ── Readiness evaluation ───────────────────────────────────────────────
    try:
        slot_policy = {
            "slot_id": slot_id,
            "source_confidence_min": slot.source_confidence_min(),
            "source_confidence_threshold": slot.source_confidence_min(),
            "editorial_quality_min": slot.editorial_quality_min(),
        }
        readiness_input = RDY.ReadinessInput(
            slot_policy_snapshot=slot_policy,
            candidate=selected,
            source_confidence_result=sc_result,
            saturation_result=None,
            admission_result=admission_result,
            draft=draft_input,
            quality_result=quality_result,
            artifact_type=format_id,
            format_id=format_id,
            editorial_day=editorial_day,
            generation_metadata={
                "admitted_artifact_type": format_id,
                "admitted_format_id": format_id,
                "generated_at": now.isoformat(),
            },
        )
        readiness_decision = RDY.evaluate_readiness(readiness_input, now=now)
    except Exception as exc:
        return SlotResult(
            slot_id=slot_id, content_type=ct_name, editorial_day=editorial_day,
            outcome=OUTCOME_PIPELINE_FAILED,
            candidate_id=selected_id,
            format_id=format_id,
            source_confidence=sc_score,
            editorial_quality=eq_score,
            draft_title=draft_title,
            draft_body=draft_body,
            error=f"readiness evaluation failed: {exc}",
            evaluations=tuple(evaluations),
        )

    rd_status = readiness_decision.status
    rd_codes = readiness_decision.reason_codes
    rd_warnings = readiness_decision.warnings

    # ── Map readiness to outcome ───────────────────────────────────────────
    if rd_status == RDY.STATUS_READY:
        outcome = OUTCOME_READY_IN_SHADOW
    elif rd_status == RDY.STATUS_READY_WITH_WARNINGS:
        outcome = OUTCOME_READY_WITH_WARNINGS_HOLD
    elif rd_status == RDY.STATUS_REQUIRES_MANUAL_REVIEW:
        outcome = OUTCOME_REQUIRES_MANUAL_REVIEW
    else:
        outcome = OUTCOME_QUALITY_REJECTED

    # ── Artifact generation (7A) — routed by content type ──────────────────
    artifact_dict = None
    try:
        artifact_dict = _generate_artifact(
            content_type, slot_id, editorial_day, normalized,
            selected, selected_id, sc_results, sc_result,
            quality_result, rd_status, rd_codes, candidates,
            admission_result, format_id,
        )
    except Exception:
        pass  # Artifact generation is best-effort; don't fail the slot

    return SlotResult(
        slot_id=slot_id,
        content_type=ct_name,
        editorial_day=editorial_day,
        outcome=outcome,
        candidate_id=selected_id,
        format_id=format_id,
        artifact_type=format_id,
        source_confidence=sc_score,
        editorial_quality=eq_score,
        readiness_status=rd_status,
        reason_codes=tuple(rd_codes),
        warnings=tuple(rd_warnings),
        draft_title=draft_title,
        draft_body=draft_body,
        artifact=artifact_dict,
        evaluations=tuple(evaluations),
    )


# ── Public entry point ───────────────────────────────────────────────────────

def run_pipeline(
    inp: PipelineInput,
) -> PipelineResult:
    """Run the full editorial pipeline for one date.

    Returns a PipelineResult with one SlotResult per slot.
    Never publishes, never notifies, never writes live history.
    """
    if inp.mode not in ALLOWED_MODES:
        return PipelineResult(
            mode=inp.mode,
            date=inp.date,
            editorial_day="",
            slot_results=(),
            config_errors=(f"unsupported mode: {inp.mode!r}; allowed: {sorted(ALLOWED_MODES)}",),
        )

    now = inp.now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    started_at = now.isoformat()
    editorial_day = _editorial_day_for(inp.date, editorial_timezone())

    draft_builder = inp.draft_builder or _default_draft_builder

    # ── Load slot config ───────────────────────────────────────────────────
    try:
        from .slots import load_slots
        slot_config = load_slots()
    except Exception as exc:
        return PipelineResult(
            mode=inp.mode,
            date=inp.date,
            editorial_day=editorial_day,
            slot_results=(),
            started_at=started_at,
            completed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            config_errors=(str(exc),),
        )

    # ── Resolve slots for this weekday ─────────────────────────────────────
    weekday = editorial_day.lower()
    try:
        slot_pairs = slot_config.slots_for(weekday)
    except Exception as exc:
        return PipelineResult(
            mode=inp.mode,
            date=inp.date,
            editorial_day=editorial_day,
            slot_results=(),
            started_at=started_at,
            completed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            config_errors=(str(exc),),
        )

    # ── Run each slot ──────────────────────────────────────────────────────
    slot_results: list[SlotResult] = []
    for slot, content_type in slot_pairs:
        result = _run_slot(
            slot, content_type, inp.candidates, inp.history_rows,
            inp.date, draft_builder, now,
        )
        slot_results.append(result)

    completed_at = dt.datetime.now(dt.timezone.utc).isoformat()

    pipeline_result = PipelineResult(
        mode=inp.mode,
        date=inp.date,
        editorial_day=editorial_day,
        slot_results=tuple(slot_results),
        started_at=started_at,
        completed_at=completed_at,
    )

    # ── Persist ────────────────────────────────────────────────────────────
    _persist(pipeline_result, inp.mode)

    return pipeline_result


# ── Persistence ──────────────────────────────────────────────────────────────

def _persist(result: PipelineResult, mode: str) -> list[Path]:
    """Write per-slot pipeline results to the git-ignored state directory.

    Each slot gets its own file so repeated runs for the same date do not
    overwrite each other. File naming:
      pipeline_YYYY-MM-DD_<slot_id>.json
    """
    out_dir = _mode_dir(mode)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for sr in result.slot_results:
        filename = f"pipeline_{result.date}_{sr.slot_id}.json"
        path = out_dir / filename
        data = {
            "mode": result.mode,
            "date": result.date,
            "editorial_day": result.editorial_day,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "config_errors": list(result.config_errors),
            "slot_result": _slot_to_dict(sr),
        }
        path.write_text(
            json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        paths.append(path)
    return paths
