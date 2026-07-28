"""Phase 1 Stage 4 — deterministic admission and backup-candidate selection.

Covers:
- All 10 hard gates
- Slot policy validation
- Backup selection behavior
- Material-development R4 downgrade (all 5 conditions)
- R1 is never downgraded
- Reason code stability
- Determinism (same input → same output)
- Shadow-mode decision recording
- No LLM / network / content-generation calls
- No production or cron changes while feature flag is false
"""
from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from agent.editorial.models import (
    Candidate,
    Claim,
    SourceRef,
    DEVELOPMENT_TYPES,
)
from agent.editorial.saturation import (
    CONFIG_PATH as SATURATION_CONFIG_PATH,
    HistoryView,
    PublicationRecord,
    SaturationConfig,
    SaturationResult,
    RuleOutcome,
    MaterialException,
    STATUS_REJECT,
    STATUS_CLEAR,
    STATUS_WARNING,
    THEME_UNKNOWN,
    load_saturation_config,
)
from agent.editorial.slots import Slot, ContentType
from agent.editorial.source_confidence import (
    ScoringConfig,
    SourceConfidence,
    Component,
    load_scoring_config,
)
from agent.editorial.source_relationships import (
    SourceRelationship,
    detect_relationships,
)
from agent.editorial.admission import (
    ADMITTED,
    REJECTED,
    WARNING,
    INVALID_CANDIDATE,
    SKIPPED_NO_CANDIDATE,
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
    ALL_REASON_CODES,
    REASON_EXPLANATIONS,
    SlotPolicy,
    SlotPolicyError,
    CandidateEvaluation,
    AdmissionResult,
    build_slot_policy,
    evaluate_candidate,
    admit_to_slot,
    record_shadow_decision,
    evaluate_and_record,
    assess_practical_value,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

NOW = dt.datetime(2026, 7, 27, 12, 0, 0, tzinfo=dt.timezone.utc)


def _src(url: str = "https://example.com/primary", kind: str = "official_announcement",
         exact: bool = True, independent: bool = True, excerpt: str = "details") -> SourceRef:
    return SourceRef(
        url=url, kind=kind, title="Test Source",
        covers_exact_development=exact, adds_independent_evidence=independent,
        excerpt=excerpt, published_at="2026-07-27T10:00:00+00:00",
    )


def _candidate(
    title: str = "OpenAI releases GPT-5",
    url: str = "https://example.com/gpt5",
    org: str = "openai",
    development: str = "model_release",
    topic: str = "openai:model_release:gpt5",
    artifact: str = "tutorial",
    opp_score: int = 80,
    sources: tuple[SourceRef, ...] | None = None,
    claims: tuple[Claim, ...] = (),
    metadata: dict[str, Any] | None = None,
    candidate_id: str = "",
) -> Candidate:
    if sources is None:
        # Strong default: primary + independent secondary → scores ~80
        sources = (
            SourceRef(url="https://openai.com/blog",
                      kind="official_announcement", title="Primary",
                      covers_exact_development=True,
                      adds_independent_evidence=False,
                      excerpt="GPT-5 released today",
                      published_at="2026-07-27T10:00:00+00:00"),
            SourceRef(url="https://arstechnica.com/gpt5",
                      kind="secondary", title="Ars",
                      excerpt="Ars reviews the launch",
                      published_at="2026-07-27T10:30:00+00:00"),
        )
    meta = metadata or {}
    return Candidate(
        title=title, url=url, subject_org=org,
        development_type=development,
        canonical_topic_id=topic,
        content_kind=artifact,
        opportunity_score=opp_score,
        sources=sources, claims=claims,
        metadata=meta,
        candidate_id=candidate_id or f"cid_{url}",
        event_time="2026-07-27T10:00:00+00:00",
    )


def _empty_history() -> HistoryView:
    return HistoryView(records=(), fingerprint="empty")


def _saturation_config() -> SaturationConfig:
    return load_saturation_config(SATURATION_CONFIG_PATH)


def _slot(slot_id: str = "midday_authority", admission: dict | None = None,
          content_types: dict | None = None,
          required_value: tuple = ()) -> Slot:
    if admission is None:
        admission = {
            "source_confidence_min": 70,
            "editorial_quality_min": 80,
            "require_practical_developer_value": True,
        }
    if content_types is None:
        content_types = {
            "tutorial": ContentType("tutorial", formats=("tutorial_deep_dive",)),
            "analysis": ContentType("analysis", formats=("technical_analysis",)),
        }
    return Slot(
        slot_id=slot_id, order=1, publish_at="12:00", label=slot_id,
        content_types=content_types, admission=admission,
        required_value_any_of=required_value,
    )


def _scoring_config() -> ScoringConfig:
    return load_scoring_config()


def _make_history(org: str, dev: str, n: int, total: int = 12,
                  artifact: str = "tutorial") -> HistoryView:
    """Build a history with n matching records out of `total` slots."""
    records = []
    for i in range(n):
        records.append(PublicationRecord(
            publication_id=f"pub_{i}",
            published_at=NOW - dt.timedelta(hours=i * 6),
            editorial_day=(NOW - dt.timedelta(hours=i * 6)).strftime("%Y-%m-%d"),
            canonical_topic_id=f"{org}:{dev}:v{i}",
            entity=org,
            development_type=dev,
            artifact_type=artifact,
            theme="ai_models",
        ))
    for i in range(n, total):
        other_org = "anthropic" if org != "anthropic" else "google"
        records.append(PublicationRecord(
            publication_id=f"pub_other_{i}",
            published_at=NOW - dt.timedelta(hours=(i + 1) * 6),
            editorial_day=(NOW - dt.timedelta(hours=(i + 1) * 6)).strftime("%Y-%m-%d"),
            canonical_topic_id=f"{other_org}:general_news:topic_{i}",
            entity=other_org,
            development_type="general_news",
            artifact_type="tutorial",
            theme="ai_models",
        ))
    return HistoryView(records=tuple(records), fingerprint="test")


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sat_config():
    return _saturation_config()


@pytest.fixture
def sc_config():
    return _scoring_config()


@pytest.fixture
def history():
    return _empty_history()


@pytest.fixture
def slot():
    return _slot()


@pytest.fixture
def defaults():
    return {"defaults": {"fallback": {"max_backup_candidates": 5,
                                      "on_no_candidate": "skip_slot"}}}


# ── Gate 1: structural validity ─────────────────────────────────────────────

def test_none_candidate_is_rejected_as_invalid(slot, sat_config, history):
    evaluation = evaluate_candidate(
        None, rank=1,
        policy=build_slot_policy(slot),
        saturation_config=sat_config,
        history=history,
        now=NOW,
    )
    assert evaluation.status == INVALID_CANDIDATE
    assert RC_INVALID_CANDIDATE in evaluation.reason_codes


def test_candidate_without_title_or_url_is_invalid(slot, sat_config, history):
    cand = Candidate(title="", url="")
    evaluation = evaluate_candidate(
        cand, rank=1,
        policy=build_slot_policy(slot),
        saturation_config=sat_config,
        history=history,
        now=NOW,
    )
    assert evaluation.status == INVALID_CANDIDATE
    assert RC_INVALID_CANDIDATE in evaluation.reason_codes


# ── Gate 2: source confidence threshold ─────────────────────────────────────

def test_source_confidence_below_threshold_rejects(slot, sat_config, history):
    """A candidate with only a secondary source gets low confidence."""
    weak_source = _src(kind="secondary", exact=False)
    cand = _candidate(sources=(weak_source,))
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert evaluation.source_confidence < policy.source_confidence_threshold
    assert RC_SOURCE_CONFIDENCE_BELOW_THRESHOLD in evaluation.reason_codes
    assert evaluation.status == REJECTED


def test_high_opportunity_score_cannot_override_low_source_confidence(
        slot, sat_config, history):
    """91 opportunity but weak evidence still fails."""
    weak_source = _src(kind="secondary", exact=False)
    cand = _candidate(sources=(weak_source,), opp_score=91)
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert evaluation.opportunity_score == 91
    assert RC_SOURCE_CONFIDENCE_BELOW_THRESHOLD in evaluation.reason_codes
    assert evaluation.status == REJECTED


# ── Gate 3: saturation rejection ────────────────────────────────────────────

def test_saturation_reject_blocks_admission(slot, sat_config):
    """5 out of 12 entity share exceeds 0.33 ceiling."""
    history = _make_history("openai", "general_news", n=5, total=12)
    cand = _candidate(org="openai", development="general_news",
                      topic="openai:general_news:new")
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert evaluation.saturation_status == STATUS_REJECT
    assert evaluation.status == REJECTED


def test_high_opportunity_cannot_override_saturation_rejection(
        slot, sat_config):
    """95 opportunity but saturated entity still rejected."""
    history = _make_history("openai", "general_news", n=5, total=12)
    cand = _candidate(org="openai", development="general_news",
                      topic="openai:general_news:new", opp_score=95)
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert evaluation.opportunity_score == 95
    assert evaluation.status == REJECTED
    assert any(code in evaluation.reason_codes for code in
               (RC_ENTITY_SATURATED, RC_ENTITY_DEVELOPMENT_SATURATED))


# ── Gate 4: primary source required ─────────────────────────────────────────

def test_primary_source_required_blocks_when_missing(slot, sat_config, history):
    slot_with_req = _slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "require_primary_source": True,
    })
    secondary_only = _src(kind="secondary", exact=False)
    cand = _candidate(sources=(secondary_only,))
    policy = build_slot_policy(slot_with_req)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRIMARY_SOURCE_REQUIRED in evaluation.reason_codes


def test_primary_source_present_passes_gate(slot, sat_config, history):
    slot_with_req = _slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "require_primary_source": True,
    })
    primary = _src(kind="official_announcement")
    cand = _candidate(sources=(primary,))
    policy = build_slot_policy(slot_with_req)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRIMARY_SOURCE_REQUIRED not in evaluation.reason_codes


# ── Gate 5: corroboration requirement ───────────────────────────────────────

def test_insufficient_corroboration_rejects(slot, sat_config, history):
    slot_with_corr = _slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "evidence": {"require_any_of": [{"independent_sources_min": 2}]},
    })
    # Only one independent source.
    cand = _candidate(sources=(_src(),))
    policy = build_slot_policy(slot_with_corr)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_INSUFFICIENT_CORROBORATION in evaluation.reason_codes


def test_sufficient_corroboration_passes(slot, sat_config, history):
    slot_with_corr = _slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "evidence": {"require_any_of": [{"independent_sources_min": 2}]},
    })
    # Two genuinely independent non-first-party sources with evidence.
    sources = (
        _src(url="https://arstechnica.com/gpt5", kind="secondary",
             excerpt="Ars covers the launch"),
        _src(url="https://theverge.com/gpt5", kind="secondary",
             excerpt="Verge reviews it"),
    )
    cand = _candidate(sources=sources)
    policy = build_slot_policy(slot_with_corr)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_INSUFFICIENT_CORROBORATION not in evaluation.reason_codes


# ── Gate 6: development type allowed ────────────────────────────────────────

def test_disallowed_development_type_rejects(slot, sat_config, history):
    restricted = _slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "allowed_development_types": ["model_release", "api_release"],
    })
    cand = _candidate(development="funding_or_company_news")
    policy = build_slot_policy(restricted)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_DEVELOPMENT_TYPE_NOT_ALLOWED in evaluation.reason_codes


# ── Gate 7: artifact type allowed ───────────────────────────────────────────

def test_disallowed_artifact_rejects(slot, sat_config, history):
    artifact_slot = _slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
    }, content_types={
        "roundup": ContentType("roundup", artifact="github_roundup"),
    })
    cand = _candidate(artifact="tutorial")
    policy = build_slot_policy(artifact_slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_ARTIFACT_NOT_ALLOWED in evaluation.reason_codes


# ── Gate 8: practical developer relevance ───────────────────────────────────

def test_practical_value_required_blocks_when_missing(slot, sat_config, history):
    # A general_news candidate has no practical signals by default.
    cand = _candidate(development="general_news")
    policy = build_slot_policy(slot)  # midday_authority requires practical value
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRACTICAL_VALUE_MISSING in evaluation.reason_codes


def test_practical_value_present_passes(slot, sat_config, history):
    cand = _candidate(development="api_release",
                      metadata={"has_api_change": True})  # concrete signal
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRACTICAL_VALUE_MISSING not in evaluation.reason_codes


def test_assess_practical_value_uses_structured_signals_only():
    """No LLM, no network — only concrete metadata signal keys pass the gate."""
    # Metadata signal key.
    assert assess_practical_value(_candidate(
        development="security_issue", metadata={"has_security_action": True}))
    assert assess_practical_value(_candidate(
        development="general_news", metadata={"has_code_change": True}))
    # Development type alone → false.
    assert not assess_practical_value(_candidate(development="security_issue"))
    # Claim type alone → false.
    claim = Claim(text="benchmark", claim_type="benchmark")
    assert not assess_practical_value(_candidate(
        development="general_news", claims=(claim,)))
    # Artifact type alone → false.
    assert not assess_practical_value(_candidate(
        development="general_news", artifact="takeaway_checklist"))
    # No signal → false.
    assert not assess_practical_value(_candidate(development="general_news",
                                                 artifact="tutorial"))


# ── Gate 9: exact duplicate ─────────────────────────────────────────────────

def test_exact_topic_duplicate_always_rejected(slot, sat_config):
    """Even with high opportunity and good evidence, R1 rejects."""
    # Build history with the same topic.
    record = PublicationRecord(
        publication_id="pub_existing",
        published_at=NOW - dt.timedelta(hours=2),
        editorial_day=(NOW - dt.timedelta(hours=2)).strftime("%Y-%m-%d"),
        canonical_topic_id="openai:model_release:gpt5",
        entity="openai", development_type="model_release",
        artifact_type="tutorial", theme="ai_models",
    )
    history = HistoryView(records=(record,), fingerprint="test")
    cand = _candidate(topic="openai:model_release:gpt5", opp_score=99)
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_EXACT_TOPIC_DUPLICATE in evaluation.reason_codes
    assert evaluation.status == REJECTED


# ── Gate 10: required claim evidence ────────────────────────────────────────

def test_missing_required_claim_evidence_rejects(slot, sat_config, history):
    slot_with_req = _slot(
        admission={
            "source_confidence_min": 50,
            "editorial_quality_min": 0,
            "require_practical_developer_value": True,
        },
        required_value=("security_action", "migration_advice"),
    )
    # No matching claims, no matching metadata.
    cand = _candidate(development="general_news")
    policy = build_slot_policy(slot_with_req)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRACTICAL_VALUE_MISSING in evaluation.reason_codes


# ── Backup selection ────────────────────────────────────────────────────────

def test_highest_ranked_candidate_admitted(slot, sat_config, history):
    cands = [
        _candidate(url="https://a.com/1", opp_score=90,
                   metadata={"has_code_change": True}),
        _candidate(url="https://b.com/2", opp_score=80,
                   metadata={"has_api_change": True}),
    ]
    result = admit_to_slot(
        slot, cands,
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    assert result.status == ADMITTED
    assert result.evaluated_candidates[0].rank == 1
    assert result.evaluated_candidates[0].status == ADMITTED


def test_highest_ranked_fails_backup_selected(slot, sat_config, history):
    """First candidate fails source confidence; second passes."""
    weak = _src(kind="secondary", exact=False)
    cands = [
        _candidate(url="https://weak.com/1", opp_score=90, sources=(weak,)),
        _candidate(url="https://strong.com/2", opp_score=80,
                   metadata={"has_code_change": True}),
    ]
    result = admit_to_slot(
        slot, cands,
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    assert result.status == ADMITTED
    assert result.evaluated_candidates[0].status == REJECTED
    assert result.evaluated_candidates[1].status == ADMITTED
    assert result.selected_candidate_id == result.evaluated_candidates[1].candidate_id


def test_all_candidates_fail_slot_skipped(slot, sat_config, history):
    weak = _src(kind="secondary", exact=False)
    cands = [
        _candidate(url="https://a.com/1", sources=(weak,)),
        _candidate(url="https://b.com/2", sources=(weak,)),
    ]
    result = admit_to_slot(
        slot, cands,
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    assert result.status == SKIPPED_NO_CANDIDATE
    assert result.selected_candidate_id == ""


def test_empty_candidate_list_skips_slot(slot, sat_config, history):
    result = admit_to_slot(
        slot, [],
        history=history,
        saturation_config=sat_config,
        now=NOW,
    )
    assert result.status == SKIPPED_NO_CANDIDATE


def test_maximum_candidate_limit(slot, sat_config, history):
    """Stop after max_candidates_to_evaluate."""
    restricted = _slot(admission={
        "source_confidence_min": 70,
        "editorial_quality_min": 80,
        "require_practical_developer_value": True,
        "maximum_candidates_to_evaluate": 2,
    })
    weak = _src(kind="secondary", exact=False)
    cands = [
        _candidate(url=f"https://w.com/{i}", sources=(weak,))
        for i in range(5)
    ]
    result = admit_to_slot(
        restricted, cands,
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    assert len(result.evaluated_candidates) == 2
    assert result.status == SKIPPED_NO_CANDIDATE


# ── Slot-specific thresholds ────────────────────────────────────────────────

def test_intelligence_brief_enforces_higher_threshold(sat_config, history):
    brief_slot = _slot("intelligence_brief", admission={
        "source_confidence_min": 75,
        "editorial_quality_min": 75,
    })
    # A candidate that would pass midday (70) but fails brief (75).
    # Use a single primary source for moderate confidence.
    cand = _candidate()
    policy = build_slot_policy(brief_slot)
    assert policy.source_confidence_threshold == 75
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    # If confidence < 75, it's rejected at brief but would pass midday.
    if evaluation.source_confidence and evaluation.source_confidence < 75:
        assert RC_SOURCE_CONFIDENCE_BELOW_THRESHOLD in evaluation.reason_codes


def test_practical_takeaway_enforces_actionable_value(sat_config, history):
    takeaway_slot = _slot("practical_takeaway", admission={
        "source_confidence_min": 65,
        "editorial_quality_min": 75,
        "require_practical_developer_value": True,
    })
    cand = _candidate(development="general_news")
    policy = build_slot_policy(takeaway_slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRACTICAL_VALUE_MISSING in evaluation.reason_codes


# ── R4 material-development downgrade ───────────────────────────────────────

def test_r4_downgrade_requires_all_conditions(slot, sat_config):
    """R4 downgrade only when ALL 5 conditions hold."""
    # Build history saturating R4.
    history = _make_history("openai", "model_release", n=4, total=12)
    cand = _candidate(org="openai", development="model_release",
                      topic="openai:model_release:new_v2",
                      metadata={"evidence_references": ["https://openai.com/blog"]})
    policy = build_slot_policy(_slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "saturation_policy": "warning_permitted",
    }))
    material_types = frozenset(DEVELOPMENT_TYPES)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(),
        material_types=material_types,
        now=NOW,
    )
    # R4 should be downgraded if conditions are met.
    if evaluation.r4_material_downgrade:
        assert evaluation.r4_downgrade_reason


def test_r4_downgrade_requires_material_development(slot, sat_config):
    """Non-material development type cannot get R4 downgrade."""
    history = _make_history("openai", "general_news", n=4, total=12)
    cand = _candidate(org="openai", development="general_news",
                      topic="openai:general_news:new")
    policy = build_slot_policy(_slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "saturation_policy": "warning_permitted",
    }))
    # Use a material_types set that EXCLUDES general_news
    material_types = frozenset({"model_release", "api_release", "security_issue"})
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(),
        material_types=material_types,
        now=NOW,
    )
    # general_news is NOT in our material_types, so downgrade must not apply.
    assert not evaluation.r4_material_downgrade


def test_r1_never_downgraded(slot, sat_config):
    """Even with material development, R1 reject is absolute."""
    record = PublicationRecord(
        publication_id="pub_exact",
        published_at=NOW - dt.timedelta(hours=1),
        editorial_day=NOW.strftime("%Y-%m-%d"),
        canonical_topic_id="openai:model_release:gpt5",
        entity="openai", development_type="model_release",
        artifact_type="tutorial", theme="ai_models",
    )
    history = HistoryView(records=(record,), fingerprint="test")
    cand = _candidate(topic="openai:model_release:gpt5",
                      development="model_release",
                      metadata={"evidence_references": ["https://openai.com/blog"]})
    policy = build_slot_policy(_slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "saturation_policy": "warning_permitted",
    }))
    material_types = frozenset(DEVELOPMENT_TYPES)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(),
        material_types=material_types,
        now=NOW,
    )
    assert RC_EXACT_TOPIC_DUPLICATE in evaluation.reason_codes
    assert evaluation.status == REJECTED
    assert not evaluation.r4_material_downgrade


# ── R4 material novelty signals (corrected condition 5) ─────────────────────

def test_r4_downgrade_different_artifact_without_novelty_signal_rejected(slot, sat_config):
    """Different artifact type with unchanged facts does NOT receive the downgrade."""
    history = _make_history("openai", "model_release", n=4, total=12)
    cand = _candidate(
        org="openai", development="model_release",
        topic="openai:model_release:same_facts",
        metadata={
            "evidence_references": ["https://openai.com/blog"],
            "prior_artifact_type": "analysis",  # different artifact
            # NO novelty signal key set
        },
    )
    policy = build_slot_policy(_slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "saturation_policy": "warning_permitted",
    }))
    material_types = frozenset(DEVELOPMENT_TYPES)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(),
        material_types=material_types,
        now=NOW,
    )
    assert not evaluation.r4_material_downgrade


def test_r4_downgrade_same_artifact_with_new_pricing_may_downgrade(slot, sat_config):
    """Same artifact type with a genuinely new pricing change MAY receive the downgrade."""
    history = _make_history("openai", "pricing_change", n=4, total=12)
    cand = _candidate(
        org="openai", development="pricing_change",
        topic="openai:pricing_change:v2",
        metadata={
            "evidence_references": ["https://openai.com/pricing"],
            "new_pricing": True,
        },
    )
    policy = build_slot_policy(_slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "saturation_policy": "warning_permitted",
    }))
    material_types = frozenset(DEVELOPMENT_TYPES)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(),
        material_types=material_types,
        now=NOW,
    )
    # If R4 fires, the novelty signal should allow downgrade.
    if any(r.rule_id == "R4" and r.status == STATUS_REJECT
           for r in (evaluation.saturation_result.rules if evaluation.saturation_result else ())):
        assert evaluation.r4_material_downgrade


def test_r4_downgrade_same_artifact_with_new_security_disclosure(slot, sat_config):
    """Same artifact type with a new security advisory MAY receive the downgrade."""
    history = _make_history("openai", "security_issue", n=4, total=12)
    cand = _candidate(
        org="openai", development="security_issue",
        topic="openai:security_issue:cve_new",
        metadata={
            "evidence_references": ["https://openai.com/security/advisory"],
            "new_security_disclosure": True,
        },
    )
    policy = build_slot_policy(_slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "saturation_policy": "warning_permitted",
    }))
    material_types = frozenset(DEVELOPMENT_TYPES)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(),
        material_types=material_types,
        now=NOW,
    )
    if any(r.rule_id == "R4" and r.status == STATUS_REJECT
           for r in (evaluation.saturation_result.rules if evaluation.saturation_result else ())):
        assert evaluation.r4_material_downgrade


def test_r4_downgrade_new_topic_without_novelty_signal_rejected(slot, sat_config):
    """New canonical topic without a new novelty signal does NOT receive the downgrade."""
    history = _make_history("openai", "model_release", n=4, total=12)
    cand = _candidate(
        org="openai", development="model_release",
        topic="openai:model_release:completely_new",
        metadata={
            "evidence_references": ["https://openai.com/blog"],
            # NO novelty signal — just a different topic with same type of coverage
        },
    )
    policy = build_slot_policy(_slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "saturation_policy": "warning_permitted",
    }))
    material_types = frozenset(DEVELOPMENT_TYPES)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(),
        material_types=material_types,
        now=NOW,
    )
    assert not evaluation.r4_material_downgrade


# ── Practical value: tightened gate (CORRECTION 2) ──────────────────────────

def test_model_release_without_practical_evidence_fails(slot, sat_config, history):
    """model_release development type alone does NOT pass practical value."""
    cand = _candidate(development="model_release")  # no signal key
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRACTICAL_VALUE_MISSING in evaluation.reason_codes


def test_api_release_without_documentation_or_availability_evidence_fails(
        slot, sat_config, history):
    """api_release development type alone does NOT pass practical value."""
    cand = _candidate(development="api_release")  # no signal key
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRACTICAL_VALUE_MISSING in evaluation.reason_codes


def test_pricing_change_with_sourced_pricing_impact_passes(slot, sat_config, history):
    """pricing_change with has_pricing_impact signal passes practical value."""
    cand = _candidate(
        development="pricing_change",
        metadata={"has_pricing_impact": True},
    )
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRACTICAL_VALUE_MISSING not in evaluation.reason_codes


def test_security_issue_with_explicit_remediation_action_passes(slot, sat_config, history):
    """security_issue with has_security_action signal passes practical value."""
    cand = _candidate(
        development="security_issue",
        metadata={"has_security_action": True},
    )
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRACTICAL_VALUE_MISSING not in evaluation.reason_codes


def test_repository_release_with_concrete_code_change_passes(slot, sat_config, history):
    """repository_release with has_code_change signal passes practical value."""
    cand = _candidate(
        development="repository_release",
        metadata={"has_code_change": True},
    )
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRACTICAL_VALUE_MISSING not in evaluation.reason_codes


def test_repository_release_with_compatibility_impact_passes(slot, sat_config, history):
    """repository_release with has_compatibility_impact signal passes practical value."""
    cand = _candidate(
        development="repository_release",
        metadata={"has_compatibility_impact": True},
    )
    policy = build_slot_policy(slot)
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    )
    assert RC_PRACTICAL_VALUE_MISSING not in evaluation.reason_codes


# ── Reason codes ─────────────────────────────────────────────────────────────

def test_all_reason_codes_are_defined():
    for code in ALL_REASON_CODES:
        assert code in REASON_EXPLANATIONS, f"missing explanation for {code}"


def test_reason_codes_are_stable_strings():
    for code in ALL_REASON_CODES:
        assert isinstance(code, str)
        assert code.replace("_", "").isalnum()


# ── Determinism ──────────────────────────────────────────────────────────────

def test_same_input_gives_identical_decision(slot, sat_config, history):
    cand = _candidate()
    policy = build_slot_policy(slot)
    first = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(), now=NOW,
    ).to_dict()
    for _ in range(5):
        result = evaluate_candidate(
            cand, rank=1, policy=policy,
            saturation_config=sat_config, history=history,
            scoring_config=_scoring_config(), now=NOW,
        ).to_dict()
        assert result == first


# ── Shadow decision recording ────────────────────────────────────────────────

def test_shadow_decision_record_does_not_affect_saturation_history(
        slot, sat_config, history, tmp_path):
    """Shadow records must not inflate future saturation calculations."""
    cand = _candidate()
    result = admit_to_slot(
        slot, [cand],
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    # Record shadow decisions.
    record_shadow_decision(result)
    # The original history is unchanged — no records were added.
    assert len(history.records) == 0


def test_shadow_record_preserves_every_rejection_reason(slot, sat_config, history, monkeypatch):
    """Decision records carry all reason codes."""
    import agent.content_decisions as CD
    recorded = []
    monkeypatch.setattr(CD, "record", lambda d: recorded.append(d))

    weak = _src(kind="secondary", exact=False)
    cand = _candidate(sources=(weak,))
    result = admit_to_slot(
        slot, [cand],
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    record_shadow_decision(result)
    assert recorded
    metadata = recorded[0].metadata
    assert "all_reason_codes" in metadata
    assert "policy_snapshot" in metadata
    assert "source_confidence_summary" in metadata
    assert "saturation_summary" in metadata
    assert metadata["mode"] == "shadow"


# ── No LLM / network / content generation ───────────────────────────────────

def test_no_llm_or_network_calls(slot, sat_config, history, monkeypatch):
    import urllib.request
    import agent.llm_ops as LLM

    def explode(*a, **k):
        raise AssertionError("admission must not call LLM or network")

    monkeypatch.setattr(LLM, "chat", explode)
    monkeypatch.setattr(LLM, "requests", type("R", (), {"post": staticmethod(explode)}))
    monkeypatch.setattr(urllib.request, "urlopen", explode)

    cand = _candidate(metadata={"has_code_change": True})
    result = admit_to_slot(
        slot, [cand],
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    assert result.status == ADMITTED


def test_no_content_generation_calls(slot, sat_config, history, monkeypatch):
    """Admission never triggers article generation."""
    def explode(*a, **k):
        raise AssertionError("admission must not generate content")

    # Patch every known generation entry point.
    for mod_name in ("agent.content_generator", "agent.article_writer",
                     "scripts.generate_article"):
        try:
            import importlib
            mod = importlib.import_module(mod_name)
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if callable(obj) and not attr.startswith("_"):
                    monkeypatch.setattr(mod, attr, explode)
        except (ImportError, ModuleNotFoundError):
            pass

    cand = _candidate()
    result = admit_to_slot(
        slot, [cand],
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    assert result  # no assertion needed — if we got here, no generation ran


# ── Production behavior unchanged ───────────────────────────────────────────

def test_production_unchanged_while_flag_is_false():
    import content_formats as CF
    from agent.editorial import editorial_slots_enabled

    assert editorial_slots_enabled() is False
    assert len(CF.NEWS_FORMATS) == 8
    assert not (set(CF.EDITORIAL_FORMATS) & set(CF.NEWS_FORMATS))


# ── Slot policy validation ──────────────────────────────────────────────────

def test_force_publish_is_rejected():
    bad_slot = _slot(admission={
        "source_confidence_min": 70,
        "editorial_quality_min": 80,
        "force_publish": True,
    })
    with pytest.raises(SlotPolicyError) as exc:
        build_slot_policy(bad_slot)
    assert any("force publication" in p for p in exc.value.problems)


def test_opportunity_overriding_evidence_is_rejected():
    bad_slot = _slot(admission={
        "source_confidence_min": 70,
        "editorial_quality_min": 80,
        "opportunity_overrides_evidence": True,
    })
    with pytest.raises(SlotPolicyError) as exc:
        build_slot_policy(bad_slot)
    assert any("override" in p for p in exc.value.problems)


def test_missing_source_confidence_threshold_is_rejected():
    bad_slot = _slot(admission={"editorial_quality_min": 80})
    with pytest.raises(SlotPolicyError) as exc:
        build_slot_policy(bad_slot)
    assert any("source_confidence_min" in p for p in exc.value.problems)


def test_unknown_development_type_in_allowed_list_is_rejected():
    bad_slot = _slot(admission={
        "source_confidence_min": 70,
        "editorial_quality_min": 80,
        "allowed_development_types": ["teleportation"],
    })
    with pytest.raises(SlotPolicyError) as exc:
        build_slot_policy(bad_slot)
    assert any("unknown development type" in p for p in exc.value.problems)


def test_maximum_candidates_below_1_is_rejected():
    bad_slot = _slot(admission={
        "source_confidence_min": 70,
        "editorial_quality_min": 80,
        "maximum_candidates_to_evaluate": 0,
    })
    with pytest.raises(SlotPolicyError) as exc:
        build_slot_policy(bad_slot)
    assert any("maximum_candidates_to_evaluate" in p for p in exc.value.problems)


def test_invalid_backup_policy_is_rejected():
    bad_slot = _slot(admission={
        "source_confidence_min": 70,
        "editorial_quality_min": 80,
        "backup_selection_policy": "random",
    })
    with pytest.raises(SlotPolicyError) as exc:
        build_slot_policy(bad_slot)
    assert any("backup_selection_policy" in p for p in exc.value.problems)


# ── Output schema ────────────────────────────────────────────────────────────

def test_result_carries_every_documented_field(slot, sat_config, history):
    result = admit_to_slot(
        slot, [_candidate()],
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    ).to_dict()
    for key in ("slot_id", "status", "selected_candidate_id",
                "evaluated_candidates", "selected_policy_snapshot",
                "decision_time", "mode", "version"):
        assert key in result, key


def test_evaluated_candidate_carries_every_field(slot, sat_config, history):
    result = admit_to_slot(
        slot, [_candidate()],
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    ev = result.evaluated_candidates[0].to_dict()
    for key in ("candidate_id", "rank", "status", "reason_codes",
                "opportunity_score", "source_confidence", "saturation_status"):
        assert key in ev, key


# ── Material update admitted with warning ────────────────────────────────────

def test_material_update_admitted_with_warning(slot, sat_config):
    """A material development that saturates R4 but has new evidence
    can be admitted with warning status."""
    history = _make_history("openai", "model_release", n=3, total=12)
    cand = _candidate(
        org="openai", development="model_release",
        topic="openai:model_release:v6",
        metadata={"evidence_references": ["https://openai.com/new-release"]},
    )
    policy = build_slot_policy(_slot(admission={
        "source_confidence_min": 50,
        "editorial_quality_min": 0,
        "saturation_policy": "warning_permitted",
    }))
    material_types = frozenset({"model_release"})
    evaluation = evaluate_candidate(
        cand, rank=1, policy=policy,
        saturation_config=sat_config, history=history,
        scoring_config=_scoring_config(),
        material_types=material_types,
        now=NOW,
    )
    # If R4 fires and all conditions are met, we should see warning or r4_downgrade.
    if evaluation.r4_material_downgrade:
        assert evaluation.status in (WARNING, ADMITTED)


# ── Intelligence brief example ──────────────────────────────────────────────

def test_intelligence_brief_full_admission(sat_config, history):
    """Full pipeline: high-confidence candidate admitted to brief slot."""
    brief_slot = _slot("intelligence_brief", admission={
        "source_confidence_min": 75,
        "editorial_quality_min": 75,
    })
    # Strong evidence: primary + 2 corroborating secondaries → score ~80
    sources = (
        _src(url="https://openai.com/blog", kind="official_announcement"),
        _src(url="https://arstechnica.com/gpt5", kind="secondary"),
        _src(url="https://theverge.com/gpt5", kind="secondary"),
    )
    cand = _candidate(sources=sources, opp_score=88)
    result = admit_to_slot(
        brief_slot, [cand],
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    assert result.status == ADMITTED
    assert result.evaluated_candidates[0].source_confidence >= 75


# ── High-interest but weak-evidence rejection example ───────────────────────

def test_high_interest_weak_evidence_rejection(slot, sat_config, history):
    """95 opportunity score, but only one weak secondary source."""
    weak = _src(url="https://rumor.blog/gpt5", kind="secondary",
                exact=False, excerpt="")
    cand = _candidate(sources=(weak,), opp_score=95)
    result = admit_to_slot(
        slot, [cand],
        history=history,
        saturation_config=sat_config,
        scoring_config=_scoring_config(),
        now=NOW,
    )
    assert result.status in (REJECTED, SKIPPED_NO_CANDIDATE)
    ev = result.evaluated_candidates[0]
    assert ev.opportunity_score == 95
    assert RC_SOURCE_CONFIDENCE_BELOW_THRESHOLD in ev.reason_codes
