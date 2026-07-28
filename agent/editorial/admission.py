"""Deterministic topic admission and backup-candidate selection (Phase 1, Stage 4).

Composes the five prior stages into one explainable admit/reject decision per
slot. The output is an AdmissionResult — never a publication, never a write to
live history.

Pipeline per candidate:
  1. Normalize (already done upstream; structural validity checked here)
  2. Detect source relationships
  3. Apply relationships (enrich source refs)
  4. Score source confidence
  5. Evaluate saturation
  6. Apply slot-specific policy (hard gates)

The admission function is pure. Shadow-mode decision recording is separated so
the pure admission logic stays independently testable without any writes.

Guarantees:
  * deterministic — same input, same output
  * no LLM, no network, no content generation
  * no writes to live publication history while EDITORIAL_SLOTS_ENABLED=false
  * high opportunity score never overrides low source confidence or saturation
  * R1 is never downgraded; R4 material downgrade requires ALL conditions
  * thresholds are never lowered to fill a slot
  * shadow decision records carry mode=shadow, do not influence saturation
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

KIT = Path(__file__).resolve().parents[2]
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from .models import (
    DEVELOPMENT_TYPES,
    Candidate,
    Claim,
    NormalizationError,
    SourceRef,
)
from .source_relationships import (
    RelationshipConfig,
    SourceRelationship,
    apply_relationships,
    detect_relationships,
)
from .source_confidence import (
    ScoringConfig,
    SourceConfidence,
    score_source_confidence,
)
from .saturation import (
    HistoryView,
    SaturationConfig,
    SaturationResult,
    evaluate_saturation,
    STATUS_REJECT,
    STATUS_WARNING,
    STATUS_CLEAR,
    THEME_UNKNOWN,
)
from .slots import (
    ContentType,
    Slot,
    SlotConfig,
)
from .flags import editorial_shadow_mode, editorial_slots_enabled

RESULT_VERSION = 1

# ── Admission outcomes ──────────────────────────────────────────────────────

ADMITTED = "admitted"
REJECTED = "rejected"
WARNING = "warning"
INVALID_CANDIDATE = "invalid_candidate"
SKIPPED_NO_CANDIDATE = "skipped_no_candidate"

# ── Reason codes (machine-readable, stable) ─────────────────────────────────

RC_INVALID_CANDIDATE = "invalid_candidate"
RC_SOURCE_CONFIDENCE_BELOW_THRESHOLD = "source_confidence_below_threshold"
RC_PRIMARY_SOURCE_REQUIRED = "primary_source_required"
RC_INSUFFICIENT_CORROBORATION = "insufficient_corroboration"
RC_OPPORTUNITY_SCORE_BELOW_THRESHOLD = "opportunity_score_below_threshold"
RC_EXACT_TOPIC_DUPLICATE = "exact_topic_duplicate"
RC_ENTITY_SATURATED = "entity_saturated"
RC_ENTITY_DEVELOPMENT_SATURATED = "entity_development_saturated"
RC_THEME_SATURATED = "theme_saturated"
RC_SAME_DAY_REUSE = "same_day_reuse"
RC_ARTIFACT_REPETITION = "artifact_repetition"
RC_DEVELOPMENT_TYPE_NOT_ALLOWED = "development_type_not_allowed"
RC_ARTIFACT_NOT_ALLOWED = "artifact_not_allowed"
RC_PRACTICAL_VALUE_MISSING = "practical_value_missing"
RC_MISSING_REQUIRED_CLAIM_EVIDENCE = "missing_required_claim_evidence"
RC_CANDIDATE_LIMIT_REACHED = "candidate_limit_reached"
RC_NO_CANDIDATE_PASSED = "no_candidate_passed"

ALL_REASON_CODES = (
    RC_INVALID_CANDIDATE,
    RC_SOURCE_CONFIDENCE_BELOW_THRESHOLD,
    RC_PRIMARY_SOURCE_REQUIRED,
    RC_INSUFFICIENT_CORROBORATION,
    RC_OPPORTUNITY_SCORE_BELOW_THRESHOLD,
    RC_EXACT_TOPIC_DUPLICATE,
    RC_ENTITY_SATURATED,
    RC_ENTITY_DEVELOPMENT_SATURATED,
    RC_THEME_SATURATED,
    RC_SAME_DAY_REUSE,
    RC_ARTIFACT_REPETITION,
    RC_DEVELOPMENT_TYPE_NOT_ALLOWED,
    RC_ARTIFACT_NOT_ALLOWED,
    RC_PRACTICAL_VALUE_MISSING,
    RC_MISSING_REQUIRED_CLAIM_EVIDENCE,
    RC_CANDIDATE_LIMIT_REACHED,
    RC_NO_CANDIDATE_PASSED,
)

# Human-readable explanations keyed by reason code.
REASON_EXPLANATIONS = {
    RC_INVALID_CANDIDATE: "candidate is structurally invalid (missing title and URL)",
    RC_SOURCE_CONFIDENCE_BELOW_THRESHOLD: (
        "source-confidence score is below the slot's minimum threshold"),
    RC_PRIMARY_SOURCE_REQUIRED: "slot requires a primary source but none exists",
    RC_INSUFFICIENT_CORROBORATION: "slot requires independent corroboration that is missing",
    RC_OPPORTUNITY_SCORE_BELOW_THRESHOLD: (
        "opportunity score is below the slot's minimum threshold"),
    RC_EXACT_TOPIC_DUPLICATE: "exact topic was already published within the cooldown",
    RC_ENTITY_SATURATED: "entity share exceeds the saturation ceiling",
    RC_ENTITY_DEVELOPMENT_SATURATED: "entity+development combination is saturated",
    RC_THEME_SATURATED: "theme share exceeds the saturation ceiling",
    RC_SAME_DAY_REUSE: "same-day topic reuse is not permitted for this slot",
    RC_ARTIFACT_REPETITION: "same entity has been published through too many formats recently",
    RC_DEVELOPMENT_TYPE_NOT_ALLOWED: "candidate development type is not allowed for this slot",
    RC_ARTIFACT_NOT_ALLOWED: "candidate artifact type is incompatible with the slot",
    RC_PRACTICAL_VALUE_MISSING: (
        "slot requires practical developer value but none was detected"),
    RC_MISSING_REQUIRED_CLAIM_EVIDENCE: (
        "required source or claim metadata is missing and cannot safely degrade"),
    RC_CANDIDATE_LIMIT_REACHED: "maximum candidates evaluated without a passing result",
    RC_NO_CANDIDATE_PASSED: "no candidate passed all hard gates for this slot",
}

# ── Practical developer relevance signals ───────────────────────────────────

# Development types that are inherently actionable for developers.
PRACTICAL_DEVELOPMENT_TYPES = frozenset({
    "model_release",
    "product_release",
    "api_release",
    "repository_release",
    "security_issue",
    "compatibility_change",
    "deployment_availability",
    "pricing_change",
    "licensing_change",
    "documentation_update",
    "benchmark",
})

# Claim types that signal concrete developer impact.
PRACTICAL_CLAIM_TYPES = frozenset({
    "capability",
    "benchmark",
    "pricing",
    "availability",
    "security",
    "licensing",
})

# Metadata keys that signal practical value when present and truthy.
PRACTICAL_VALUE_SIGNAL_KEYS = frozenset({
    "has_code_change",
    "has_api_change",
    "has_deployment_impact",
    "has_compatibility_impact",
    "has_security_action",
    "has_migration_requirement",
    "has_pricing_implication",
    "has_developer_tooling_impact",
    "has_reproducible_benchmark",
    "has_architecture_implication",
})

# Artifact types that are inherently practical.
PRACTICAL_ARTIFACT_TYPES = frozenset({
    "takeaway_checklist",
    "migration_note",
    "compatibility_brief",
})


def assess_practical_value(candidate: Candidate) -> bool:
    """Deterministic structured signals — no LLM, no network.

    A candidate has practical developer value when ANY of these hold:
    - development type is inherently actionable
    - at least one claim is developer-impact type
    - metadata carries a practical-value signal key set to truthy
    - artifact type is inherently practical
    """
    if candidate.development_type in PRACTICAL_DEVELOPMENT_TYPES:
        return True
    if any(c.claim_type in PRACTICAL_CLAIM_TYPES for c in candidate.claims):
        return True
    metadata = candidate.metadata or {}
    if any(metadata.get(k) for k in PRACTICAL_VALUE_SIGNAL_KEYS):
        return True
    if candidate.artifact_type in PRACTICAL_ARTIFACT_TYPES:
        return True
    return False


# ── Slot policy ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SlotPolicy:
    """The admission-relevant subset of a slot's configuration."""
    slot_id: str
    allowed_artifacts: tuple[str, ...]
    allowed_development_types: tuple[str, ...]
    source_confidence_threshold: int
    opportunity_score_threshold: int | None
    opportunity_score_role: str  # "threshold_only" | "ranking_only" | "both"
    primary_source_required: bool
    minimum_independent_sources: int
    saturation_policy: str  # "reject_on_reject" | "warning_permitted" | "ignore"
    practical_value_required: bool
    maximum_candidates_to_evaluate: int
    backup_selection_policy: str  # "next_by_rank" | "best_by_confidence" | "none"
    skip_when_none_pass: bool
    # Additional from slots.yaml
    required_value_any_of: tuple[str, ...] = ()
    # Human-readable label for the decision record
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "label": self.label,
            "allowed_artifacts": list(self.allowed_artifacts),
            "allowed_development_types": list(self.allowed_development_types),
            "source_confidence_threshold": self.source_confidence_threshold,
            "opportunity_score_threshold": self.opportunity_score_threshold,
            "opportunity_score_role": self.opportunity_score_role,
            "primary_source_required": self.primary_source_required,
            "minimum_independent_sources": self.minimum_independent_sources,
            "saturation_policy": self.saturation_policy,
            "practical_value_required": self.practical_value_required,
            "maximum_candidates_to_evaluate": self.maximum_candidates_to_evaluate,
            "backup_selection_policy": self.backup_selection_policy,
            "skip_when_none_pass": self.skip_when_none_pass,
        }


class SlotPolicyError(ValueError):
    """Raised for any structural or policy problem in a slot's admission config.

    Carries every problem found so one edit cycle surfaces the full list.
    """

    def __init__(self, problems: list[str], slot_id: str = ""):
        self.problems = list(problems)
        self.slot_id = slot_id
        label = f" for slot {slot_id!r}" if slot_id else ""
        joined = "\n  - ".join(self.problems)
        super().__init__(
            f"{len(self.problems)} policy problem(s){label}:\n  - {joined}")


def build_slot_policy(slot: Slot, defaults: dict[str, Any] | None = None,
                      ) -> SlotPolicy:
    """Extract the admission-relevant policy from a Slot.

    Validation is strict: every problem is reported at once. A slot whose policy
    half-loads is worse than one that refuses to start.
    """
    defaults = defaults or {}
    admission = slot.admission or {}
    problems: list[str] = []

    # Source confidence threshold — the slot's own admission config wins.
    sc_threshold = admission.get("source_confidence_min")
    if sc_threshold is None:
        problems.append("source_confidence_min is required")
        sc_threshold = 0
    elif not isinstance(sc_threshold, (int, float)) or isinstance(sc_threshold, bool):
        problems.append("source_confidence_min must be a number")
        sc_threshold = int(sc_threshold)
    elif not 0 <= sc_threshold <= 100:
        problems.append(f"source_confidence_min={sc_threshold} outside 0-100")
        sc_threshold = int(sc_threshold)
    else:
        sc_threshold = int(sc_threshold)

    # Opportunity score: threshold, ranking, or both.
    opp_threshold = admission.get("opportunity_score_min")
    opp_role = str(admission.get("opportunity_score_role") or "ranking_only")
    if opp_role not in ("threshold_only", "ranking_only", "both"):
        problems.append(
            f"opportunity_score_role must be threshold_only|ranking_only|both, got {opp_role!r}")
    if opp_threshold is not None:
        if not isinstance(opp_threshold, (int, float)) or isinstance(opp_threshold, bool):
            problems.append("opportunity_score_min must be a number or null")
            opp_threshold = None
        elif not 0 <= opp_threshold <= 100:
            problems.append(f"opportunity_score_min={opp_threshold} outside 0-100")
        else:
            opp_threshold = int(opp_threshold)
            if opp_role == "ranking_only":
                problems.append(
                    "opportunity_score_min is set but role is ranking_only — "
                    "use 'both' or remove the threshold")

    # Allowed artifacts: collect from content types defined on the slot.
    allowed_artifacts: set[str] = set()
    allowed_formats: set[str] = set()
    for ct in slot.content_types.values():
        if ct.is_artifact:
            allowed_artifacts.add(ct.artifact)
        else:
            allowed_formats.update(ct.formats)

    # Allowed development types: everything by default unless restricted.
    raw_dev = admission.get("allowed_development_types")
    if raw_dev is not None:
        if not isinstance(raw_dev, list):
            problems.append("allowed_development_types must be a list or null")
            raw_dev = None
        else:
            unknown = [d for d in raw_dev if d not in DEVELOPMENT_TYPES]
            if unknown:
                problems.append(
                    f"unknown development type(s): {', '.join(unknown)}")
    dev_types: tuple[str, ...] = tuple(raw_dev) if raw_dev else tuple(DEVELOPMENT_TYPES)

    # Primary source required.
    primary_required = bool(admission.get("require_primary_source", True))
    evidence = admission.get("evidence") or {}
    if isinstance(evidence, dict):
        evidence_require = evidence.get("require_any_of") or []
    else:
        evidence_require = []
    for req in evidence_require:
        if isinstance(req, dict) and req.get("primary_source") is True:
            primary_required = True

    # Minimum independent sources.
    min_independent = 0
    for req in evidence_require:
        if isinstance(req, dict) and "independent_sources_min" in req:
            val = req["independent_sources_min"]
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                problems.append("independent_sources_min must be a non-negative integer")
            else:
                min_independent = max(min_independent, int(val))

    # Contradictory requirements: primary required + 0 independent + corroboration
    # required is a config smell but not strictly contradictory. Only flag when
    # independent_sources_min > 1 and primary is NOT required (makes corroboration
    # the sole evidence path, which is fragile).
    if min_independent > 1 and not primary_required:
        problems.append(
            "corroboration requires independent sources but primary source is not "
            "required — at least one of these must hold for corroboration to work")

    # Saturation policy.
    sat_policy = str(admission.get("saturation_policy") or "reject_on_reject")
    if sat_policy not in ("reject_on_reject", "warning_permitted", "ignore"):
        problems.append(
            f"saturation_policy must be reject_on_reject|warning_permitted|ignore, "
            f"got {sat_policy!r}")

    # Practical value required.
    practical_required = bool(admission.get("require_practical_developer_value", False))
    if slot.required_value_any_of:
        practical_required = True

    # Maximum candidates.
    raw_max = admission.get("maximum_candidates_to_evaluate")
    default_max = int(
        defaults.get("defaults", {}).get("fallback", {}).get("max_backup_candidates", 5)
        or 5)
    max_candidates = int(raw_max) if raw_max is not None else default_max
    if max_candidates < 1:
        problems.append("maximum_candidates_to_evaluate must be >= 1")

    # Backup selection policy.
    backup_policy = str(admission.get("backup_selection_policy") or "next_by_rank")
    if backup_policy not in ("next_by_rank", "best_by_confidence", "none"):
        problems.append(
            f"backup_selection_policy must be next_by_rank|best_by_confidence|none, "
            f"got {backup_policy!r}")

    # Skip when none pass.
    skip = bool(admission.get("skip_when_none_pass",
                              defaults.get("defaults", {}).get("fallback", {}).get(
                                  "on_no_candidate", "skip_slot") == "skip_slot"))

    # Force publication check — a slot must never be configured to force publication.
    if admission.get("force_publish") or admission.get("always_admit"):
        problems.append("slot must not force publication — evidence gates must hold")

    # Opportunity score overriding evidence gates.
    if admission.get("opportunity_overrides_evidence"):
        problems.append(
            "opportunity score must not override source confidence or saturation — "
            "this contradicts the hard-gate design")

    if problems:
        raise SlotPolicyError(problems, slot.slot_id)

    return SlotPolicy(
        slot_id=slot.slot_id,
        allowed_artifacts=tuple(sorted(allowed_artifacts)),
        allowed_development_types=dev_types,
        source_confidence_threshold=sc_threshold,
        opportunity_score_threshold=opp_threshold,
        opportunity_score_role=opp_role,
        primary_source_required=primary_required,
        minimum_independent_sources=min_independent,
        saturation_policy=sat_policy,
        practical_value_required=practical_required,
        maximum_candidates_to_evaluate=max_candidates,
        backup_selection_policy=backup_policy,
        skip_when_none_pass=skip,
        required_value_any_of=tuple(slot.required_value_any_of or ()),
        label=slot.label,
    )


# ── Per-candidate evaluation ────────────────────────────────────────────────

@dataclass(frozen=True)
class CandidateEvaluation:
    """The full pipeline result for one candidate against one slot."""
    candidate_id: str
    rank: int
    status: str  # admitted | rejected | warning | invalid_candidate
    reason_codes: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    opportunity_score: int | None = None
    source_confidence: int | None = None
    saturation_status: str = ""
    # Rich summaries for the decision record.
    source_confidence_summary: dict[str, Any] = field(default_factory=dict)
    saturation_summary: dict[str, Any] = field(default_factory=dict)
    policy_snapshot: dict[str, Any] = field(default_factory=dict)
    r4_material_downgrade: bool = False
    r4_downgrade_reason: str = ""
    # The enriched candidate and its relationship results, retained for recording.
    enriched_candidate: Candidate | None = None
    relationships: tuple[SourceRelationship, ...] = ()
    source_confidence_result: SourceConfidence | None = None
    saturation_result: SaturationResult | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "rank": self.rank,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "opportunity_score": self.opportunity_score,
            "source_confidence": self.source_confidence,
            "saturation_status": self.saturation_status,
            "source_confidence_summary": self.source_confidence_summary,
            "saturation_summary": self.saturation_summary,
            "policy_snapshot": self.policy_snapshot,
            "r4_material_downgrade": self.r4_material_downgrade,
            "r4_downgrade_reason": self.r4_downgrade_reason,
            "warnings": list(self.warnings),
        }


def _is_valid_candidate(candidate: Candidate) -> tuple[bool, str]:
    """Gate 1: structural validity."""
    if not candidate:
        return False, "candidate is None"
    if not candidate.title and not candidate.url:
        return False, "candidate has no title and no URL"
    return True, ""


def _count_independent_sources(candidate: Candidate) -> int:
    """Count independent non-first-party sources with evidence."""
    return sum(1 for s in candidate.sources
               if s.adds_independent_evidence
               and not s.is_first_party
               and not s.is_syndicated
               and not s.is_press_release)


def _saturation_status_to_reasons(sat: SaturationResult,
                                  ) -> tuple[str, ...]:
    """Map saturation rule outcomes to stable reason codes."""
    codes: list[str] = []
    for rule in sat.rules:
        if rule.status != STATUS_REJECT:
            continue
        if rule.rule_id == "R1":
            codes.append(RC_EXACT_TOPIC_DUPLICATE)
        elif rule.rule_id == "R3":
            codes.append(RC_ENTITY_SATURATED)
        elif rule.rule_id == "R4":
            codes.append(RC_ENTITY_DEVELOPMENT_SATURATED)
        elif rule.rule_id == "R5":
            codes.append(RC_THEME_SATURATED)
        elif rule.rule_id == "R6":
            codes.append(RC_ARTIFACT_REPETITION)
        elif rule.rule_id == "R2":
            codes.append(RC_SAME_DAY_REUSE)
    return tuple(codes)


def _r4_material_downgrade_eligible(
        candidate: Candidate,
        saturation_result: SaturationResult,
        material_types: frozenset[str],
) -> tuple[bool, str]:
    """Check whether R4 reject can be downgraded to warning at admission time.

    All five conditions must hold:
    1. canonical_topic_id differs from prior publications
    2. candidate represents a material development
    3. concrete evidence references are present
    4. not merely a reformatted version of previous coverage
    5. exact-topic R1 is clear (never weakened)
    """
    # Condition 5: R1 must be clear. If R1 fires (reject or warning), no downgrade.
    r1_rules = [r for r in saturation_result.rules if r.rule_id == "R1"]
    r1_status = r1_rules[0].status if r1_rules else STATUS_CLEAR
    if r1_status != STATUS_CLEAR:
        return False, "R1 is not clear"

    # Is there an R4 reject to downgrade?
    r4_rules = [r for r in saturation_result.rules if r.rule_id == "R4"]
    if not r4_rules or r4_rules[0].status != STATUS_REJECT:
        return False, "R4 is not rejected"

    # Condition 2: material development type.
    if candidate.development_type not in material_types:
        return False, "development type is not material"

    # Condition 1: canonical_topic_id differs from prior publications.
    # We check this by verifying the candidate's topic ID is present (non-empty)
    # and that R1 is clear (which already means the topic is NOT in the cooldown).
    if not candidate.canonical_topic_id:
        return False, "no canonical topic id"
    # R1 being clear already means this topic is not in the cooldown window,
    # which means it differs from prior publications. So conditions 1 and 5
    # are jointly satisfied by R1=clear.

    # Condition 3: concrete evidence references.
    has_evidence = bool(candidate.metadata.get("evidence_references"))
    if not has_evidence:
        # Also check if the candidate has a primary source with exact coverage.
        has_evidence = any(
            s.is_primary and s.covers_exact_development for s in candidate.sources
        )
    if not has_evidence:
        return False, "no concrete evidence references"

    # Condition 4: not merely a reformatted version.
    # Check by requiring a different artifact type than recent R4-covered ones,
    # or by having new evidence that distinguishes it.
    prior_artifact = candidate.metadata.get("prior_artifact_type")
    if prior_artifact and candidate.artifact_type == prior_artifact:
        # Same format, same topic — just a reformatted version.
        return False, "appears to be a reformatted version of previous coverage"

    return True, "R4 material-development downgrade applied"


def evaluate_candidate(
        candidate: Candidate,
        *,
        rank: int,
        policy: SlotPolicy,
        saturation_config: SaturationConfig,
        history: HistoryView,
        scoring_config: ScoringConfig | None = None,
        relationship_config: RelationshipConfig | None = None,
        material_types: frozenset[str] = frozenset(),
        now: dt.datetime | None = None,
) -> CandidateEvaluation:
    """Apply the full pipeline to one candidate. Returns the evaluation result.

    This is the pure function — no writes, no recordings. Each gate is applied
    in order; gates that do not depend on later ones can short-circuit, but
    all applicable gates are evaluated so the result carries every reason.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now = now.astimezone(dt.timezone.utc)

    reason_codes: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []

    # ── Gate 1: structural validity (checked BEFORE any attribute access) ──
    valid, validity_reason = _is_valid_candidate(candidate)
    if not valid:
        reason_codes.append(RC_INVALID_CANDIDATE)
        reasons.append(validity_reason)
        return CandidateEvaluation(
            candidate_id="unknown",
            rank=rank,
            status=INVALID_CANDIDATE,
            reason_codes=tuple(reason_codes),
            reasons=tuple(reasons),
            opportunity_score=None,
            policy_snapshot=policy.to_dict(),
            warnings=tuple(warnings),
        )

    opp_score = candidate.opportunity_score
    sc_score: int | None = None
    sat_status = STATUS_CLEAR
    r4_downgrade = False
    r4_downgrade_reason = ""
    sc_result: SourceConfidence | None = None
    sat_result: SaturationResult | None = None
    relationships: list[SourceRelationship] = []
    enriched = candidate

    # ── Gate 6: development type allowed ──
    if candidate.development_type not in policy.allowed_development_types:
        reason_codes.append(RC_DEVELOPMENT_TYPE_NOT_ALLOWED)
        reasons.append(REASON_EXPLANATIONS[RC_DEVELOPMENT_TYPE_NOT_ALLOWED])

    # ── Gate 7: artifact type allowed ──
    if policy.allowed_artifacts and candidate.artifact_type not in policy.allowed_artifacts:
        # Only check if artifacts are explicitly restricted.
        # If allowed_artifacts is empty, all are allowed.
        if candidate.artifact_type:
            reason_codes.append(RC_ARTIFACT_NOT_ALLOWED)
            reasons.append(REASON_EXPLANATIONS[RC_ARTIFACT_NOT_ALLOWED])

    # ── Steps 2-4: relationships, enrichment, source confidence ──
    try:
        relationships = detect_relationships(
            candidate.sources,
            subject_org=candidate.subject_org,
            config=relationship_config,
            metadata=candidate.metadata,
        )
        enriched = apply_relationships(candidate, relationships)
        sc_result = score_source_confidence(enriched, scoring_config, now=now)
        sc_score = sc_result.score
    except Exception as exc:  # noqa: BLE001 — scoring can fail on bad input
        warnings.append(f"scoring error: {exc}")
        enriched = candidate

    # ── Gate 2: source confidence threshold ──
    if sc_score is not None and sc_score < policy.source_confidence_threshold:
        reason_codes.append(RC_SOURCE_CONFIDENCE_BELOW_THRESHOLD)
        reasons.append(
            f"source confidence {sc_score} below threshold "
            f"{policy.source_confidence_threshold}")

    # ── Gate 4: primary source required ──
    if policy.primary_source_required and enriched.primary_source is None:
        reason_codes.append(RC_PRIMARY_SOURCE_REQUIRED)
        reasons.append(REASON_EXPLANATIONS[RC_PRIMARY_SOURCE_REQUIRED])

    # ── Gate 5: minimum independent sources ──
    if policy.minimum_independent_sources > 0:
        independent = _count_independent_sources(enriched)
        if independent < policy.minimum_independent_sources:
            reason_codes.append(RC_INSUFFICIENT_CORROBORATION)
            reasons.append(
                f"insufficient corroboration: {independent} independent source(s), "
                f"need {policy.minimum_independent_sources}")

    # ── Step 5: saturation evaluation ──
    try:
        sat_result = evaluate_saturation(
            enriched,
            history=history,
            config=saturation_config,
            now=now,
        )
        sat_status = sat_result.status
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"saturation error: {exc}")
        sat_result = None

    # ── Gate 3: saturation rejection ──
    if sat_status == STATUS_REJECT and policy.saturation_policy != "ignore":
        # Check R4 material-development downgrade.
        r4_eligible, r4_reason = _r4_material_downgrade_eligible(
            enriched, sat_result, material_types) if sat_result else (False, "")
        if r4_eligible:
            r4_downgrade = True
            r4_downgrade_reason = r4_reason
            # R4 is downgraded to warning; check if any OTHER rule still rejects.
            other_rejections = [
                r for r in (sat_result.rules if sat_result else ())
                if r.rule_id != "R4" and r.status == STATUS_REJECT
            ]
            if other_rejections:
                sat_reasons = _saturation_status_to_reasons(sat_result)
                reason_codes.extend(sat_reasons)
                for code in sat_reasons:
                    reasons.append(REASON_EXPLANATIONS.get(code, code))
        else:
            # All saturation rejections stand.
            sat_reasons = _saturation_status_to_reasons(sat_result)
            reason_codes.extend(sat_reasons)
            for code in sat_reasons:
                reasons.append(REASON_EXPLANATIONS.get(code, code))

    # ── Gate 9: exact duplicate — never bypassed ──
    if sat_result:
        r1_rules = [r for r in sat_result.rules if r.rule_id == "R1"]
        if r1_rules and r1_rules[0].status == STATUS_REJECT:
            if RC_EXACT_TOPIC_DUPLICATE not in reason_codes:
                reason_codes.append(RC_EXACT_TOPIC_DUPLICATE)
                reasons.append(REASON_EXPLANATIONS[RC_EXACT_TOPIC_DUPLICATE])

    # ── Gate 8: practical developer relevance ──
    if policy.practical_value_required and not assess_practical_value(enriched):
        reason_codes.append(RC_PRACTICAL_VALUE_MISSING)
        reasons.append(REASON_EXPLANATIONS[RC_PRACTICAL_VALUE_MISSING])

    # ── Gate 10: required claim evidence ──
    if policy.required_value_any_of:
        has_required = False
        metadata = enriched.metadata or {}
        for key in policy.required_value_any_of:
            if metadata.get(key):
                has_required = True
                break
        if not has_required:
            # Also check claims for relevant types.
            has_required = any(
                c.claim_type in PRACTICAL_CLAIM_TYPES for c in enriched.claims
            )
        if not has_required and policy.practical_value_required:
            # Only add this reason if it's not already covered by practical_value_missing
            if RC_PRACTICAL_VALUE_MISSING not in reason_codes:
                reason_codes.append(RC_MISSING_REQUIRED_CLAIM_EVIDENCE)
                reasons.append(REASON_EXPLANATIONS[RC_MISSING_REQUIRED_CLAIM_EVIDENCE])

    # ── Opportunity score gate (if role includes threshold) ──
    if (policy.opportunity_score_role in ("threshold_only", "both")
            and policy.opportunity_score_threshold is not None
            and opp_score is not None
            and opp_score < policy.opportunity_score_threshold):
        reason_codes.append(RC_OPPORTUNITY_SCORE_BELOW_THRESHOLD)
        reasons.append(REASON_EXPLANATIONS[RC_OPPORTUNITY_SCORE_BELOW_THRESHOLD])

    # ── Determine final status ──
    deduped_codes = tuple(dict.fromkeys(reason_codes))
    deduped_reasons = tuple(dict.fromkeys(reasons))

    if RC_INVALID_CANDIDATE in deduped_codes:
        status = INVALID_CANDIDATE
    elif deduped_codes:
        # Check if saturation policy permits warning (R4 downgrade case).
        if (r4_downgrade
                and policy.saturation_policy == "warning_permitted"
                and all(c in (RC_ENTITY_DEVELOPMENT_SATURATED,
                              RC_ENTITY_SATURATED,
                              RC_THEME_SATURATED,
                              RC_ARTIFACT_REPETITION)
                        for c in deduped_codes)):
            status = WARNING
        else:
            status = REJECTED
    else:
        status = ADMITTED

    # Source confidence summary for the record.
    sc_summary = sc_result.to_dict() if sc_result else {}
    sat_summary = sat_result.to_dict() if sat_result else {}

    return CandidateEvaluation(
        candidate_id=enriched.candidate_id or "unknown",
        rank=rank,
        status=status,
        reason_codes=deduped_codes,
        reasons=deduped_reasons,
        opportunity_score=opp_score,
        source_confidence=sc_score,
        saturation_status=sat_status,
        source_confidence_summary=sc_summary,
        saturation_summary=sat_summary,
        policy_snapshot=policy.to_dict(),
        r4_material_downgrade=r4_downgrade,
        r4_downgrade_reason=r4_downgrade_reason,
        enriched_candidate=enriched,
        relationships=tuple(relationships),
        source_confidence_result=sc_result,
        saturation_result=sat_result,
        warnings=tuple(warnings),
    )


# ── Slot-level admission ────────────────────────────────────────────────────

@dataclass(frozen=True)
class AdmissionResult:
    """The full admission decision for one slot."""
    slot_id: str
    status: str  # admitted | rejected | skipped_no_candidate
    selected_candidate_id: str = ""
    evaluated_candidates: tuple[CandidateEvaluation, ...] = ()
    selected_policy_snapshot: dict[str, Any] = field(default_factory=dict)
    decision_time: str = ""
    mode: str = "shadow"
    version: int = RESULT_VERSION
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "status": self.status,
            "selected_candidate_id": self.selected_candidate_id,
            "evaluated_candidates": [e.to_dict() for e in self.evaluated_candidates],
            "selected_policy_snapshot": self.selected_policy_snapshot,
            "decision_time": self.decision_time,
            "mode": self.mode,
            "version": self.version,
            "warnings": list(self.warnings),
        }


def admit_to_slot(
        slot: Slot,
        candidates: Sequence[Candidate],
        *,
        history: HistoryView,
        saturation_config: SaturationConfig,
        slot_config: SlotConfig | None = None,
        scoring_config: ScoringConfig | None = None,
        relationship_config: RelationshipConfig | None = None,
        material_types: frozenset[str] = frozenset(),
        now: dt.datetime | None = None,
) -> AdmissionResult:
    """Pure admission: evaluate ranked candidates against one slot.

    Returns an AdmissionResult without writing anything. This is the function
    tests exercise directly; the recording layer wraps it.

    Candidate evaluation order:
    1. Receive ranked candidates (rank derived from opportunity_score descending,
       or the input order if scores are absent).
    2. For each: normalize → relationships → confidence → saturation → slot policy.
    3. Admit the first candidate that passes all hard gates.
    4. Continue to ranked backups when one fails.
    5. Stop after maximum_candidates_to_evaluate.
    6. Skip the slot when no candidate passes.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now = now.astimezone(dt.timezone.utc)

    defaults = slot_config.defaults if slot_config else {}
    policy = build_slot_policy(slot, defaults)

    # Rank candidates: by opportunity_score descending, stable by input order.
    indexed = list(enumerate(candidates))
    indexed.sort(
        key=lambda pair: (
            -(pair[1].opportunity_score or 0),
            pair[0],
        ))

    evaluated: list[CandidateEvaluation] = []
    selected_id = ""
    warnings: list[str] = []
    limit_reached = False

    for rank_0, (orig_idx, candidate) in enumerate(indexed):
        if rank_0 >= policy.maximum_candidates_to_evaluate:
            limit_reached = True
            break

        evaluation = evaluate_candidate(
            candidate,
            rank=rank_0 + 1,
            policy=policy,
            saturation_config=saturation_config,
            history=history,
            scoring_config=scoring_config,
            relationship_config=relationship_config,
            material_types=material_types,
            now=now,
        )
        evaluated.append(evaluation)

        if evaluation.status == ADMITTED:
            selected_id = evaluation.candidate_id
            break
        elif evaluation.status == WARNING:
            # Warning is still admitted if all blocking requirements pass.
            selected_id = evaluation.candidate_id
            break

    if limit_reached and not selected_id:
        # Record that we stopped evaluating.
        warnings.append("maximum candidates evaluated without a passing result")

    # Determine slot-level status.
    if not candidates:
        slot_status = SKIPPED_NO_CANDIDATE
    elif selected_id:
        slot_status = ADMITTED
    elif policy.skip_when_none_pass:
        slot_status = SKIPPED_NO_CANDIDATE
    else:
        slot_status = REJECTED

    return AdmissionResult(
        slot_id=slot.slot_id,
        status=slot_status,
        selected_candidate_id=selected_id,
        evaluated_candidates=tuple(evaluated),
        selected_policy_snapshot=policy.to_dict(),
        decision_time=now.isoformat(),
        mode="shadow",
        version=RESULT_VERSION,
        warnings=tuple(warnings),
    )


# ── Shadow-mode decision recording ──────────────────────────────────────────

def record_shadow_decision(result: AdmissionResult,
                           log_path: Path | None = None) -> None:
    """Write a shadow-mode decision record to the ContentDecision ledger.

    Requirements:
    - mode=shadow (always, while EDITORIAL_SLOTS_ENABLED=false)
    - no publication status
    - no mutation of live publication history
    - no influence on saturation calculations
    - policy snapshot included
    - source-confidence and saturation summaries included
    - every rejection reason preserved
    """
    from agent.content_decisions import ContentDecision, record as cd_record

    mode = "shadow" if not editorial_slots_enabled() else "live"

    for evaluation in result.evaluated_candidates:
        if evaluation.status == ADMITTED:
            decision = "accepted"
            reason_code = "accepted"
            reason = ""
        elif evaluation.status == INVALID_CANDIDATE:
            decision = "rejected"
            # ContentDecision's reason_code is a closed Phase 0 vocabulary.
            # Stage 4 reason codes live in metadata.all_reason_codes; the
            # ContentDecision field is left empty for shadow records.
            reason_code = ""
            reason = "; ".join(evaluation.reasons) if evaluation.reasons else "structurally invalid"
        elif evaluation.status in (REJECTED, WARNING):
            decision = "rejected" if evaluation.status == REJECTED else "accepted"
            reason_code = ""
            reason = "; ".join(evaluation.reasons) if evaluation.reasons else ""
        else:
            continue

        metadata: dict[str, Any] = {
            "mode": mode,
            "slot_id": result.slot_id,
            "rank": evaluation.rank,
            "opportunity_score": evaluation.opportunity_score,
            "source_confidence_summary": evaluation.source_confidence_summary,
            "saturation_summary": evaluation.saturation_summary,
            "policy_snapshot": evaluation.policy_snapshot,
            "all_reason_codes": list(evaluation.reason_codes),
            "r4_material_downgrade": evaluation.r4_material_downgrade,
            "r4_downgrade_reason": evaluation.r4_downgrade_reason,
            "warnings": list(evaluation.warnings),
            "enrichment": {
                "source_count": len(evaluation.enriched_candidate.sources)
                if evaluation.enriched_candidate else 0,
                "claim_count": len(evaluation.enriched_candidate.claims)
                if evaluation.enriched_candidate else 0,
                "development_type": evaluation.enriched_candidate.development_type
                if evaluation.enriched_candidate else "",
                "artifact_type": evaluation.enriched_candidate.artifact_type
                if evaluation.enriched_candidate else "",
                "canonical_topic_id": evaluation.enriched_candidate.canonical_topic_id
                if evaluation.enriched_candidate else "",
            },
        }

        cd = ContentDecision(
            stage="topic_admission",
            decision=decision,
            job_id=f"admission:{result.slot_id}:{evaluation.candidate_id}",
            title=evaluation.enriched_candidate.title if evaluation.enriched_candidate else "",
            slug="",
            reason_code=reason_code,
            reason=reason,
            source_confidence=evaluation.source_confidence,
            sources=[s.url for s in (evaluation.enriched_candidate.sources or ())]
            if evaluation.enriched_candidate else [],
            metadata=metadata,
        )
        cd_record(cd)


def evaluate_and_record(
        slot: Slot,
        candidates: Sequence[Candidate],
        *,
        history: HistoryView,
        saturation_config: SaturationConfig,
        slot_config: SlotConfig | None = None,
        scoring_config: ScoringConfig | None = None,
        relationship_config: RelationshipConfig | None = None,
        material_types: frozenset[str] = frozenset(),
        now: dt.datetime | None = None,
) -> AdmissionResult:
    """Evaluate + record shadow decisions. The production entry point.

    While EDITORIAL_SLOTS_ENABLED=false, records are always shadow mode.
    The pure admission function (admit_to_slot) remains separately callable.
    """
    result = admit_to_slot(
        slot, candidates,
        history=history,
        saturation_config=saturation_config,
        slot_config=slot_config,
        scoring_config=scoring_config,
        relationship_config=relationship_config,
        material_types=material_types,
        now=now,
    )
    record_shadow_decision(result)
    return result
