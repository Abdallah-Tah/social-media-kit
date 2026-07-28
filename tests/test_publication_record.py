"""Phase 1 Stage 3.5 — the publication metadata contract.

Saturation reads a publication's editorial identity from the ContentDecision
`metadata` dict. Nothing wrote those fields, so real history read as entirely
legacy records and saturation could only be exercised against synthetic data.

Two properties these tests hold:
  * `theme` and `editorial_day` are FROZEN at publication. Editing theme_map or
    the editorial timezone afterwards must not rewrite what a past publication
    was;
  * `identity_source` / `identity_confidence` are recorded but NOT acted on —
    saturation still treats every entity as equally certain.
"""
import datetime as dt
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from agent.editorial import saturation as S  # noqa: E402
from agent.editorial.models import Candidate, SourceRef  # noqa: E402
from agent.editorial.publication_record import (  # noqa: E402
    IDENTITY_FIELDS,
    MODE_REPLAY,
    MODE_SHADOW,
    PUBLICATION_FIELDS,
    PUBLICATION_METADATA_VERSION,
    REQUIRED_FIELDS,
    PublicationMetadataError,
    assert_valid,
    backfill_metadata,
    build_publication_metadata,
    editorial_day_for,
    record_publication,
    validate_publication_metadata,
)
from agent.editorial.saturation import (  # noqa: E402
    build_history,
    evaluate_saturation,
    load_saturation_config,
)

NOW = dt.datetime(2026, 7, 27, 16, 0, tzinfo=dt.timezone.utc)  # 12:00 New York


@pytest.fixture
def config():
    return load_saturation_config()


@pytest.fixture
def candidate():
    return Candidate(
        title="OpenAI launches GPT-5",
        url="https://openai.com/blog/gpt-5",
        canonical_topic_id="openai:model_release:gpt-5",
        subject_org="openai",
        development_type="model_release",
        content_kind="news",
        source_fingerprint="fp-abc123",
        subject_org_confidence=0.9,
        subject_org_resolution_reason="first_party_source_domain",
        sources=(
            SourceRef(url="https://openai.com/blog/gpt-5",
                      kind="official_announcement", covers_exact_development=True),
            SourceRef(url="https://techcrunch.com/gpt-5"),
        ),
    )


class FakeConfidence:
    """Stands in for a SourceConfidence without importing the scorer."""

    def __init__(self, score=88, counted=("techcrunch.com", "arstechnica.com")):
        self.score = score
        self.components = {"corroboration": type("C", (), {
            "extra": {"counted_domains": list(counted)}})()}


def build(candidate, **kw):
    defaults = dict(slot="midday_authority", published_at=NOW,
                    publication_id="post-42")
    return build_publication_metadata(candidate, **{**defaults, **kw})


# ── The contract ────────────────────────────────────────────────────────────

def test_every_agreed_field_is_present(candidate):
    metadata = build(candidate, source_confidence=FakeConfidence())
    for name in REQUIRED_FIELDS:
        assert name in metadata, name


def test_the_thirteen_identity_fields_are_the_agreed_ones():
    assert IDENTITY_FIELDS == (
        "canonical_topic_id", "entity", "development_type", "artifact_type",
        "theme", "slot", "editorial_day", "source_fingerprint",
        "primary_source_url", "corroborating_domains", "identity_source",
        "identity_confidence", "schema_version")


def test_publication_identity_is_separate_from_editorial_identity():
    """publication_id answers 'which post', not 'what was it about'."""
    assert PUBLICATION_FIELDS == ("publication_id", "published_at")
    assert not set(PUBLICATION_FIELDS) & set(IDENTITY_FIELDS)


def test_the_block_carries_the_candidates_identity(candidate):
    metadata = build(candidate)
    assert metadata["canonical_topic_id"] == "openai:model_release:gpt-5"
    assert metadata["entity"] == "openai"
    assert metadata["development_type"] == "model_release"
    assert metadata["artifact_type"] == "news"
    assert metadata["source_fingerprint"] == "fp-abc123"
    assert metadata["slot"] == "midday_authority"
    assert metadata["schema_version"] == PUBLICATION_METADATA_VERSION


def test_the_primary_source_url_is_the_exact_development_source(candidate):
    assert build(candidate)["primary_source_url"] == "https://openai.com/blog/gpt-5"


def test_corroborating_domains_come_from_the_confidence_result(candidate):
    metadata = build(candidate, source_confidence=FakeConfidence(
        counted=("b.com", "a.com")))
    assert metadata["corroborating_domains"] == ["a.com", "b.com"], "sorted"


def test_corroborating_domains_default_to_empty_without_a_score(candidate):
    assert build(candidate)["corroborating_domains"] == []


def test_building_metadata_is_deterministic(candidate):
    first = build(candidate, source_confidence=FakeConfidence())
    for _ in range(5):
        assert build(candidate, source_confidence=FakeConfidence()) == first


# ── Frozen theme and editorial day ──────────────────────────────────────────

def test_the_theme_is_resolved_and_stored_at_publication(candidate):
    assert build(candidate)["theme"] == "ai_models"


def test_an_explicit_theme_overrides_the_map(candidate):
    assert build(candidate, theme="custom_theme")["theme"] == "custom_theme"


def test_an_upstream_metadata_theme_is_used(config):
    cand = Candidate(canonical_topic_id="acme:general_news:1", subject_org="acme",
                     development_type="general_news", metadata={"theme": "databases"})
    assert build(cand)["theme"] == "databases"


def test_an_unmapped_entity_stores_theme_unknown(candidate):
    cand = Candidate(canonical_topic_id="nobody:general_news:1",
                     subject_org="nobody", development_type="general_news")
    assert build(cand)["theme"] == S.THEME_UNKNOWN


def test_editing_the_theme_map_later_does_not_rewrite_history(candidate, config):
    """The whole reason theme is frozen at publication."""
    stamp = NOW - dt.timedelta(days=2)
    metadata = build(candidate, published_at=stamp)
    row = {"stage": "publish", "decision": "accepted", "job_id": "t",
           "ts": stamp.isoformat(), "title": "x", "metadata": metadata}

    # A later config where openai maps somewhere else entirely.
    from dataclasses import replace
    remapped = replace(config, theme_map={"openai": "something_else"})

    record = build_history([row], remapped).records[0]
    assert record.theme == "ai_models", "the stored theme wins over the new map"


def test_the_editorial_day_is_stored_not_recomputed(candidate, config):
    """A 02:00 UTC publication is the previous New York editorial day."""
    stamp = dt.datetime(2026, 7, 28, 2, 0, tzinfo=dt.timezone.utc)
    metadata = build(candidate, published_at=stamp)
    assert metadata["editorial_day"] == "2026-07-27"

    row = {"stage": "publish", "decision": "accepted", "job_id": "t",
           "ts": stamp.isoformat(), "metadata": metadata}
    assert build_history([row], config).records[0].editorial_day == "2026-07-27"


def test_changing_the_timezone_later_does_not_move_a_stored_editorial_day(
        candidate, config):
    from dataclasses import replace

    stamp = dt.datetime(2026, 7, 28, 2, 0, tzinfo=dt.timezone.utc)
    metadata = build(candidate, published_at=stamp)
    row = {"stage": "publish", "decision": "accepted", "job_id": "t",
           "ts": stamp.isoformat(), "metadata": metadata}

    utc_config = replace(config, timezone="UTC")
    record = build_history([row], utc_config).records[0]
    assert record.editorial_day == "2026-07-27", "stored value is immutable"


def test_editorial_day_for_handles_dst_and_bad_zones():
    assert editorial_day_for(dt.datetime(2026, 3, 8, 3, 0, tzinfo=dt.timezone.utc),
                             "America/New_York") == "2026-03-07"
    assert editorial_day_for(dt.datetime(2026, 11, 1, 6, 0, tzinfo=dt.timezone.utc),
                             "America/New_York") == "2026-11-01"
    # A bad zone degrades to UTC rather than failing a publish.
    assert editorial_day_for(NOW, "Mars/Olympus_Mons") == "2026-07-27"


def test_a_naive_published_at_is_read_as_utc(candidate):
    metadata = build(candidate, published_at=dt.datetime(2026, 7, 27, 16, 0))
    assert dt.datetime.fromisoformat(metadata["published_at"]).tzinfo is not None


# ── Identity confidence: recorded, not acted on ─────────────────────────────

def test_identity_source_and_confidence_are_recorded(candidate):
    metadata = build(candidate)
    assert metadata["identity_source"] == "first_party_source_domain"
    assert metadata["identity_confidence"] == 0.9


def test_saturation_carries_identity_confidence_without_acting_on_it(config, candidate):
    """Low-confidence attribution must saturate exactly like high-confidence."""
    def make(entity_confidence, publication_id, days_ago):
        stamp = NOW - dt.timedelta(days=days_ago)
        cand = Candidate(canonical_topic_id=f"acme:general_news:{publication_id}",
                         subject_org="acme", development_type="general_news",
                         subject_org_confidence=entity_confidence,
                         subject_org_resolution_reason="configured_alias_name")
        meta = build(cand, published_at=stamp, publication_id=publication_id)
        return {"stage": "publish", "decision": "accepted", "job_id": "t",
                "ts": stamp.isoformat(), "metadata": meta}

    low = [make(0.6, f"low-{i}", i + 1) for i in range(3)]
    high = [make(1.0, f"high-{i}", i + 1) for i in range(3)]

    cand = Candidate(canonical_topic_id="acme:general_news:new", subject_org="acme",
                     development_type="general_news")
    low_result = evaluate_saturation(cand, history=build_history(low, config),
                                     config=config, now=NOW)
    high_result = evaluate_saturation(cand, history=build_history(high, config),
                                      config=config, now=NOW)

    r4_low = next(o for o in low_result.rules if o.rule_id == "R4")
    r4_high = next(o for o in high_result.rules if o.rule_id == "R4")
    assert r4_low.status == r4_high.status == S.STATUS_REJECT
    # ...but the confidence is preserved for the replay measurement.
    assert build_history(low, config).records[0].identity_confidence == 0.6
    assert build_history(low, config).records[0].identity_source == \
        "configured_alias_name"


# ── Validation ──────────────────────────────────────────────────────────────

def test_a_complete_block_validates(candidate):
    assert validate_publication_metadata(build(candidate)) == []


def test_missing_fields_are_all_reported(candidate):
    problems = validate_publication_metadata({"entity": "openai"})
    assert len(problems) >= len(REQUIRED_FIELDS) - 1
    assert any("canonical_topic_id" in p for p in problems)
    assert any("published_at" in p for p in problems)


def test_an_unknown_development_type_is_rejected(candidate):
    metadata = build(candidate)
    metadata["development_type"] = "teleportation"
    assert any("unknown development_type" in p
               for p in validate_publication_metadata(metadata))


def test_a_malformed_topic_id_is_rejected(candidate):
    metadata = build(candidate)
    metadata["canonical_topic_id"] = "just-a-slug"
    assert any("entity:development_type:release" in p
               for p in validate_publication_metadata(metadata))


def test_a_naive_published_at_string_is_rejected(candidate):
    metadata = build(candidate)
    metadata["published_at"] = "2026-07-27T16:00:00"
    assert any("timezone-aware" in p for p in validate_publication_metadata(metadata))


def test_a_malformed_editorial_day_is_rejected(candidate):
    metadata = build(candidate)
    metadata["editorial_day"] = "July 27th"
    assert any("YYYY-MM-DD" in p for p in validate_publication_metadata(metadata))


@pytest.mark.parametrize("value", [-0.1, 1.5, "high"])
def test_an_out_of_range_identity_confidence_is_rejected(candidate, value):
    metadata = build(candidate)
    metadata["identity_confidence"] = value
    assert any("identity_confidence" in p
               for p in validate_publication_metadata(metadata))


def test_a_newer_schema_version_is_rejected_by_this_reader(candidate):
    metadata = build(candidate)
    metadata["schema_version"] = PUBLICATION_METADATA_VERSION + 1
    assert any("newer than this reader" in p
               for p in validate_publication_metadata(metadata))


def test_assert_valid_raises_with_every_problem(candidate):
    with pytest.raises(PublicationMetadataError) as exc:
        assert_valid({"entity": "openai", "development_type": "teleportation"})
    assert len(exc.value.problems) > 1


# ── Writing ─────────────────────────────────────────────────────────────────

class FakeLog:
    def __init__(self):
        self.calls = []

    def accept(self, stage, job_id, **kw):
        self.calls.append({"stage": stage, "job_id": job_id, **kw})


def test_record_publication_writes_one_publish_stage_decision(candidate):
    log = FakeLog()
    metadata = record_publication(
        candidate, job_id="feed_run", slot="midday_authority", published_at=NOW,
        publication_id="post-42", slug="gpt-5", source_confidence=FakeConfidence(),
        decision_log=log)

    assert len(log.calls) == 1
    call = log.calls[0]
    assert call["stage"] == "publish"
    assert call["publication_readiness"] == "passed"
    assert call["source_confidence"] == 88
    assert call["metadata"] == metadata
    assert call["sources"] == ["https://openai.com/blog/gpt-5",
                               "https://techcrunch.com/gpt-5"]


def test_an_invalid_block_is_never_written(candidate):
    log = FakeLog()
    broken = Candidate(canonical_topic_id="not-a-topic-id", subject_org="x",
                       development_type="model_release")
    with pytest.raises(PublicationMetadataError):
        record_publication(broken, job_id="t", slot="s", published_at=NOW,
                           publication_id="p", decision_log=log)
    assert log.calls == []


def test_a_recorded_publication_is_readable_as_saturation_history(candidate, config):
    log = FakeLog()
    record_publication(candidate, job_id="t", slot="midday_authority",
                       published_at=NOW - dt.timedelta(days=2),
                       publication_id="post-42", decision_log=log)
    row = {"stage": "publish", "decision": "accepted", "job_id": "t",
           "ts": (NOW - dt.timedelta(days=2)).isoformat(),
           "title": candidate.title, "metadata": log.calls[0]["metadata"]}

    history = build_history([row], config)
    assert len(history.records) == 1
    record = history.records[0]
    assert record.legacy is False, "a contract record is never legacy"
    assert record.canonical_topic_id == "openai:model_release:gpt-5"
    assert record.schema_version == PUBLICATION_METADATA_VERSION
    assert record.source_fingerprint == "fp-abc123"


def test_a_recorded_publication_triggers_exact_topic_saturation(candidate, config):
    log = FakeLog()
    record_publication(candidate, job_id="t", slot="midday_authority",
                       published_at=NOW - dt.timedelta(days=2),
                       publication_id="post-42", decision_log=log)
    row = {"stage": "publish", "decision": "accepted", "job_id": "t",
           "ts": (NOW - dt.timedelta(days=2)).isoformat(),
           "metadata": log.calls[0]["metadata"]}

    result = evaluate_saturation(candidate, history=build_history([row], config),
                                 config=config, now=NOW)
    assert result.status == S.STATUS_REJECT
    assert next(o for o in result.rules if o.rule_id == "R1").reason == \
        "exact_topic_republished_within_cooldown"


@pytest.mark.parametrize("mode", [MODE_SHADOW, MODE_REPLAY])
def test_shadow_and_replay_records_never_count_as_history(candidate, config, mode):
    log = FakeLog()
    record_publication(candidate, job_id="t", slot="midday_authority",
                       published_at=NOW - dt.timedelta(days=2),
                       publication_id="post-42", mode=mode, decision_log=log)
    row = {"stage": "publish", "decision": "accepted", "job_id": "t",
           "ts": (NOW - dt.timedelta(days=2)).isoformat(),
           "metadata": log.calls[0]["metadata"]}

    history = build_history([row], config)
    assert history.records == ()
    assert history.diagnostics[f"excluded_mode_{mode}"] == 1


def test_nothing_writes_the_real_decision_log_by_default(candidate, monkeypatch):
    """The production log must not be touched by the test suite or by import."""
    import agent.content_decisions as CD

    def explode(*a, **k):
        raise AssertionError("must not write the production decision log")

    monkeypatch.setattr(CD, "record", explode)
    monkeypatch.setattr(CD, "accept", explode)

    # Building is pure; only record_publication writes, and it is given a log.
    assert build(candidate)
    log = FakeLog()
    record_publication(candidate, job_id="t", slot="s", published_at=NOW,
                       publication_id="p", decision_log=log)
    assert len(log.calls) == 1


# ── Backfill / legacy tolerance ─────────────────────────────────────────────

def test_backfill_recovers_identity_from_the_topic_id():
    row = {"ts": "2026-07-25T16:00:00+00:00",
           "metadata": {"canonical_topic_id": "laravel:repository_release:13.2"}}
    metadata = backfill_metadata(row, "America/New_York")

    assert metadata["entity"] == "laravel"
    assert metadata["development_type"] == "repository_release"
    assert metadata["editorial_day"] == "2026-07-25"
    assert metadata["schema_version"] == 0, "0 marks a pre-contract record"


def test_backfill_never_invents_an_entity():
    row = {"ts": "2026-07-25T16:00:00+00:00", "metadata": {}, "title": "Some post"}
    metadata = backfill_metadata(row, "America/New_York")
    assert "entity" not in metadata
    assert "development_type" not in metadata


def test_backfill_tolerates_a_missing_or_unparseable_timestamp():
    assert backfill_metadata({"metadata": {}}, "UTC")["schema_version"] == 0
    assert backfill_metadata({"ts": "whenever", "metadata": {}}, "UTC")[
        "schema_version"] == 0


def test_pre_contract_records_still_read_as_legacy(config):
    stamp = (NOW - dt.timedelta(days=2)).isoformat()
    row = {"stage": "publish", "decision": "accepted", "job_id": "t", "ts": stamp,
           "title": "An old post", "metadata": {"published_at": stamp,
                                                "slug": "an-old-post"}}
    record = build_history([row], config).records[0]

    assert record.legacy is True
    assert record.schema_version == 0
    assert record.editorial_day, "still derived at read time for legacy rows"


def test_contract_and_legacy_records_coexist(config):
    stamp = (NOW - dt.timedelta(days=2)).isoformat()
    log = FakeLog()
    cand = Candidate(canonical_topic_id="openai:model_release:gpt-5",
                     subject_org="openai", development_type="model_release")
    record_publication(cand, job_id="t", slot="midday_authority",
                       published_at=NOW - dt.timedelta(days=2),
                       publication_id="new-1", decision_log=log)

    rows = [
        {"stage": "publish", "decision": "accepted", "job_id": "t", "ts": stamp,
         "metadata": log.calls[0]["metadata"]},
        {"stage": "publish", "decision": "accepted", "job_id": "t", "ts": stamp,
         "title": "old", "metadata": {"published_at": stamp, "slug": "old-post"}},
    ]
    history = build_history(rows, config)

    assert len(history.records) == 2
    assert {r.schema_version for r in history.records} == {0, PUBLICATION_METADATA_VERSION}
    assert S.WARN_LEGACY_RECORDS in history.warnings


# ── Dormancy ────────────────────────────────────────────────────────────────

def test_stage_three_five_changes_nothing_while_the_flag_is_false():
    import content_formats as CF
    from agent.editorial import editorial_slots_enabled

    assert editorial_slots_enabled() is False
    assert len(CF.NEWS_FORMATS) == 8
    assert not (set(CF.EDITORIAL_FORMATS) & set(CF.NEWS_FORMATS))


def test_no_production_code_path_calls_record_publication():
    """It exists for Stage 6 and shadow runs; nothing live may invoke it yet.

    Looks for an actual CALL — `record_publication(` — rather than any mention,
    so re-exporting the name from agent/editorial/__init__.py does not read as
    a caller. An import is not an invocation.
    """
    import subprocess

    result = subprocess.run(
        ["grep", "-rn", r"record_publication(", "--include=*.py",
         "scripts/", "agent/"],
        cwd=ROOT, capture_output=True, text=True)
    callers = [ln for ln in result.stdout.splitlines()
               if "agent/editorial/publication_record.py" not in ln]
    assert callers == [], f"unexpected caller(s): {callers}"


def test_the_export_is_not_mistaken_for_a_caller():
    """Guards the test above from being trivially satisfied by a bad filter."""
    import agent.editorial as E

    assert "record_publication" in E.__all__
    assert callable(E.record_publication)
