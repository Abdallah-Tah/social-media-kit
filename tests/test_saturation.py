"""Phase 1 Stage 3 — deterministic topic-saturation prevention.

Source confidence asks whether a candidate is well evidenced. Saturation asks
whether SMKit has already said this. A perfectly evidenced story can still be
the fifth OpenAI post this week.

Two properties these tests exist to hold:
  * only CONFIRMED successful publications count — rejected, shadow, simulated,
    failed, and draft decisions are diagnostics, never saturation;
  * a material development prevents rejection on entity/theme recency ALONE.
    It never bypasses exact-topic duplication and never publishes anything.
"""
import copy
import datetime as dt
import os
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from agent.editorial import saturation as S  # noqa: E402
from agent.editorial.models import Candidate, SourceRef  # noqa: E402
from agent.editorial.saturation import (  # noqa: E402
    CONFIG_PATH,
    STATUS_CLEAR,
    STATUS_REJECT,
    STATUS_WARNING,
    THEME_UNKNOWN,
    ContinuationClaim,
    SaturationConfigError,
    build_history,
    evaluate_saturation,
    load_index,
    load_saturation_config,
    relationship_observability,
    save_index,
)

NOW = dt.datetime(2026, 7, 27, 16, 0, tzinfo=dt.timezone.utc)  # 12:00 New York


@pytest.fixture
def config():
    return load_saturation_config(CONFIG_PATH)


@pytest.fixture
def raw_config():
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def row(topic, entity, development, days_ago=1, publication_id=None,
        artifact="news", slot="", stage="publish", decision="accepted",
        mode=None, status=None, hours_ago=0, theme=None, reason_code=""):
    stamp = (NOW - dt.timedelta(days=days_ago, hours=hours_ago)).isoformat()
    meta = {"canonical_topic_id": topic, "entity": entity,
            "development_type": development, "artifact_type": artifact,
            "published_at": stamp, "slot": slot,
            "publication_id": publication_id or f"{topic}@{days_ago}"}
    if mode:
        meta["mode"] = mode
    if status:
        meta["status"] = status
    if theme:
        meta["theme"] = theme
    return {"stage": stage, "decision": decision, "job_id": "t", "title": topic,
            "ts": stamp, "reason_code": reason_code, "metadata": meta}


def candidate(topic="openai:model_release:gpt-6", entity="openai",
              development="model_release", artifact="news", **kw):
    return Candidate(canonical_topic_id=topic, subject_org=entity,
                     development_type=development, content_kind=artifact, **kw)


def evaluate(cand, rows, config, **kwargs):
    return evaluate_saturation(cand, history=build_history(rows, config),
                               config=config, now=NOW, **kwargs)


def firing(result):
    return {o.rule_id: o.reason for o in result.rules if o.status != STATUS_CLEAR}


def problems_from(tmp_path, data):
    path = tmp_path / "sat.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(SaturationConfigError) as exc:
        load_saturation_config(path)
    return exc.value.problems


# ── R1: exact topic ─────────────────────────────────────────────────────────

def test_an_exact_topic_inside_the_cooldown_is_rejected(config):
    rows = [row("openai:model_release:gpt-5", "openai", "model_release", days_ago=3)]
    result = evaluate(candidate(topic="openai:model_release:gpt-5"), rows, config)

    assert result.status == STATUS_REJECT
    assert firing(result)["R1"] == "exact_topic_republished_within_cooldown"
    assert result.exact_topic_count == 1


def test_an_exact_topic_outside_the_cooldown_is_clear(config):
    rows = [row("openai:model_release:gpt-5", "openai", "model_release", days_ago=30)]
    result = evaluate(candidate(topic="openai:model_release:gpt-5"), rows, config)

    assert next(o for o in result.rules if o.rule_id == "R1").status == STATUS_CLEAR
    assert result.exact_topic_count == 0


def test_different_developments_from_one_entity_are_different_topics(config):
    """openai:model_release:gpt-5 must not block openai:pricing_change:2026-07."""
    rows = [row("openai:model_release:gpt-5", "openai", "model_release", days_ago=2)]
    result = evaluate(
        candidate(topic="openai:pricing_change:2026-07", development="pricing_change"),
        rows, config)
    assert next(o for o in result.rules if o.rule_id == "R1").status == STATUS_CLEAR


def test_a_material_development_does_not_bypass_exact_topic_duplication(config):
    """R1 is the one rule material exceptions never reach past."""
    rows = [row("openai:security_issue:2026-07", "openai", "security_issue", days_ago=2)]
    result = evaluate(
        candidate(topic="openai:security_issue:2026-07", development="security_issue"),
        rows, config)

    assert result.material_exception.applied is True
    assert result.status == STATUS_REJECT
    assert firing(result)["R1"] == "exact_topic_republished_within_cooldown"


# ── R2: same editorial day ──────────────────────────────────────────────────

def test_a_same_day_follow_up_is_rejected_by_default(config):
    rows = [row("openai:model_release:gpt-5", "openai", "model_release",
                days_ago=0, hours_ago=4)]
    result = evaluate(candidate(topic="openai:model_release:gpt-5"), rows, config,
                      slot="midday_authority")
    assert firing(result)["R2"] == "same_day_topic_reuse"


def test_an_explicit_distinct_follow_up_passes_r2(config):
    rows = [row("openai:model_release:gpt-5", "openai", "model_release",
                days_ago=0, hours_ago=4)]
    result = evaluate(
        candidate(topic="openai:model_release:gpt-5"), rows, config,
        slot="practical_takeaway",
        continuation=ContinuationClaim(links_to_earlier_item=True,
                                       materially_distinct_objective=True))
    r2 = next(o for o in result.rules if o.rule_id == "R2")
    assert r2.status == STATUS_WARNING
    assert r2.reason == "same_day_continuation_permitted"


def test_a_continuation_in_a_slot_that_does_not_allow_it_is_rejected(config):
    rows = [row("openai:model_release:gpt-5", "openai", "model_release",
                days_ago=0, hours_ago=4)]
    result = evaluate(
        candidate(topic="openai:model_release:gpt-5"), rows, config,
        slot="intelligence_brief",
        continuation=ContinuationClaim(links_to_earlier_item=True,
                                       materially_distinct_objective=True))
    assert firing(result)["R2"] == "same_day_topic_reuse"


def test_a_partial_continuation_claim_is_rejected(config):
    """Every required condition must hold, not just one."""
    rows = [row("openai:model_release:gpt-5", "openai", "model_release",
                days_ago=0, hours_ago=4)]
    result = evaluate(
        candidate(topic="openai:model_release:gpt-5"), rows, config,
        slot="practical_takeaway",
        continuation=ContinuationClaim(links_to_earlier_item=True))
    assert firing(result)["R2"] == "same_day_topic_reuse"


# ── R3: entity share ────────────────────────────────────────────────────────

def busy_entity_rows(entity="openai", n=5, total=12, development="general_news"):
    rows = [row(f"{entity}:{development}:{i}", entity, development, days_ago=i + 1,
                publication_id=f"{entity}-{i}") for i in range(n)]
    rows += [row(f"other{i}:general_news:{i}", f"other{i}", "general_news",
                 days_ago=i + 1, publication_id=f"other-{i}")
             for i in range(total - n)]
    return rows


def test_the_last_twelve_entity_share_threshold_fires(config):
    rows = busy_entity_rows(n=5, total=12)   # 5/12 = 0.4167 > 0.33
    result = evaluate(candidate(topic="openai:general_news:new",
                                development="general_news"), rows, config)

    r3 = next(o for o in result.rules if o.rule_id == "R3")
    assert r3.status == STATUS_REJECT
    assert r3.reason == "entity_share_exceeded"
    assert r3.detail["share"] == pytest.approx(0.4167, abs=0.001)
    assert r3.detail["threshold"] == 0.33
    assert result.entity_count_last_12 == 5


def test_an_entity_under_the_share_ceiling_is_clear(config):
    rows = busy_entity_rows(n=2, total=12)   # 2/12 = 0.167
    result = evaluate(candidate(topic="openai:general_news:new",
                                development="general_news"), rows, config)
    assert next(o for o in result.rules if o.rule_id == "R3").status == STATUS_CLEAR


def test_share_rules_do_not_apply_below_the_minimum_sample(config):
    """Two posts out of three is 0.67 and means nothing."""
    rows = busy_entity_rows(n=2, total=3)
    result = evaluate(candidate(topic="openai:general_news:new",
                                development="general_news"), rows, config)

    assert next(o for o in result.rules if o.rule_id == "R3").status == STATUS_CLEAR
    assert S.WARN_SMALL_SAMPLE in result.warnings


def test_the_rolling_fourteen_day_share_threshold_fires(config):
    """Beyond the last-12 window but inside 14 days."""
    rows = [row(f"openai:general_news:{i}", "openai", "general_news",
                days_ago=1, hours_ago=i, publication_id=f"o-{i}") for i in range(6)]
    rows += [row(f"x{i}:general_news:{i}", f"x{i}", "general_news",
                 days_ago=2, hours_ago=i, publication_id=f"x-{i}") for i in range(8)]
    result = evaluate(candidate(topic="openai:general_news:new",
                                development="general_news"), rows, config)

    r3 = next(o for o in result.rules if o.rule_id == "R3")
    assert r3.status == STATUS_REJECT
    assert result.entity_count_14d == 6


# ── Material exceptions ─────────────────────────────────────────────────────

def test_a_new_pricing_change_bypasses_entity_recency_only(config):
    rows = busy_entity_rows(n=5, total=12)
    result = evaluate(
        candidate(topic="openai:pricing_change:2026-08", development="pricing_change"),
        rows, config)

    r3 = next(o for o in result.rules if o.rule_id == "R3")
    assert r3.status == STATUS_WARNING, "saturation is still reported"
    assert r3.reason == "entity_share_exceeded_but_material"
    assert result.material_exception.applied is True
    assert result.material_exception.type == "pricing_change"
    assert result.status != STATUS_REJECT


def test_a_security_issue_bypasses_entity_recency_only(config):
    rows = busy_entity_rows(n=5, total=12)
    result = evaluate(
        candidate(topic="openai:security_issue:2026-08", development="security_issue"),
        rows, config)

    assert result.material_exception.type == "security_issue"
    assert next(o for o in result.rules if o.rule_id == "R3").status == STATUS_WARNING
    assert result.status != STATUS_REJECT


def test_a_non_material_event_from_a_saturated_entity_is_rejected(config):
    rows = busy_entity_rows(n=5, total=12)
    result = evaluate(candidate(topic="openai:general_news:new",
                                development="general_news"), rows, config)
    assert result.material_exception.applied is False
    assert result.status == STATUS_REJECT


def test_the_material_exception_is_recorded_with_its_reason(config):
    rows = busy_entity_rows(n=5, total=12)
    result = evaluate(
        candidate(topic="openai:pricing_change:2026-08", development="pricing_change"),
        rows, config, evidence_references=["https://vendor.com/pricing"])
    exception = result.material_exception.to_dict()

    assert exception["applied"] is True
    assert exception["reason"]
    assert exception["evidence_references"] == ["https://vendor.com/pricing"]


# ── R7: evidence update ─────────────────────────────────────────────────────

def test_new_evidence_allows_reconsideration_of_an_exact_topic(config):
    rows = [row("openai:model_release:gpt-5", "openai", "model_release", days_ago=3)]
    result = evaluate(
        candidate(topic="openai:model_release:gpt-5"), rows, config,
        evidence_update_types=["benchmark_reproduction"],
        evidence_references=["https://lab.dev/repro"])

    r1 = next(o for o in result.rules if o.rule_id == "R1")
    assert r1.status == STATUS_WARNING
    assert r1.reason == "exact_topic_reconsidered_on_new_evidence"
    assert result.status != STATUS_REJECT


def test_the_evidence_exception_is_recorded_with_references(config):
    rows = [row("openai:model_release:gpt-5", "openai", "model_release", days_ago=3)]
    result = evaluate(
        candidate(topic="openai:model_release:gpt-5"), rows, config,
        evidence_update_types=["contradictory_results"],
        evidence_references=["https://lab.dev/a", "https://lab.dev/b"])

    r7 = next(o for o in result.rules if o.rule_id == "R7")
    assert r7.status == STATUS_WARNING
    assert r7.detail["evidence_types"] == ["contradictory_results"]
    assert len(r7.detail["evidence_references"]) == 2


def test_an_unconfigured_evidence_type_is_ignored(config):
    rows = [row("openai:model_release:gpt-5", "openai", "model_release", days_ago=3)]
    result = evaluate(candidate(topic="openai:model_release:gpt-5"), rows, config,
                      evidence_update_types=["vibes"])
    assert result.status == STATUS_REJECT


# ── R4: entity + development ────────────────────────────────────────────────

def test_the_entity_development_count_threshold_fires(config):
    rows = [row(f"acme:general_news:{i}", "acme", "general_news", days_ago=i + 1,
                publication_id=f"a-{i}") for i in range(3)]
    result = evaluate(candidate(topic="acme:general_news:new", entity="acme",
                                development="general_news"), rows, config)

    r4 = next(o for o in result.rules if o.rule_id == "R4")
    assert r4.status == STATUS_REJECT
    assert r4.reason == "entity_development_count_exceeded"
    assert r4.detail["threshold"] == 3


def test_the_entity_development_count_is_scoped_to_that_development(config):
    rows = [row(f"acme:general_news:{i}", "acme", "general_news", days_ago=i + 1,
                publication_id=f"a-{i}") for i in range(3)]
    result = evaluate(candidate(topic="acme:compatibility_change:1", entity="acme",
                                development="compatibility_change"), rows, config)
    assert next(o for o in result.rules if o.rule_id == "R4").status != STATUS_REJECT


# ── R5: theme ───────────────────────────────────────────────────────────────

def test_theme_saturation_fires(config):
    """openai, anthropic, google all map to ai_models."""
    entities = ["openai", "anthropic", "google", "mistral", "huggingface"]
    rows = [row(f"{e}:general_news:{i}", e, "general_news", days_ago=i + 1,
                publication_id=f"{e}-{i}") for i, e in enumerate(entities)]
    rows += [row(f"laravel:general_news:{i}", "laravel", "general_news",
                 days_ago=i + 1, publication_id=f"l-{i}") for i in range(3)]
    result = evaluate(candidate(topic="anthropic:general_news:new", entity="anthropic",
                                development="general_news"), rows, config)

    r5 = next(o for o in result.rules if o.rule_id == "R5")
    assert r5.status == STATUS_REJECT
    assert r5.reason == "theme_share_exceeded"
    assert r5.detail["theme"] == "ai_models"
    assert result.theme_count_14d == 5


def test_a_missing_theme_skips_the_rule_explicitly(config):
    rows = [row(f"acme{i}:general_news:{i}", f"acme{i}", "general_news",
                days_ago=i + 1, publication_id=f"a-{i}") for i in range(8)]
    result = evaluate(candidate(topic="acme9:general_news:new", entity="acme9",
                                development="general_news"), rows, config)

    r5 = next(o for o in result.rules if o.rule_id == "R5")
    assert r5.status == STATUS_CLEAR
    assert r5.reason == "theme_unknown_rule_skipped"
    assert S.WARN_THEME_UNKNOWN in result.warnings


def test_a_theme_is_never_invented_from_title_similarity(config):
    """Only an explicit map or upstream metadata is trusted."""
    cand = candidate(topic="unmapped:general_news:1", entity="unmapped",
                     development="general_news")
    result = evaluate(cand, [], config)
    assert result.observability["theme"] == THEME_UNKNOWN


def test_an_upstream_theme_in_metadata_is_used(config):
    cand = Candidate(canonical_topic_id="acme:general_news:1", subject_org="acme",
                     development_type="general_news", metadata={"theme": "databases"})
    result = evaluate(cand, [], config)
    assert result.observability["theme"] == "databases"


# ── R6: artifact repetition ─────────────────────────────────────────────────

def test_a_format_change_alone_does_not_bypass_saturation(config):
    """news -> takeaway must not buy another slot on its own."""
    rows = [row("acme:general_news:1", "acme", "general_news", days_ago=1,
                artifact="news", publication_id="a-1"),
            row("acme:general_news:2", "acme", "general_news", days_ago=2,
                artifact="news", publication_id="a-2")]
    result = evaluate(candidate(topic="acme:general_news:3", entity="acme",
                                development="general_news", artifact="tutorial"),
                      rows, config)

    r6 = next(o for o in result.rules if o.rule_id == "R6")
    assert r6.status == STATUS_REJECT
    assert r6.reason == "artifact_repetition_for_entity"
    assert r6.detail["candidate_artifact_type"] == "tutorial"


def test_artifact_repetition_yields_to_a_material_development(config):
    rows = [row("acme:general_news:1", "acme", "general_news", days_ago=1,
                publication_id="a-1"),
            row("acme:general_news:2", "acme", "general_news", days_ago=2,
                publication_id="a-2")]
    result = evaluate(candidate(topic="acme:security_issue:1", entity="acme",
                                development="security_issue"), rows, config)
    assert next(o for o in result.rules if o.rule_id == "R6").status == STATUS_WARNING


# ── History interpretation ──────────────────────────────────────────────────

def test_failed_publications_do_not_count(config):
    rows = [row("openai:model_release:gpt-5", "openai", "model_release",
                days_ago=2, status="failed")]
    history = build_history(rows, config)
    assert history.records == ()
    assert history.diagnostics["excluded_status_failed"] == 1


def test_rejected_decisions_do_not_count(config):
    rows = [row("openai:model_release:gpt-5", "openai", "model_release",
                days_ago=2, decision="rejected", reason_code="topic_saturated")]
    history = build_history(rows, config)
    assert history.records == ()
    assert history.diagnostics["rejected_decision"] == 1


def test_shadow_and_simulated_decisions_do_not_count(config):
    rows = [row("a:general_news:1", "a", "general_news", days_ago=1, mode="shadow"),
            row("b:general_news:1", "b", "general_news", days_ago=1, mode="simulated"),
            row("c:general_news:1", "c", "general_news", days_ago=1, mode="replay")]
    history = build_history(rows, config)

    assert history.records == ()
    assert history.diagnostics["excluded_mode_shadow"] == 1
    assert history.diagnostics["excluded_mode_simulated"] == 1
    assert history.diagnostics["excluded_mode_replay"] == 1


def test_non_publish_stages_do_not_count(config):
    rows = [{"stage": "topic_admission", "decision": "accepted", "job_id": "t",
             "ts": NOW.isoformat(), "metadata": {"canonical_topic_id": "a:b:c"}}]
    assert build_history(rows, config).records == ()


def test_a_publish_failed_reason_code_does_not_count(config):
    rows = [row("a:general_news:1", "a", "general_news", days_ago=1,
                reason_code="publish_failed")]
    history = build_history(rows, config)
    assert history.records == ()
    assert history.diagnostics["publish_failed"] == 1


def test_duplicate_publication_records_count_once(config):
    """A retry that refers to the same published post is one publication."""
    rows = [row("a:general_news:1", "a", "general_news", days_ago=1,
                publication_id="post-42"),
            row("a:general_news:1", "a", "general_news", days_ago=1,
                publication_id="post-42")]
    history = build_history(rows, config)

    assert len(history.records) == 1
    assert history.diagnostics["duplicate_publication_record"] == 1


def test_records_without_a_stable_key_still_dedupe_by_topic_and_day(config):
    stamp = (NOW - dt.timedelta(days=1)).isoformat()
    base = {"stage": "publish", "decision": "accepted", "job_id": "t", "ts": stamp,
            "metadata": {"canonical_topic_id": "a:general_news:1",
                         "published_at": stamp}}
    assert len(build_history([base, dict(base)], config).records) == 1


def test_legacy_records_without_a_topic_id_degrade_safely(config):
    stamp = (NOW - dt.timedelta(days=1)).isoformat()
    rows = [{"stage": "publish", "decision": "accepted", "job_id": "t",
             "title": "An old post", "ts": stamp,
             "metadata": {"published_at": stamp, "slug": "an-old-post"}}]
    history = build_history(rows, config)

    assert len(history.records) == 1
    assert history.records[0].legacy is True
    assert S.WARN_LEGACY_RECORDS in history.warnings


def test_entity_and_development_are_recovered_from_the_topic_id(config):
    stamp = (NOW - dt.timedelta(days=1)).isoformat()
    rows = [{"stage": "publish", "decision": "accepted", "job_id": "t", "ts": stamp,
             "metadata": {"canonical_topic_id": "openai:model_release:gpt-5",
                          "published_at": stamp, "publication_id": "p1"}}]
    record = build_history(rows, config).records[0]
    assert record.entity == "openai"
    assert record.development_type == "model_release"


def test_malformed_and_undated_rows_are_counted_not_crashed_on(config):
    rows = ["not a dict", {"stage": "publish", "decision": "accepted",
                           "metadata": {"published_at": "nonsense"}}]
    history = build_history(rows, config)
    assert history.records == ()
    assert history.diagnostics["malformed"] == 1
    assert history.diagnostics["unparseable_timestamp"] == 1


def test_an_empty_history_is_reported_and_never_rejects(config):
    result = evaluate(candidate(), [], config)
    assert S.WARN_NO_HISTORY in result.warnings
    assert result.status == STATUS_CLEAR


# ── Timezone and DST ────────────────────────────────────────────────────────

def test_a_utc_date_boundary_stays_on_the_same_new_york_editorial_day(config):
    """02:00 UTC on the 28th is 22:00 on the 27th in New York."""
    assert S._editorial_day(
        dt.datetime(2026, 7, 28, 2, 0, tzinfo=dt.timezone.utc),
        config.timezone) == "2026-07-27"


def test_dst_spring_forward_editorial_days(config):
    """2026-03-08: clocks jump 02:00 EST -> 03:00 EDT."""
    before = dt.datetime(2026, 3, 8, 6, 0, tzinfo=dt.timezone.utc)   # 01:00 EST
    after = dt.datetime(2026, 3, 8, 8, 0, tzinfo=dt.timezone.utc)    # 04:00 EDT
    assert S._editorial_day(before, config.timezone) == "2026-03-08"
    assert S._editorial_day(after, config.timezone) == "2026-03-08"
    # 03:00 UTC is still the previous evening in New York.
    assert S._editorial_day(
        dt.datetime(2026, 3, 8, 3, 0, tzinfo=dt.timezone.utc),
        config.timezone) == "2026-03-07"


def test_dst_fall_back_editorial_days(config):
    """2026-11-01: clocks fall back 02:00 EDT -> 01:00 EST, so 01:00 happens twice."""
    first = dt.datetime(2026, 11, 1, 5, 0, tzinfo=dt.timezone.utc)   # 01:00 EDT
    second = dt.datetime(2026, 11, 1, 6, 0, tzinfo=dt.timezone.utc)  # 01:00 EST
    assert S._editorial_day(first, config.timezone) == "2026-11-01"
    assert S._editorial_day(second, config.timezone) == "2026-11-01"
    assert S._editorial_day(
        dt.datetime(2026, 11, 1, 3, 0, tzinfo=dt.timezone.utc),
        config.timezone) == "2026-10-31"


def test_same_day_reuse_uses_the_editorial_day_not_the_utc_day(config):
    """A 02:00 UTC post is the same NY editorial day as a 22:00 UTC one."""
    late_ny = dt.datetime(2026, 7, 28, 2, 0, tzinfo=dt.timezone.utc)
    stamp = late_ny.isoformat()
    rows = [{"stage": "publish", "decision": "accepted", "job_id": "t", "ts": stamp,
             "metadata": {"canonical_topic_id": "openai:model_release:gpt-5",
                          "entity": "openai", "development_type": "model_release",
                          "published_at": stamp, "publication_id": "p1"}}]
    evaluated_at = dt.datetime(2026, 7, 27, 23, 0, tzinfo=dt.timezone.utc)  # 19:00 NY
    result = evaluate_saturation(
        candidate(topic="openai:model_release:gpt-5"),
        history=build_history(rows, config), config=config, now=evaluated_at,
        slot="midday_authority")
    assert firing(result)["R2"] == "same_day_topic_reuse"


def test_the_saturation_timezone_inherits_the_slot_configuration(config):
    from agent.editorial.slots import load_slots

    assert config.timezone == load_slots().timezone == "America/New_York"


# ── Cache / index ───────────────────────────────────────────────────────────

def test_the_cache_round_trips_to_the_same_result(config, tmp_path):
    rows = busy_entity_rows(n=5, total=12)
    history = build_history(rows, config)
    path = tmp_path / "index.json"
    save_index(history, path)

    cached = load_index(history.fingerprint, path)
    assert cached is not None
    assert [r.to_dict() for r in cached.records] == \
        [r.to_dict() for r in history.records]

    cand = candidate(topic="openai:general_news:new", development="general_news")
    fresh = evaluate_saturation(cand, history=history, config=config, now=NOW)
    from_cache = evaluate_saturation(cand, history=cached, config=config, now=NOW)
    assert fresh.to_dict() == from_cache.to_dict()


def test_the_cache_is_discarded_when_the_source_history_changes(config, tmp_path):
    path = tmp_path / "index.json"
    original = build_history(busy_entity_rows(n=5, total=12), config)
    save_index(original, path)

    changed = build_history(busy_entity_rows(n=5, total=12)
                            + [row("new:general_news:1", "new", "general_news",
                                   days_ago=0, publication_id="n-1")], config)
    assert changed.fingerprint != original.fingerprint
    assert load_index(changed.fingerprint, path) is None


def test_a_corrupt_or_versionless_cache_is_discarded(config, tmp_path):
    path = tmp_path / "index.json"
    path.write_text("{ not json", encoding="utf-8")
    assert load_index("anything", path) is None
    path.write_text('{"index_version": 999, "source_fingerprint": "x"}',
                    encoding="utf-8")
    assert load_index("x", path) is None


def test_deleting_the_cache_loses_no_history(config, tmp_path):
    """The index is derived; authoritative history lives in the decision log."""
    rows = busy_entity_rows(n=5, total=12)
    path = tmp_path / "index.json"
    save_index(build_history(rows, config), path)
    path.unlink()

    assert load_index("whatever", path) is None
    assert len(build_history(rows, config).records) == 12


def test_the_cache_is_never_written_by_evaluation(config, tmp_path, monkeypatch):
    monkeypatch.setattr(S, "INDEX_PATH", tmp_path / "index.json")
    evaluate(candidate(), busy_entity_rows(), config)
    assert not (tmp_path / "index.json").exists()


# ── Determinism and purity ──────────────────────────────────────────────────

def test_the_same_input_produces_identical_output(config):
    rows = busy_entity_rows(n=5, total=12)
    cand = candidate(topic="openai:general_news:new", development="general_news")
    first = evaluate(cand, rows, config).to_dict()
    for _ in range(5):
        assert evaluate(cand, rows, config).to_dict() == first


def test_history_order_does_not_change_the_result(config):
    rows = busy_entity_rows(n=5, total=12)
    cand = candidate(topic="openai:general_news:new", development="general_news")
    assert evaluate(cand, rows, config).to_dict() == \
        evaluate(cand, list(reversed(rows)), config).to_dict()


def test_evaluation_makes_no_llm_or_network_call(config, monkeypatch):
    import urllib.request

    import agent.llm_ops as LLM

    def explode(*a, **k):
        raise AssertionError("saturation must not call an LLM or the network")

    monkeypatch.setattr(LLM, "chat", explode)
    monkeypatch.setattr(LLM, "requests", type("R", (), {"post": staticmethod(explode)}))
    monkeypatch.setattr(urllib.request, "urlopen", explode)

    assert evaluate(candidate(), busy_entity_rows(), config)


def test_evaluation_writes_no_production_history(config, monkeypatch):
    import agent.content_decisions as CD

    def explode(*a, **k):
        raise AssertionError("saturation must not write decisions")

    monkeypatch.setattr(CD, "record", explode)
    monkeypatch.setattr(CD, "accept", explode)
    monkeypatch.setattr(CD, "reject", explode)
    assert evaluate(candidate(), busy_entity_rows(), config)


def test_the_result_carries_every_documented_field(config):
    result = evaluate(candidate(), busy_entity_rows(), config).to_dict()
    for key in ("status", "rules", "exact_topic_count", "entity_count_14d",
                "entity_count_last_12", "development_type_count_14d",
                "theme_count_14d", "material_exception", "history_fingerprint",
                "warnings", "observability", "version"):
        assert key in result, key


# ── Observability retention ─────────────────────────────────────────────────

def test_the_result_retains_fields_for_the_agreed_metrics(config):
    rows = busy_entity_rows(n=5, total=12)
    obs = evaluate(candidate(topic="openai:general_news:new",
                             development="general_news"), rows, config).observability

    for key in ("entity", "theme", "development_type", "artifact_type", "slot",
                "rule_statuses", "rejecting_rules", "material_exception_applied",
                "exact_topic_repeat", "history_size", "history_diagnostics"):
        assert key in obs, key
    assert obs["rejecting_rules"], "saturation_rejections_by_rule must be derivable"


def test_relationship_observability_retains_the_stage_two_six_limitation():
    """Fields needed for relationship_unknown_rate and its confidence impact."""
    from agent.editorial.source_relationships import (
        detect_relationships, load_relationship_config)

    cand = Candidate(url="https://a.dev/x", sources=(
        SourceRef(url="https://a.dev/x", excerpt=""),
        SourceRef(url="https://b.dev/y", excerpt="x" * 150),
    ))
    relationships = detect_relationships(
        cand.sources, config=load_relationship_config())
    obs = relationship_observability(cand, relationships)

    assert obs["source_count"] == 2
    assert obs["relationship_unknown_count"] >= 1
    assert obs["excerpt_present_count"] == 1
    assert obs["excerpt_length_buckets"]["0"] == 1
    assert obs["excerpt_length_buckets"]["100-299"] == 1
    assert "relationship_unknown_by_domain" in obs
    assert "relationship_unknown_by_source_kind" in obs
    assert "source_confidence_score" in obs


# ── Configuration validation ────────────────────────────────────────────────

def test_the_shipped_config_loads(config):
    assert config.version == 1
    assert config.rolling_days == 14 and config.recent_items == 12
    assert config.material_types


def test_disabling_the_exact_topic_rule_is_rejected(tmp_path, raw_config):
    raw_config["rules"]["R1_exact_topic"]["enabled"] = False
    assert any("R1_exact_topic.enabled must be true" in p
               for p in problems_from(tmp_path, raw_config))


def test_a_share_ceiling_of_one_is_rejected_as_a_silent_disable(tmp_path, raw_config):
    raw_config["rules"]["R3_entity_share"]["last_12_ceiling"] = 1.0
    assert any("silently disables the rule" in p
               for p in problems_from(tmp_path, raw_config))


@pytest.mark.parametrize("value", [-0.2, 1.5, "high"])
def test_out_of_range_share_thresholds_are_rejected(tmp_path, raw_config, value):
    raw_config["rules"]["R5_theme_share"]["ceiling_14d"] = value
    assert any("ceiling_14d" in p for p in problems_from(tmp_path, raw_config))


@pytest.mark.parametrize("value", [-1, 0])
def test_negative_or_zero_windows_are_rejected(tmp_path, raw_config, value):
    raw_config["windows"]["rolling_days"] = value
    assert any("rolling_days" in p for p in problems_from(tmp_path, raw_config))


def test_an_unknown_development_type_is_rejected(tmp_path, raw_config):
    raw_config["material_development_types"].append("teleportation")
    assert any("unknown development type(s): teleportation" in p
               for p in problems_from(tmp_path, raw_config))


def test_marking_every_development_type_material_is_rejected(tmp_path, raw_config):
    from agent.editorial.models import DEVELOPMENT_TYPES

    raw_config["material_development_types"] = list(DEVELOPMENT_TYPES)
    assert any("disables saturation entirely" in p
               for p in problems_from(tmp_path, raw_config))


def test_an_unknown_slot_in_the_continuation_list_is_rejected(tmp_path, raw_config):
    raw_config["rules"]["R2_same_day_reuse"]["allow_continuation_slots"] = ["nope"]
    assert any("unknown slot(s): nope" in p for p in problems_from(tmp_path, raw_config))


def test_an_empty_continuation_condition_list_is_rejected(tmp_path, raw_config):
    raw_config["rules"]["R2_same_day_reuse"]["require_all_of"] = []
    assert any("require_all_of" in p for p in problems_from(tmp_path, raw_config))


def test_an_unknown_rule_name_is_rejected(tmp_path, raw_config):
    raw_config["rules"]["R9_vibes"] = {"enabled": True}
    assert any("unknown rule(s): R9_vibes" in p for p in problems_from(tmp_path, raw_config))


def test_a_missing_rule_is_rejected(tmp_path, raw_config):
    del raw_config["rules"]["R5_theme_share"]
    assert any("missing rule(s): R5_theme_share" in p
               for p in problems_from(tmp_path, raw_config))


def test_disabling_every_rule_is_rejected(tmp_path, raw_config):
    for rule in raw_config["rules"].values():
        rule["enabled"] = False
    problems = problems_from(tmp_path, raw_config)
    assert any("every rule is disabled" in p for p in problems)


def test_removing_deduplication_keys_is_rejected(tmp_path, raw_config):
    raw_config["history"]["deduplication_keys"] = []
    assert any("deduplication_keys" in p for p in problems_from(tmp_path, raw_config))


def test_an_invalid_timezone_is_rejected(tmp_path, raw_config):
    raw_config["timezone"] = "Mars/Olympus_Mons"
    assert any("unknown timezone" in p for p in problems_from(tmp_path, raw_config))


def test_an_unsupported_version_is_rejected(tmp_path, raw_config):
    raw_config["version"] = 99
    assert any("unsupported version" in p for p in problems_from(tmp_path, raw_config))


def test_a_missing_config_file_is_reported(tmp_path):
    with pytest.raises(SaturationConfigError) as exc:
        load_saturation_config(tmp_path / "absent.yaml")
    assert any("not found" in p for p in exc.value.problems)


def test_validation_reports_every_problem_at_once(tmp_path, raw_config):
    broken = copy.deepcopy(raw_config)
    broken["version"] = 99
    broken["rules"]["R1_exact_topic"]["enabled"] = False
    broken["windows"]["recent_items"] = -1
    broken["timezone"] = "Nowhere/Nothing"
    assert len(problems_from(tmp_path, broken)) >= 4


# ── Dormancy ────────────────────────────────────────────────────────────────

def test_stage_three_changes_nothing_while_the_flag_is_false():
    import content_formats as CF
    from agent.editorial import editorial_slots_enabled

    assert editorial_slots_enabled() is False
    assert len(CF.NEWS_FORMATS) == 8
    assert not (set(CF.EDITORIAL_FORMATS) & set(CF.NEWS_FORMATS))
