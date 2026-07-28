"""Phase 1 Stage 6 — deterministic publication readiness verdict.

Combines pre-generation topic admission and post-generation draft quality into a
single publication-readiness verdict. This stage never publishes anything; it
only returns one of four states and, optionally, records the result in the
ContentDecision ledger for shadow analysis.

Guarantees:
  * deterministic — same unchanged input yields the same decision_id
  * no LLM, no network, no content generation
  * no mutation of live publication history while EDITORIAL_SLOTS_ENABLED=false
  * duplicate publication intent blocks new ready states for the same slot/day
  * shadow records never affect saturation or live format rotation
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from .admission import ADMITTED, AdmissionResult, CandidateEvaluation
from .flags import editorial_slots_enabled, editorial_timezone
from .models import (
    Claim,
    Candidate,
    SourceRef,
    VERIFIED_INDEPENDENT,
    digest,
)
from .publication_record import MODE_LIVE, MODE_SHADOW, editorial_day_for
from .quality import (
    CONFIG_PATH,
    DraftInput,
    QualityResult,
    STATUS_FAIL as QUALITY_FAIL,
    WARNING_ABOVE_WORD_RANGE,
    WARNING_EXCESSIVE_HEDGING,
    WARNING_GENERIC_FILLER,
    WARNING_GENERIC_INTRO,
    WARNING_LONG_PARAGRAPH,
    WARNING_SUMMARY_MISSING,
    WARNING_TITLE_BODY_LOW_OVERLAP,
    WARNING_TRUNCATED_SENTENCE,
)

RESULT_VERSION = 1

STATUS_READY = "ready"
STATUS_READY_WITH_WARNINGS = "ready_with_warnings"
STATUS_REJECTED = "rejected"
STATUS_REQUIRES_MANUAL_REVIEW = "requires_manual_review"

RC_ADMISSION_NOT_SUCCESSFUL = "admission_not_successful"
RC_EDITORIAL_QUALITY_FAILED = "editorial_quality_failed"
RC_EDITORIAL_HARD_FAILURE = "editorial_hard_failure"
RC_REQUIRED_SOURCES_DISAPPEARED = "required_sources_disappeared"
RC_UNSUPPORTED_CLAIMS = "unsupported_claims_present"
RC_CONTRADICTS_CONFIRMED_FACTS = "draft_contradicts_confirmed_facts"
RC_ARTIFACT_TYPE_MISMATCH = "artifact_type_mismatch"
RC_FORMAT_ID_MISMATCH = "format_id_mismatch"
RC_DRAFT_INCOMPLETE = "draft_incomplete_or_truncated"
RC_DUPLICATE_PUBLICATION_INTENT = "duplicate_publication_intent"
RC_DUPLICATE_SUCCESSFUL_PUBLICATION = "duplicate_successful_publication"
RC_UNSTABLE_CANDIDATE_SLOT = "unstable_candidate_or_slot_identity"

RC_IMPORTANT_QUALITY_WARNING = "important_quality_warning"
RC_SOURCE_CONFIDENCE_NEAR_THRESHOLD = "source_confidence_near_threshold"
RC_RELATIONSHIP_MATERIAL_UNKNOWNS = "relationship_material_unknowns"
RC_SENSITIVE_LEGAL_CONTENT = "sensitive_legal_content"
RC_SENSITIVE_SECURITY_CONTENT = "sensitive_security_content"
RC_SENSITIVE_FINANCIAL_CONTENT = "sensitive_financial_content"
RC_SENSITIVE_ACCUSATION_CONTENT = "sensitive_accusation_content"
RC_VENDOR_BENCHMARK_UNVERIFIED = "vendor_benchmark_unverified"
RC_R4_OVERRIDE_USED = "r4_material_override_used"
RC_SOURCES_CHANGED_MATERIALLY = "sources_changed_materially"
RC_TRACEABLE_BUT_AMBIGUOUS = "traceable_but_ambiguous_claim"

ALL_READINESS_REASON_CODES = frozenset({
    RC_ADMISSION_NOT_SUCCESSFUL,
    RC_EDITORIAL_QUALITY_FAILED,
    RC_EDITORIAL_HARD_FAILURE,
    RC_REQUIRED_SOURCES_DISAPPEARED,
    RC_UNSUPPORTED_CLAIMS,
    RC_CONTRADICTS_CONFIRMED_FACTS,
    RC_ARTIFACT_TYPE_MISMATCH,
    RC_FORMAT_ID_MISMATCH,
    RC_DRAFT_INCOMPLETE,
    RC_DUPLICATE_PUBLICATION_INTENT,
    RC_DUPLICATE_SUCCESSFUL_PUBLICATION,
    RC_UNSTABLE_CANDIDATE_SLOT,
    RC_IMPORTANT_QUALITY_WARNING,
    RC_SOURCE_CONFIDENCE_NEAR_THRESHOLD,
    RC_RELATIONSHIP_MATERIAL_UNKNOWNS,
    RC_SENSITIVE_LEGAL_CONTENT,
    RC_SENSITIVE_SECURITY_CONTENT,
    RC_SENSITIVE_FINANCIAL_CONTENT,
    RC_SENSITIVE_ACCUSATION_CONTENT,
    RC_VENDOR_BENCHMARK_UNVERIFIED,
    RC_R4_OVERRIDE_USED,
    RC_SOURCES_CHANGED_MATERIALLY,
    RC_TRACEABLE_BUT_AMBIGUOUS,
})

KNOWN_NON_BLOCKING_QUALITY_CODES = frozenset({
    WARNING_ABOVE_WORD_RANGE,
    WARNING_TRUNCATED_SENTENCE,
    WARNING_GENERIC_FILLER,
    WARNING_LONG_PARAGRAPH,
    WARNING_GENERIC_INTRO,
    WARNING_SUMMARY_MISSING,
    WARNING_EXCESSIVE_HEDGING,
    WARNING_TITLE_BODY_LOW_OVERLAP,
})


@dataclass(frozen=True)
class ReadinessConfig:
    schema_version: int
    ready_quality_threshold: int
    warning_quality_threshold: int
    near_threshold_margin: int
    allowed_non_blocking_quality_issues: frozenset[str]
    manual_review_triggers: frozenset[str]
    sensitive_development_types: frozenset[str]
    auto_ready_development_types: frozenset[str]
    required_draft_fingerprint_fields: tuple[str, ...]
    required_source_fingerprint_fields: tuple[str, ...]
    duplicate_lookup_stages: tuple[str, ...]
    duplicate_blocking_statuses: tuple[str, ...]
    duplicate_identity_keys: tuple[str, ...]
    allow_hard_failures_to_pass: bool
    allow_rejected_admissions_to_pass: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ready_quality_threshold": self.ready_quality_threshold,
            "warning_quality_threshold": self.warning_quality_threshold,
            "near_threshold_margin": self.near_threshold_margin,
            "allowed_non_blocking_quality_issues": sorted(self.allowed_non_blocking_quality_issues),
            "manual_review_triggers": sorted(self.manual_review_triggers),
            "sensitive_development_types": sorted(self.sensitive_development_types),
            "auto_ready_development_types": sorted(self.auto_ready_development_types),
            "required_fingerprint_fields": {
                "draft": list(self.required_draft_fingerprint_fields),
                "source": list(self.required_source_fingerprint_fields),
            },
            "duplicate_detection": {
                "stages": list(self.duplicate_lookup_stages),
                "blocking_statuses": list(self.duplicate_blocking_statuses),
                "identity_keys": list(self.duplicate_identity_keys),
            },
            "allow_hard_failures_to_pass": self.allow_hard_failures_to_pass,
            "allow_rejected_admissions_to_pass": self.allow_rejected_admissions_to_pass,
        }


class ReadinessConfigError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        joined = "\n  - ".join(self.problems)
        super().__init__(f"{len(self.problems)} readiness config problem(s):\n  - {joined}")


def load_readiness_config(path: Path | None = None) -> ReadinessConfig:
    path = path or CONFIG_PATH
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    ready = raw.get("readiness") or {}
    problems: list[str] = []

    schema_version = ready.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 1:
        problems.append("readiness.schema_version must be a positive integer")

    def _int_0_100(key: str) -> int:
        value = ready.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            problems.append(f"readiness.{key} must be an integer 0-100")
            return 0
        return value

    ready_threshold = _int_0_100("ready_quality_threshold")
    warning_threshold = _int_0_100("warning_quality_threshold")
    if ready_threshold < warning_threshold:
        problems.append("readiness.ready_quality_threshold must be >= warning_quality_threshold")

    near_margin = ready.get("near_threshold_margin")
    if not isinstance(near_margin, int) or isinstance(near_margin, bool) or near_margin < 0:
        problems.append("readiness.near_threshold_margin must be a non-negative integer")
        near_margin = 0

    allowed_non_blocking = ready.get("allowed_non_blocking_quality_issues", [])
    if not isinstance(allowed_non_blocking, list):
        problems.append("readiness.allowed_non_blocking_quality_issues must be a list")
        allowed_non_blocking = []
    else:
        unknown = [code for code in allowed_non_blocking if not isinstance(code, str)]
        if unknown:
            problems.append("readiness.allowed_non_blocking_quality_issues must contain strings only")
        unknown_codes = [code for code in allowed_non_blocking
                         if isinstance(code, str) and code not in KNOWN_NON_BLOCKING_QUALITY_CODES]
        if unknown_codes:
            problems.append(
                "readiness.allowed_non_blocking_quality_issues contains unknown codes: "
                + ", ".join(sorted(unknown_codes)))

    manual_review_triggers = ready.get("manual_review_triggers", [])
    if not isinstance(manual_review_triggers, list):
        problems.append("readiness.manual_review_triggers must be a list")
        manual_review_triggers = []
    else:
        unknown_manual = [code for code in manual_review_triggers
                          if code not in ALL_READINESS_REASON_CODES]
        if unknown_manual:
            problems.append(
                f"readiness.manual_review_triggers contains unknown codes: {', '.join(sorted(unknown_manual))}")

    sensitive_types = ready.get("sensitive_development_types", [])
    if not isinstance(sensitive_types, list):
        problems.append("readiness.sensitive_development_types must be a list")
        sensitive_types = []
    auto_ready_types = ready.get("auto_ready_development_types", [])
    if not isinstance(auto_ready_types, list):
        problems.append("readiness.auto_ready_development_types must be a list")
        auto_ready_types = []
    overlap = set(str(x) for x in sensitive_types) & set(str(x) for x in auto_ready_types)
    if overlap:
        problems.append(
            "readiness.sensitive_development_types may not overlap auto_ready_development_types")

    fp = ready.get("required_fingerprint_fields", {})
    if not isinstance(fp, dict):
        problems.append("readiness.required_fingerprint_fields must be a mapping")
        fp = {}
    draft_fields = fp.get("draft", [])
    source_fields = fp.get("source", [])
    if not isinstance(draft_fields, list) or not all(isinstance(x, str) and x for x in draft_fields):
        problems.append("readiness.required_fingerprint_fields.draft must be a non-empty list of strings")
        draft_fields = []
    if not isinstance(source_fields, list) or not all(isinstance(x, str) and x for x in source_fields):
        problems.append("readiness.required_fingerprint_fields.source must be a non-empty list of strings")
        source_fields = []

    dup = ready.get("duplicate_detection", {})
    if not isinstance(dup, dict):
        problems.append("readiness.duplicate_detection must be a mapping")
        dup = {}
    dup_stages = dup.get("stages", [])
    dup_statuses = dup.get("blocking_statuses", [])
    dup_keys = dup.get("identity_keys", [])
    if not isinstance(dup_stages, list) or not all(isinstance(x, str) and x for x in dup_stages):
        problems.append("readiness.duplicate_detection.stages must be a non-empty list of strings")
        dup_stages = []
    if not isinstance(dup_statuses, list) or not all(isinstance(x, str) and x for x in dup_statuses):
        problems.append("readiness.duplicate_detection.blocking_statuses must be a non-empty list of strings")
        dup_statuses = []
    if not isinstance(dup_keys, list) or not all(isinstance(x, str) and x for x in dup_keys):
        problems.append("readiness.duplicate_detection.identity_keys must be a non-empty list of strings")
        dup_keys = []
    if not dup_keys:
        problems.append("readiness.duplicate_detection.identity_keys may not be empty")

    allow_hard = bool(ready.get("allow_hard_failures_to_pass", False))
    allow_rejected = bool(ready.get("allow_rejected_admissions_to_pass", False))
    if allow_hard:
        problems.append("readiness may not allow hard failures to pass")
    if allow_rejected:
        problems.append("readiness may not allow rejected admissions to pass")

    if problems:
        raise ReadinessConfigError(problems)

    return ReadinessConfig(
        schema_version=schema_version,
        ready_quality_threshold=ready_threshold,
        warning_quality_threshold=warning_threshold,
        near_threshold_margin=near_margin,
        allowed_non_blocking_quality_issues=frozenset(str(x) for x in allowed_non_blocking),
        manual_review_triggers=frozenset(str(x) for x in manual_review_triggers),
        sensitive_development_types=frozenset(str(x) for x in sensitive_types),
        auto_ready_development_types=frozenset(str(x) for x in auto_ready_types),
        required_draft_fingerprint_fields=tuple(draft_fields),
        required_source_fingerprint_fields=tuple(source_fields),
        duplicate_lookup_stages=tuple(dup_stages),
        duplicate_blocking_statuses=tuple(dup_statuses),
        duplicate_identity_keys=tuple(dup_keys),
        allow_hard_failures_to_pass=allow_hard,
        allow_rejected_admissions_to_pass=allow_rejected,
    )


@dataclass(frozen=True)
class ReadinessInput:
    slot_policy_snapshot: dict[str, Any]
    candidate: Candidate | None
    source_confidence_result: Any | None
    saturation_result: Any | None
    admission_result: AdmissionResult
    draft: DraftInput
    quality_result: QualityResult
    source_evidence: tuple[SourceRef | dict[str, Any], ...] = ()
    claim_evidence: tuple[Claim | dict[str, Any], ...] = ()
    generation_metadata: dict[str, Any] = field(default_factory=dict)
    artifact_type: str = ""
    format_id: str = ""
    editorial_day: str = ""


@dataclass(frozen=True)
class DuplicateMatch:
    duplicate_intent: bool = False
    successful_publication: bool = False
    matching_decision_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "duplicate_intent": self.duplicate_intent,
            "successful_publication": self.successful_publication,
            "matching_decision_id": self.matching_decision_id,
        }


@dataclass(frozen=True)
class ReadinessDecision:
    decision_id: str
    candidate_id: str
    slot_id: str
    editorial_day: str
    artifact_type: str
    format_id: str
    status: str
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    manual_review_reasons: tuple[str, ...]
    admission_summary: dict[str, Any]
    quality_summary: dict[str, Any]
    source_confidence: int | None
    editorial_quality: int | None
    policy_snapshot: dict[str, Any]
    draft_fingerprint: str
    source_fingerprint: str
    decision_time: str
    mode: str
    version: int = RESULT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "candidate_id": self.candidate_id,
            "slot_id": self.slot_id,
            "editorial_day": self.editorial_day,
            "artifact_type": self.artifact_type,
            "format_id": self.format_id,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "warnings": list(self.warnings),
            "manual_review_reasons": list(self.manual_review_reasons),
            "admission_summary": self.admission_summary,
            "quality_summary": self.quality_summary,
            "source_confidence": self.source_confidence,
            "editorial_quality": self.editorial_quality,
            "policy_snapshot": self.policy_snapshot,
            "draft_fingerprint": self.draft_fingerprint,
            "source_fingerprint": self.source_fingerprint,
            "decision_time": self.decision_time,
            "mode": self.mode,
            "version": self.version,
        }


def _selected_evaluation(result: AdmissionResult) -> CandidateEvaluation | None:
    for evaluation in result.evaluated_candidates:
        if evaluation.candidate_id == result.selected_candidate_id:
            return evaluation
    return None


def _normalize_source(source: SourceRef | dict[str, Any]) -> dict[str, Any]:
    return source.to_dict() if hasattr(source, "to_dict") else dict(source)


def _normalize_claim(claim: Claim | dict[str, Any]) -> dict[str, Any]:
    return claim.to_dict() if hasattr(claim, "to_dict") else dict(claim)


def _editorial_day(inp: ReadinessInput, now: dt.datetime) -> str:
    if inp.editorial_day:
        return inp.editorial_day
    raw = inp.generation_metadata.get("generated_at")
    if raw:
        stamp = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        return editorial_day_for(stamp, editorial_timezone())
    return editorial_day_for(now, editorial_timezone())


def _draft_fingerprint(inp: ReadinessInput, config: ReadinessConfig) -> str:
    draft = inp.draft
    values: list[str] = []
    for field_name in config.required_draft_fingerprint_fields:
        if field_name == "title":
            values.append(draft.title)
        elif field_name == "body":
            values.append(draft.body)
        elif field_name == "summary":
            values.append(draft.summary)
        elif field_name == "artifact_type":
            values.append(inp.artifact_type or draft.artifact_type)
        elif field_name == "format_id":
            values.append(inp.format_id or draft.format_id)
        else:
            values.append(str(inp.generation_metadata.get(field_name, "")))
    return "draft_" + digest(*values, length=24)


def _source_fingerprint(inp: ReadinessInput, config: ReadinessConfig) -> str:
    candidate = inp.candidate
    source_urls = sorted({
        _normalize_source(source).get("url", "")
        for source in (inp.source_evidence or (candidate.sources if candidate else ()))
        if _normalize_source(source).get("url", "")
    })
    claim_ids = sorted({
        _normalize_claim(claim).get("claim_id", "")
        for claim in (inp.claim_evidence or (candidate.claims if candidate else ()))
        if _normalize_claim(claim).get("claim_id", "")
    })
    claim_texts = sorted({
        _normalize_claim(claim).get("normalized_text")
        or _normalize_claim(claim).get("text", "")
        for claim in (inp.claim_evidence or (candidate.claims if candidate else ()))
        if _normalize_claim(claim).get("normalized_text") or _normalize_claim(claim).get("text", "")
    })

    values: list[str] = []
    for field_name in config.required_source_fingerprint_fields:
        if field_name == "candidate_id":
            values.append(candidate.candidate_id if candidate else "")
        elif field_name == "canonical_topic_id":
            values.append(candidate.canonical_topic_id if candidate else "")
        elif field_name == "source_urls":
            values.append("|".join(source_urls))
        elif field_name == "claim_ids":
            values.append("|".join(claim_ids))
        elif field_name == "claim_texts":
            values.append("|".join(claim_texts))
        elif field_name == "candidate_source_fingerprint":
            values.append(candidate.source_fingerprint if candidate else "")
        else:
            values.append(str(inp.generation_metadata.get(field_name, "")))
    return "src_" + digest(*values, length=24)


def _decision_id(candidate_id: str, slot_id: str, editorial_day: str,
                 artifact_type: str, draft_fingerprint: str) -> str:
    return "rdy_" + digest(candidate_id, slot_id, editorial_day,
                           artifact_type, draft_fingerprint, length=24)


def _duplicate_match(existing_rows: Iterable[dict[str, Any]], *,
                     candidate_id: str, slot_id: str, editorial_day: str,
                     decision_id: str, config: ReadinessConfig) -> DuplicateMatch:
    for row in existing_rows:
        metadata = row.get("metadata") or {}
        row_candidate = str(metadata.get("candidate_id") or "")
        row_slot = str(metadata.get("slot_id") or metadata.get("slot") or "")
        row_day = str(metadata.get("editorial_day") or "")
        if (row_candidate, row_slot, row_day) != (candidate_id, slot_id, editorial_day):
            continue

        row_decision_id = str(metadata.get("decision_id") or "")
        if row_decision_id and row_decision_id == decision_id:
            continue

        stage = str(row.get("stage") or "")
        if stage == "publish" and row.get("decision") == "accepted":
            return DuplicateMatch(successful_publication=True,
                                  matching_decision_id=row_decision_id)

        row_status = str(metadata.get("status") or "")
        if (stage in config.duplicate_lookup_stages
                and row.get("decision") == "accepted"
                and row_status in config.duplicate_blocking_statuses):
            return DuplicateMatch(duplicate_intent=True,
                                  matching_decision_id=row_decision_id)
    return DuplicateMatch()


def _contains_material_unknown_relationships(candidate: Candidate | None,
                                             generation_metadata: dict[str, Any]) -> bool:
    if generation_metadata.get("relationship_material_unknowns"):
        return True
    if not candidate:
        return False
    warnings = set(candidate.warnings or ())
    return any(code in warnings for code in ("subject_org_unresolved", "subject_org_low_confidence"))


def _has_sensitive_claim_type(claims: Sequence[Claim | dict[str, Any]], claim_type: str) -> bool:
    for claim in claims:
        data = _normalize_claim(claim)
        if data.get("claim_type") == claim_type:
            return True
    return False


def evaluate_readiness(inp: ReadinessInput, config: ReadinessConfig | None = None,
                       *, existing_rows: Iterable[dict[str, Any]] = (),
                       now: dt.datetime | None = None) -> ReadinessDecision:
    """Pure readiness evaluation with no writes."""
    config = config or load_readiness_config()
    now = (now or dt.datetime.now(dt.timezone.utc))
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now = now.astimezone(dt.timezone.utc)

    candidate = inp.candidate
    slot_id = str(inp.slot_policy_snapshot.get("slot_id") or inp.admission_result.slot_id)
    artifact_type = inp.artifact_type or inp.draft.artifact_type
    format_id = inp.format_id or inp.draft.format_id
    editorial_day = _editorial_day(inp, now)
    candidate_id = candidate.candidate_id if candidate else ""
    draft_fingerprint = _draft_fingerprint(inp, config)
    source_fingerprint = _source_fingerprint(inp, config)
    decision_id = _decision_id(candidate_id, slot_id, editorial_day,
                               artifact_type, draft_fingerprint)
    selected = _selected_evaluation(inp.admission_result)
    duplicate = _duplicate_match(
        existing_rows,
        candidate_id=candidate_id,
        slot_id=slot_id,
        editorial_day=editorial_day,
        decision_id=decision_id,
        config=config,
    )

    reasons: list[str] = []
    warnings: list[str] = []
    manual_reasons: list[str] = []

    if not candidate_id or not slot_id:
        reasons.append(RC_UNSTABLE_CANDIDATE_SLOT)

    admission_successful = (
        inp.admission_result.status == ADMITTED
        and selected is not None
        and selected.candidate_id == candidate_id
    )
    if not admission_successful:
        reasons.append(RC_ADMISSION_NOT_SUCCESSFUL)

    if inp.quality_result.status == QUALITY_FAIL or inp.quality_result.score < config.warning_quality_threshold:
        reasons.append(RC_EDITORIAL_QUALITY_FAILED)

    if inp.quality_result.hard_failures:
        reasons.append(RC_EDITORIAL_HARD_FAILURE)

    if inp.generation_metadata.get("required_sources_disappeared"):
        reasons.append(RC_REQUIRED_SOURCES_DISAPPEARED)

    if inp.generation_metadata.get("unsupported_claims_present"):
        reasons.append(RC_UNSUPPORTED_CLAIMS)

    if inp.generation_metadata.get("draft_contradicts_confirmed_facts"):
        reasons.append(RC_CONTRADICTS_CONFIRMED_FACTS)

    admitted_artifact = inp.generation_metadata.get("admitted_artifact_type") or (
        candidate.artifact_type if candidate else artifact_type
    )
    admitted_format = inp.generation_metadata.get("admitted_format_id") or format_id
    if admitted_artifact != artifact_type and not inp.generation_metadata.get("artifact_change_authorized", False):
        reasons.append(RC_ARTIFACT_TYPE_MISMATCH)
    if admitted_format != format_id and not inp.generation_metadata.get("format_change_authorized", False):
        reasons.append(RC_FORMAT_ID_MISMATCH)

    if inp.generation_metadata.get("draft_incomplete") or inp.generation_metadata.get("draft_truncated"):
        reasons.append(RC_DRAFT_INCOMPLETE)

    if duplicate.successful_publication:
        reasons.append(RC_DUPLICATE_SUCCESSFUL_PUBLICATION)
    elif duplicate.duplicate_intent:
        reasons.append(RC_DUPLICATE_PUBLICATION_INTENT)

    # Manual-review conditions.
    non_blocking_codes = set(config.allowed_non_blocking_quality_issues)
    quality_warning_codes = {note.code for note in inp.quality_result.warning_details}
    quality_issue_codes = {note.code for note in inp.quality_result.issue_details}
    important_quality_codes = (quality_warning_codes | quality_issue_codes) - non_blocking_codes
    if inp.quality_result.status != QUALITY_FAIL and important_quality_codes:
        manual_reasons.append(RC_IMPORTANT_QUALITY_WARNING)

    threshold = int(inp.slot_policy_snapshot.get(
        "source_confidence_threshold",
        getattr(inp.source_confidence_result, "score", 0) or 0,
    ))
    source_conf = getattr(inp.source_confidence_result, "score", None)
    if source_conf is not None and threshold <= source_conf < threshold + config.near_threshold_margin:
        manual_reasons.append(RC_SOURCE_CONFIDENCE_NEAR_THRESHOLD)

    if _contains_material_unknown_relationships(candidate, inp.generation_metadata):
        manual_reasons.append(RC_RELATIONSHIP_MATERIAL_UNKNOWNS)

    if inp.generation_metadata.get("contains_legal_risk"):
        manual_reasons.append(RC_SENSITIVE_LEGAL_CONTENT)
    elif candidate and candidate.development_type == "licensing_change":
        manual_reasons.append(RC_SENSITIVE_LEGAL_CONTENT)
    if inp.generation_metadata.get("contains_security_risk") or (
            candidate and candidate.development_type == "security_issue"):
        manual_reasons.append(RC_SENSITIVE_SECURITY_CONTENT)
    if inp.generation_metadata.get("contains_financial_risk") or (
            candidate and candidate.development_type == "pricing_change"):
        manual_reasons.append(RC_SENSITIVE_FINANCIAL_CONTENT)
    if inp.generation_metadata.get("contains_accusation_risk"):
        manual_reasons.append(RC_SENSITIVE_ACCUSATION_CONTENT)

    claims = inp.claim_evidence or (candidate.claims if candidate else ())
    if (inp.generation_metadata.get("vendor_benchmark_unverified")
            or any(_normalize_claim(claim).get("claim_type") == "benchmark"
                   and _normalize_claim(claim).get("verification") != VERIFIED_INDEPENDENT
                   for claim in claims)):
        manual_reasons.append(RC_VENDOR_BENCHMARK_UNVERIFIED)

    if selected and selected.r4_material_downgrade:
        manual_reasons.append(RC_R4_OVERRIDE_USED)

    if inp.generation_metadata.get("sources_changed_materially"):
        manual_reasons.append(RC_SOURCES_CHANGED_MATERIALLY)

    if inp.generation_metadata.get("traceable_but_ambiguous_claim"):
        manual_reasons.append(RC_TRACEABLE_BUT_AMBIGUOUS)

    reasons = list(dict.fromkeys(reasons))
    manual_reasons = list(dict.fromkeys(
        [code for code in manual_reasons if code in config.manual_review_triggers]
    ))
    warnings = sorted(code for code in quality_warning_codes if code in non_blocking_codes)

    if reasons:
        status = STATUS_REJECTED
    elif manual_reasons:
        status = STATUS_REQUIRES_MANUAL_REVIEW
    elif warnings or inp.quality_result.status != "pass":
        status = STATUS_READY_WITH_WARNINGS
    elif inp.quality_result.score >= config.ready_quality_threshold:
        status = STATUS_READY
    else:
        status = STATUS_REJECTED
        reasons.append(RC_EDITORIAL_QUALITY_FAILED)

    mode = MODE_LIVE if editorial_slots_enabled() else MODE_SHADOW

    return ReadinessDecision(
        decision_id=decision_id,
        candidate_id=candidate_id,
        slot_id=slot_id,
        editorial_day=editorial_day,
        artifact_type=artifact_type,
        format_id=format_id,
        status=status,
        reason_codes=tuple(reasons),
        warnings=tuple(warnings),
        manual_review_reasons=tuple(manual_reasons),
        admission_summary={
            "status": inp.admission_result.status,
            "selected_candidate_id": inp.admission_result.selected_candidate_id,
            "selected_reason_codes": list(selected.reason_codes if selected else ()),
            "source_confidence": getattr(selected, "source_confidence", None),
            "saturation_status": getattr(selected, "saturation_status", ""),
            "r4_material_downgrade": bool(getattr(selected, "r4_material_downgrade", False)),
            "version": inp.admission_result.version,
        },
        quality_summary={
            "status": inp.quality_result.status,
            "score": inp.quality_result.score,
            "hard_failures": list(inp.quality_result.hard_failures),
            "issue_codes": sorted({note.code for note in inp.quality_result.issue_details}),
            "warning_codes": sorted(quality_warning_codes),
            "version": inp.quality_result.version,
        },
        source_confidence=source_conf,
        editorial_quality=inp.quality_result.score,
        policy_snapshot={
            **inp.slot_policy_snapshot,
            "readiness": config.to_dict(),
        },
        draft_fingerprint=draft_fingerprint,
        source_fingerprint=source_fingerprint,
        decision_time=now.isoformat(),
        mode=mode,
        version=RESULT_VERSION,
    )


def record_readiness_decision(decision: ReadinessDecision) -> None:
    """Append a Stage 6 readiness record to the ContentDecision ledger."""
    from agent.content_decisions import ContentDecision, record as cd_record

    accepted = decision.status in (STATUS_READY, STATUS_READY_WITH_WARNINGS)
    publication_readiness = "passed" if accepted else "failed"
    reason = "; ".join(decision.reason_codes or decision.manual_review_reasons or decision.warnings)
    metadata = {
        "mode": decision.mode,
        "decision_id": decision.decision_id,
        "candidate_id": decision.candidate_id,
        "slot_id": decision.slot_id,
        "editorial_day": decision.editorial_day,
        "artifact_type": decision.artifact_type,
        "format_id": decision.format_id,
        "status": decision.status,
        "reason_codes": list(decision.reason_codes),
        "warning_codes": list(decision.warnings),
        "manual_review_reasons": list(decision.manual_review_reasons),
        "admission_summary": decision.admission_summary,
        "quality_summary": decision.quality_summary,
        "draft_fingerprint": decision.draft_fingerprint,
        "source_fingerprint": decision.source_fingerprint,
        "policy_snapshot": decision.policy_snapshot,
        "scorer_versions": {
            "admission": decision.admission_summary.get("version"),
            "quality": decision.quality_summary.get("version"),
            "readiness": decision.version,
            "policy_schema": decision.policy_snapshot.get("readiness", {}).get("schema_version"),
        },
    }

    cd_record(ContentDecision(
        stage="article_gate",
        decision="accepted" if accepted else "rejected",
        job_id=f"readiness:{decision.slot_id}:{decision.candidate_id}:{decision.decision_id}",
        title="",
        slug="",
        reason_code="",
        reason=reason,
        source_confidence=decision.source_confidence,
        editorial_quality=decision.editorial_quality,
        publication_readiness=publication_readiness,
        sources=[],
        content_format=decision.format_id,
        metadata=metadata,
    ))


def evaluate_and_record_readiness(inp: ReadinessInput,
                                  config: ReadinessConfig | None = None,
                                  *, existing_rows: Iterable[dict[str, Any]] | None = None,
                                  now: dt.datetime | None = None) -> ReadinessDecision:
    if existing_rows is None:
        from agent.content_decisions import read

        existing_rows = read()
    decision = evaluate_readiness(inp, config, existing_rows=existing_rows, now=now)
    record_readiness_decision(decision)
    return decision
