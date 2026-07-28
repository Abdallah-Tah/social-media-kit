"""Phase 1 Stage 6 — deterministic publication readiness verdict."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from agent.editorial.admission import ADMITTED, REJECTED, AdmissionResult, CandidateEvaluation
from agent.editorial.models import (
    Claim,
    Candidate,
    SourceRef,
    VERIFIED_INDEPENDENT,
    VERIFIED_VENDOR,
)
from agent.editorial.publication_record import MODE_SHADOW
from agent.editorial.quality import (
    ComponentResult,
    DraftInput,
    QualityNote,
    QualityResult,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_WARNING,
    WARNING_GENERIC_FILLER,
)
from agent.editorial.readiness import (
    CONFIG_PATH,
    RC_ADMISSION_NOT_SUCCESSFUL,
    RC_ARTIFACT_TYPE_MISMATCH,
    RC_CONTRADICTS_CONFIRMED_FACTS,
    RC_DRAFT_INCOMPLETE,
    RC_DUPLICATE_PUBLICATION_INTENT,
    RC_DUPLICATE_SUCCESSFUL_PUBLICATION,
    RC_EDITORIAL_HARD_FAILURE,
    RC_EDITORIAL_QUALITY_FAILED,
    RC_IMPORTANT_QUALITY_WARNING,
    RC_R4_OVERRIDE_USED,
    RC_REQUIRED_SOURCES_DISAPPEARED,
    RC_SOURCE_CONFIDENCE_NEAR_THRESHOLD,
    RC_SENSITIVE_ACCUSATION_CONTENT,
    RC_SENSITIVE_SECURITY_CONTENT,
    RC_TRACEABLE_BUT_AMBIGUOUS,
    RC_UNSUPPORTED_CLAIMS,
    RC_VENDOR_BENCHMARK_UNVERIFIED,
    STATUS_READY,
    STATUS_READY_WITH_WARNINGS,
    STATUS_REJECTED,
    STATUS_REQUIRES_MANUAL_REVIEW,
    ReadinessConfigError,
    ReadinessInput,
    evaluate_and_record_readiness,
    evaluate_readiness,
    load_readiness_config,
)
from agent.editorial.saturation import build_history, load_saturation_config


NOW = dt.datetime(2026, 7, 28, 16, 0, tzinfo=dt.timezone.utc)


@dataclass(frozen=True)
class _Score:
    score: int
    version: int = 1


def _source(url: str = "https://example.com/primary",
            kind: str = "official_announcement") -> SourceRef:
    return SourceRef(
        url=url,
        kind=kind,
        title="Source",
        published_at="2026-07-28T12:00:00+00:00",
        covers_exact_development=True,
        adds_independent_evidence=(kind == "secondary"),
        excerpt="Grounding evidence",
    )


def _claim(text: str = "Latency improved 40%", *,
           claim_type: str = "benchmark",
           verification: str = VERIFIED_INDEPENDENT) -> Claim:
    return Claim(
        text=text,
        claim_id="claim_1",
        claim_type=claim_type,
        verification=verification,
        source_url="https://example.com/primary",
        source_urls=("https://example.com/primary",),
    )


def _candidate(development_type: str = "api_release",
               artifact_type: str = "technical_analysis",
               claims: tuple[Claim, ...] = (),
               sources: tuple[SourceRef, ...] | None = None) -> Candidate:
    if sources is None:
        sources = (_source(), _source("https://example.com/secondary", kind="secondary"))
    return Candidate(
        title="OpenAI updates GPT API",
        url="https://example.com/post",
        candidate_id="cand_123",
        canonical_topic_id="openai:api_release:gpt_api",
        subject_org="openai",
        development_type=development_type,
        content_kind=artifact_type,
        event_time="2026-07-28T12:00:00+00:00",
        source_fingerprint="cand_src_fp",
        sources=sources,
        claims=claims,
    )


def _quality_result(*, status: str = STATUS_PASS, score: int = 88,
                    hard_failures: tuple[str, ...] = (),
                    issue_codes: tuple[str, ...] = (),
                    warning_codes: tuple[str, ...] = ()) -> QualityResult:
    issue_details = tuple(QualityNote(code=code, message=code.replace("_", " ")) for code in issue_codes)
    warning_details = tuple(QualityNote(code=code, message=code.replace("_", " ")) for code in warning_codes)
    component = ComponentResult(
        name="dummy",
        score=min(score, 20),
        max_weight=20,
        issues=tuple(note.message for note in issue_details),
        warnings=tuple(note.message for note in warning_details),
        issue_details=issue_details,
        warning_details=warning_details,
    )
    return QualityResult(
        score=score,
        status=status,
        components=(component,),
        hard_failures=hard_failures,
        issues=tuple(note.message for note in issue_details),
        warnings=tuple(note.message for note in warning_details),
        artifact_type="technical_analysis",
        format_id="under_the_hood",
        issue_details=issue_details,
        warning_details=warning_details,
    )


def _draft(body_suffix: str = "Stable ending.") -> DraftInput:
    return DraftInput(
        title="Understanding the GPT API update",
        body=(
            "# Understanding the GPT API update\n\n"
            "## Overview\n\n"
            "API v2.1 shipped on 2026-07-28.\n\n"
            "## Technical Details\n\n"
            "```bash\ncurl https://example.com\n```\n\n"
            "## Analysis\n\n"
            f"Developers should watch rate limits. {body_suffix}\n\n"
            "## Sources\n\n"
            "- https://example.com/primary\n"
        ),
        summary="A grounded technical summary.",
        artifact_type="technical_analysis",
        format_id="under_the_hood",
        slot_objective="explain",
        sources=({"url": "https://example.com/primary", "text": "API v2.1 shipped"},),
        claims=(),
        confirmed_facts=(),
        metadata={},
    )


def _admission(candidate: Candidate | None = None, *,
               status: str = ADMITTED,
               candidate_status: str = ADMITTED,
               r4_override: bool = False) -> AdmissionResult:
    candidate = candidate or _candidate()
    evaluation = CandidateEvaluation(
        candidate_id=candidate.candidate_id,
        rank=1,
        status=candidate_status,
        reason_codes=(),
        reasons=(),
        opportunity_score=86,
        source_confidence=84,
        saturation_status="clear",
        source_confidence_summary={"score": 84},
        saturation_summary={"status": "clear"},
        policy_snapshot={"slot_id": "midday_authority", "source_confidence_threshold": 70},
        r4_material_downgrade=r4_override,
        r4_downgrade_reason="R4 override used" if r4_override else "",
        enriched_candidate=candidate,
    )
    return AdmissionResult(
        slot_id="midday_authority",
        status=status,
        selected_candidate_id=candidate.candidate_id if status == ADMITTED else "",
        evaluated_candidates=(evaluation,),
        selected_policy_snapshot={"slot_id": "midday_authority", "source_confidence_threshold": 70},
        decision_time=NOW.isoformat(),
        mode="shadow",
        warnings=(),
    )


def _input(*, candidate: Candidate | None = None,
           admission_result: AdmissionResult | None = None,
           quality_result: QualityResult | None = None,
           source_confidence: int = 84,
           generation_metadata: dict | None = None,
           artifact_type: str = "technical_analysis",
           format_id: str = "under_the_hood",
           draft: DraftInput | None = None) -> ReadinessInput:
    candidate = candidate or _candidate()
    admission_result = admission_result or _admission(candidate)
    quality_result = quality_result or _quality_result()
    return ReadinessInput(
        slot_policy_snapshot={"slot_id": "midday_authority", "source_confidence_threshold": 70},
        candidate=candidate,
        source_confidence_result=_Score(source_confidence),
        saturation_result=None,
        admission_result=admission_result,
        draft=draft or _draft(),
        quality_result=quality_result,
        source_evidence=candidate.sources,
        claim_evidence=candidate.claims,
        generation_metadata=generation_metadata or {
            "generated_at": NOW.isoformat(),
            "admitted_artifact_type": artifact_type,
            "admitted_format_id": format_id,
        },
        artifact_type=artifact_type,
        format_id=format_id,
        editorial_day="2026-07-28",
    )


def _config():
    return load_readiness_config(CONFIG_PATH)


def test_strong_admitted_candidate_and_strong_draft_become_ready():
    decision = evaluate_readiness(_input(), _config(), now=NOW)
    assert decision.status == STATUS_READY
    assert decision.reason_codes == ()


def test_admission_rejection_can_never_become_ready():
    rejected = _admission(status=REJECTED, candidate_status=REJECTED)
    decision = evaluate_readiness(_input(admission_result=rejected), _config(), now=NOW)
    assert decision.status == STATUS_REJECTED
    assert RC_ADMISSION_NOT_SUCCESSFUL in decision.reason_codes


def test_quality_failure_becomes_rejected():
    decision = evaluate_readiness(
        _input(quality_result=_quality_result(status=STATUS_FAIL, score=40)),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REJECTED
    assert RC_EDITORIAL_QUALITY_FAILED in decision.reason_codes


def test_any_hard_failure_becomes_rejected():
    decision = evaluate_readiness(
        _input(quality_result=_quality_result(hard_failures=("prompt_leakage",))),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REJECTED
    assert RC_EDITORIAL_HARD_FAILURE in decision.reason_codes


def test_minor_warning_becomes_ready_with_warnings():
    decision = evaluate_readiness(
        _input(quality_result=_quality_result(
            status=STATUS_WARNING,
            score=84,
            warning_codes=(WARNING_GENERIC_FILLER,),
        )),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_READY_WITH_WARNINGS
    assert WARNING_GENERIC_FILLER in decision.warnings


def test_security_warning_requires_manual_review():
    decision = evaluate_readiness(
        _input(generation_metadata={
            "generated_at": NOW.isoformat(),
            "admitted_artifact_type": "technical_analysis",
            "admitted_format_id": "under_the_hood",
            "contains_security_risk": True,
        }),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REQUIRES_MANUAL_REVIEW
    assert RC_SENSITIVE_SECURITY_CONTENT in decision.manual_review_reasons


def test_unsupported_accusation_requires_manual_review_or_rejection():
    decision = evaluate_readiness(
        _input(generation_metadata={
            "generated_at": NOW.isoformat(),
            "admitted_artifact_type": "technical_analysis",
            "admitted_format_id": "under_the_hood",
            "contains_accusation_risk": True,
        }),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REQUIRES_MANUAL_REVIEW
    assert RC_SENSITIVE_ACCUSATION_CONTENT in decision.manual_review_reasons


def test_vendor_benchmark_without_independent_verification_requires_manual_review():
    candidate = _candidate(claims=(_claim(verification=VERIFIED_VENDOR),))
    decision = evaluate_readiness(_input(candidate=candidate), _config(), now=NOW)
    assert decision.status == STATUS_REQUIRES_MANUAL_REVIEW
    assert RC_VENDOR_BENCHMARK_UNVERIFIED in decision.manual_review_reasons


def test_r4_material_downgrade_requires_manual_review():
    candidate = _candidate()
    decision = evaluate_readiness(
        _input(candidate=candidate, admission_result=_admission(candidate, r4_override=True)),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REQUIRES_MANUAL_REVIEW
    assert RC_R4_OVERRIDE_USED in decision.manual_review_reasons


def test_near_threshold_source_confidence_requires_manual_review():
    decision = evaluate_readiness(_input(source_confidence=72), _config(), now=NOW)
    assert decision.status == STATUS_REQUIRES_MANUAL_REVIEW
    assert RC_SOURCE_CONFIDENCE_NEAR_THRESHOLD in decision.manual_review_reasons


def test_contradictory_draft_is_rejected():
    decision = evaluate_readiness(
        _input(generation_metadata={
            "generated_at": NOW.isoformat(),
            "admitted_artifact_type": "technical_analysis",
            "admitted_format_id": "under_the_hood",
            "draft_contradicts_confirmed_facts": True,
        }),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REJECTED
    assert RC_CONTRADICTS_CONFIRMED_FACTS in decision.reason_codes


def test_missing_admitted_source_is_rejected():
    decision = evaluate_readiness(
        _input(generation_metadata={
            "generated_at": NOW.isoformat(),
            "admitted_artifact_type": "technical_analysis",
            "admitted_format_id": "under_the_hood",
            "required_sources_disappeared": True,
        }),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REJECTED
    assert RC_REQUIRED_SOURCES_DISAPPEARED in decision.reason_codes


def test_changed_artifact_type_is_rejected():
    decision = evaluate_readiness(
        _input(
            artifact_type="tutorial",
            generation_metadata={
                "generated_at": NOW.isoformat(),
                "admitted_artifact_type": "technical_analysis",
                "admitted_format_id": "under_the_hood",
            },
        ),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REJECTED
    assert RC_ARTIFACT_TYPE_MISMATCH in decision.reason_codes


def test_truncated_draft_is_rejected():
    decision = evaluate_readiness(
        _input(generation_metadata={
            "generated_at": NOW.isoformat(),
            "admitted_artifact_type": "technical_analysis",
            "admitted_format_id": "under_the_hood",
            "draft_truncated": True,
        }),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REJECTED
    assert RC_DRAFT_INCOMPLETE in decision.reason_codes


def test_existing_publication_intent_blocks_readiness():
    existing = [{
        "stage": "article_gate",
        "decision": "accepted",
        "metadata": {
            "candidate_id": "cand_123",
            "slot_id": "midday_authority",
            "editorial_day": "2026-07-28",
            "status": "ready",
            "decision_id": "other_decision",
        },
    }]
    decision = evaluate_readiness(_input(), _config(), existing_rows=existing, now=NOW)
    assert decision.status == STATUS_REJECTED
    assert RC_DUPLICATE_PUBLICATION_INTENT in decision.reason_codes


def test_existing_successful_publication_blocks_readiness():
    existing = [{
        "stage": "publish",
        "decision": "accepted",
        "metadata": {
            "candidate_id": "cand_123",
            "slot_id": "midday_authority",
            "editorial_day": "2026-07-28",
            "decision_id": "published_decision",
        },
    }]
    decision = evaluate_readiness(_input(), _config(), existing_rows=existing, now=NOW)
    assert decision.status == STATUS_REJECTED
    assert RC_DUPLICATE_SUCCESSFUL_PUBLICATION in decision.reason_codes


def test_stable_unchanged_input_returns_identical_decision_id():
    first = evaluate_readiness(_input(), _config(), now=NOW)
    second = evaluate_readiness(_input(), _config(), now=NOW)
    assert first.decision_id == second.decision_id
    assert first.status == second.status
    assert first.draft_fingerprint == second.draft_fingerprint


def test_changed_draft_changes_fingerprint_and_decision_id():
    first = evaluate_readiness(_input(draft=_draft()), _config(), now=NOW)
    second = evaluate_readiness(_input(draft=_draft("Different ending.")), _config(), now=NOW)
    assert first.draft_fingerprint != second.draft_fingerprint
    assert first.decision_id != second.decision_id


def test_shadow_record_does_not_affect_saturation_history(monkeypatch, tmp_path):
    import agent.content_decisions as CD

    monkeypatch.setattr(CD, "DECISION_LOG", tmp_path / "content_decisions.jsonl")
    decision = evaluate_and_record_readiness(_input(), _config(), existing_rows=[], now=NOW)
    rows = CD.read()
    assert rows and rows[-1]["stage"] == "article_gate"
    history = build_history(rows, load_saturation_config())
    assert history.records == ()
    assert decision.mode == MODE_SHADOW


def test_no_publication_network_or_llm_call_occurs(monkeypatch):
    import urllib.request
    import agent.content_decisions as CD
    import agent.llm_ops as LLM

    def explode(*args, **kwargs):
        raise AssertionError("Stage 6 must not call publishing, network, or LLM code")

    monkeypatch.setattr(LLM, "chat", explode)
    monkeypatch.setattr(LLM, "requests", type("R", (), {"post": staticmethod(explode)}))
    monkeypatch.setattr(urllib.request, "urlopen", explode)
    monkeypatch.setattr(CD, "record", lambda decision: decision)

    decision = evaluate_and_record_readiness(_input(), _config(), existing_rows=[], now=NOW)
    assert decision.status == STATUS_READY


def test_production_remains_unchanged_while_flag_is_false(monkeypatch, tmp_path):
    import agent.content_decisions as CD
    from agent.editorial.flags import editorial_slots_enabled

    monkeypatch.setattr(CD, "DECISION_LOG", tmp_path / "content_decisions.jsonl")
    decision = evaluate_and_record_readiness(_input(), _config(), existing_rows=[], now=NOW)
    rows = CD.read()
    assert editorial_slots_enabled() is False
    assert decision.mode == MODE_SHADOW
    assert rows[-1]["stage"] == "article_gate"
    assert all(row["stage"] != "publish" for row in rows)


def test_important_quality_warning_requires_manual_review():
    decision = evaluate_readiness(
        _input(quality_result=_quality_result(
            status=STATUS_PASS,
            score=88,
            warning_codes=("numeric_claims_without_sources",),
        )),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REQUIRES_MANUAL_REVIEW
    assert RC_IMPORTANT_QUALITY_WARNING in decision.manual_review_reasons


def test_traceable_but_ambiguous_claim_requires_manual_review():
    decision = evaluate_readiness(
        _input(generation_metadata={
            "generated_at": NOW.isoformat(),
            "admitted_artifact_type": "technical_analysis",
            "admitted_format_id": "under_the_hood",
            "traceable_but_ambiguous_claim": True,
        }),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REQUIRES_MANUAL_REVIEW
    assert RC_TRACEABLE_BUT_AMBIGUOUS in decision.manual_review_reasons


def test_unsupported_claims_are_rejected():
    decision = evaluate_readiness(
        _input(generation_metadata={
            "generated_at": NOW.isoformat(),
            "admitted_artifact_type": "technical_analysis",
            "admitted_format_id": "under_the_hood",
            "unsupported_claims_present": True,
        }),
        _config(),
        now=NOW,
    )
    assert decision.status == STATUS_REJECTED
    assert RC_UNSUPPORTED_CLAIMS in decision.reason_codes


def test_config_rejects_unknown_manual_reason_code(tmp_path):
    raw = yaml.safe_load(Path(CONFIG_PATH).read_text(encoding="utf-8"))
    raw["readiness"]["manual_review_triggers"] = ["not_a_real_code"]
    path = tmp_path / "quality.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ReadinessConfigError) as exc:
        load_readiness_config(path)
    assert any("unknown codes" in p for p in exc.value.problems)


def test_config_rejects_invalid_thresholds_and_empty_duplicate_keys(tmp_path):
    raw = yaml.safe_load(Path(CONFIG_PATH).read_text(encoding="utf-8"))
    raw["readiness"]["ready_quality_threshold"] = 50
    raw["readiness"]["warning_quality_threshold"] = 60
    raw["readiness"]["duplicate_detection"]["identity_keys"] = []
    path = tmp_path / "quality.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ReadinessConfigError) as exc:
        load_readiness_config(path)
    assert any("must be >=" in p for p in exc.value.problems)
    assert any("may not be empty" in p for p in exc.value.problems)


def test_config_rejects_sensitive_auto_ready_overlap(tmp_path):
    raw = yaml.safe_load(Path(CONFIG_PATH).read_text(encoding="utf-8"))
    raw["readiness"]["auto_ready_development_types"] = ["security_issue"]
    path = tmp_path / "quality.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ReadinessConfigError) as exc:
        load_readiness_config(path)
    assert any("may not overlap" in p for p in exc.value.problems)


def test_config_rejects_policies_allowing_hard_failures_or_rejected_admissions(tmp_path):
    raw = yaml.safe_load(Path(CONFIG_PATH).read_text(encoding="utf-8"))
    raw["readiness"]["allow_hard_failures_to_pass"] = True
    raw["readiness"]["allow_rejected_admissions_to_pass"] = True
    path = tmp_path / "quality.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ReadinessConfigError) as exc:
        load_readiness_config(path)
    assert any("hard failures" in p for p in exc.value.problems)
    assert any("rejected admissions" in p for p in exc.value.problems)
