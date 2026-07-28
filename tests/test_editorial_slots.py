"""Phase 1 Stage 1 — feature flag and slot configuration loader.

Validation is strict and happens at load. A slot naming a format id that does
not exist must fail when someone edits the file, not at 08:00 on a Tuesday when
`content_formats.get()` quietly falls back to the registry's first entry and
publishes the wrong shape.
"""
import copy
import os
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import content_formats as CF  # noqa: E402
from agent.editorial import (  # noqa: E402
    SlotConfigError,
    editorial_shadow_mode,
    editorial_slots_enabled,
    editorial_timezone,
    editorial_zoneinfo,
    load_slots,
)
from agent.editorial import flags as FLAGS  # noqa: E402

SHIPPED = os.path.join(ROOT, "config", "publishing_slots.yaml")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("EDITORIAL_SLOTS_ENABLED", "EDITORIAL_SHADOW_MODE", "EDITORIAL_TIMEZONE"):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def raw():
    with open(SHIPPED, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def write(tmp_path, data, name="slots.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def problems_from(tmp_path, data):
    with pytest.raises(SlotConfigError) as exc:
        load_slots(write(tmp_path, data))
    return exc.value.problems


# ── the feature flag ────────────────────────────────────────────────────────

def test_the_flag_is_off_by_default():
    """The safety property the whole phase rests on."""
    assert FLAGS.DEFAULT_ENABLED is False
    assert editorial_slots_enabled() is False
    assert load_slots(SHIPPED).enabled is False


def test_the_shipped_config_is_dormant(raw):
    assert raw["enabled"] is False
    assert raw["shadow_mode"] is False


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("no", False), ("off", False),
])
def test_env_overrides_the_file_in_both_directions(monkeypatch, value, expected):
    monkeypatch.setenv("EDITORIAL_SLOTS_ENABLED", value)
    assert editorial_slots_enabled() is expected
    assert load_slots(SHIPPED).enabled is expected


def test_an_unparseable_flag_value_falls_back_to_the_file(monkeypatch):
    monkeypatch.setenv("EDITORIAL_SLOTS_ENABLED", "maybe")
    assert editorial_slots_enabled() is False


def test_shadow_mode_is_independent_of_the_master_switch(monkeypatch):
    """Shadow evaluation runs for 24h while the slots themselves stay off."""
    monkeypatch.setenv("EDITORIAL_SHADOW_MODE", "true")
    assert editorial_shadow_mode() is True
    assert editorial_slots_enabled() is False


def test_the_flag_survives_an_unreadable_slots_file(monkeypatch, tmp_path):
    """A broken config must not make the kill switch unreadable."""
    bad = tmp_path / "broken.yaml"
    bad.write_text("{{{ not yaml", encoding="utf-8")
    monkeypatch.setattr(FLAGS, "SLOTS_PATH", bad)
    assert editorial_slots_enabled() is False


# ── timezone ────────────────────────────────────────────────────────────────

def test_the_editorial_timezone_is_explicit_not_the_hosts():
    assert FLAGS.DEFAULT_TIMEZONE == "America/New_York"
    assert editorial_timezone() == "America/New_York"
    assert load_slots(SHIPPED).timezone == "America/New_York"


def test_the_timezone_actually_resolves_and_observes_dst():
    """Guards against tzdata being absent on the Pi."""
    import datetime as dt

    tz = editorial_zoneinfo()
    summer = dt.datetime(2026, 7, 1, 12, tzinfo=tz).utcoffset()
    winter = dt.datetime(2026, 1, 1, 12, tzinfo=tz).utcoffset()
    assert summer != winter, "America/New_York must observe DST"
    assert summer == dt.timedelta(hours=-4)
    assert winter == dt.timedelta(hours=-5)


def test_an_unknown_timezone_is_a_config_error(tmp_path, raw):
    raw["timezone"] = "Mars/Olympus_Mons"
    assert any("unknown timezone" in p for p in problems_from(tmp_path, raw))


# ── the shipped configuration ───────────────────────────────────────────────

def test_the_shipped_config_loads_and_has_three_ordered_slots():
    cfg = load_slots(SHIPPED)
    assert [s.slot_id for s in cfg.ordered()] == [
        "intelligence_brief", "midday_authority", "practical_takeaway"]
    assert [s.publish_at for s in cfg.ordered()] == ["08:00", "12:00", "17:00"]


def test_every_weekday_resolves_to_a_content_type_for_every_slot():
    cfg = load_slots(SHIPPED)
    for day in ("monday", "tuesday", "wednesday", "thursday",
                "friday", "saturday", "sunday"):
        resolved = cfg.slots_for(day)
        assert len(resolved) == 3
        for _slot, ctype in resolved:
            assert ctype.formats or ctype.artifact


def test_the_two_sunday_artifacts_are_distinct():
    """Forward-looking trends at 12:00, retrospective report at 17:00."""
    cfg = load_slots(SHIPPED)
    sunday = dict((s.slot_id, t) for s, t in cfg.slots_for("sunday"))
    assert sunday["midday_authority"].artifact == "weekly_trend_analysis"
    assert sunday["practical_takeaway"].artifact == "weekly_intelligence_report"
    assert sunday["midday_authority"].artifact != sunday["practical_takeaway"].artifact


def test_saturday_midday_is_the_github_roundup():
    cfg = load_slots(SHIPPED)
    saturday = dict((s.slot_id, t) for s, t in cfg.slots_for("saturday"))
    assert saturday["midday_authority"].artifact == "github_roundup"


def test_admission_thresholds_match_the_approved_values():
    cfg = load_slots(SHIPPED)
    assert cfg.slots["intelligence_brief"].source_confidence_min() == 75
    assert cfg.slots["intelligence_brief"].editorial_quality_min() == 75
    assert cfg.slots["midday_authority"].source_confidence_min() == 70
    assert cfg.slots["midday_authority"].editorial_quality_min() == 80
    assert cfg.slots["practical_takeaway"].source_confidence_min() == 65
    assert cfg.slots["practical_takeaway"].editorial_quality_min() == 75


def test_no_slot_may_be_configured_to_fill_by_lowering_thresholds():
    cfg = load_slots(SHIPPED)
    assert cfg.defaults["fallback"]["on_no_candidate"] == "skip_slot"
    assert cfg.defaults["fallback"]["record_rejections"] is True


def test_every_shipped_format_id_exists_in_the_editorial_registry():
    cfg = load_slots(SHIPPED)
    for slot in cfg.slots.values():
        for ctype in slot.content_types.values():
            for fid in ctype.formats:
                assert fid in CF.EDITORIAL_FORMATS
            if ctype.artifact:
                assert ctype.artifact in CF.EDITORIAL_ARTIFACTS


# ── validation ──────────────────────────────────────────────────────────────

def test_an_unknown_format_id_is_rejected(tmp_path, raw):
    raw["slots"]["practical_takeaway"]["content_types"]["practical_takeaway"]["formats"] = [
        "takeaway_checklist", "migration_note", "does_not_exist"]
    assert any("unknown editorial format 'does_not_exist'" in p
               for p in problems_from(tmp_path, raw))


def test_referencing_a_live_production_format_is_rejected(tmp_path, raw):
    """The dormancy guarantee: editorial slots never touch a live registry."""
    raw["slots"]["midday_authority"]["content_types"]["long_form_tutorial"]["formats"] = [
        "tutorial_deep_dive", "guided_build", "build_along"]  # build_along is live
    assert any("belongs to a live production registry" in p
               for p in problems_from(tmp_path, raw))


def test_an_unknown_artifact_is_rejected(tmp_path, raw):
    raw["slots"]["midday_authority"]["content_types"]["github_roundup"]["artifact"] = "nope"
    assert any("unknown artifact 'nope'" in p for p in problems_from(tmp_path, raw))


def test_declaring_both_formats_and_an_artifact_is_rejected(tmp_path, raw):
    raw["slots"]["midday_authority"]["content_types"]["github_roundup"]["formats"] = ["x"]
    assert any("declares both formats and artifact" in p
               for p in problems_from(tmp_path, raw))


def test_a_missing_weekday_is_rejected(tmp_path, raw):
    del raw["slots"]["midday_authority"]["weekly_schedule"]["wednesday"]
    assert any("missing wednesday" in p for p in problems_from(tmp_path, raw))


def test_a_weekday_pointing_at_an_undefined_content_type_is_rejected(tmp_path, raw):
    raw["slots"]["midday_authority"]["weekly_schedule"]["tuesday"] = "mystery_type"
    assert any("undefined content type 'mystery_type'" in p
               for p in problems_from(tmp_path, raw))


def test_insufficient_variation_is_rejected(tmp_path, raw):
    """practical_takeaway runs 6x/week; one shape would be visibly repetitive."""
    raw["slots"]["practical_takeaway"]["content_types"]["practical_takeaway"]["formats"] = [
        "takeaway_checklist"]
    assert any("runs 6x/week but has 1 format(s); needs at least 3" in p
               for p in problems_from(tmp_path, raw))


def test_a_twice_weekly_type_needs_two_shapes(tmp_path, raw):
    raw["slots"]["midday_authority"]["content_types"]["technical_analysis"]["formats"] = [
        "technical_analysis"]
    assert any("runs 2x/week but has 1 format(s); needs at least 2" in p
               for p in problems_from(tmp_path, raw))


def test_a_daily_slot_without_a_schedule_needs_three_shapes(tmp_path, raw):
    raw["slots"]["intelligence_brief"]["content_types"]["intelligence_brief"]["formats"] = [
        "intelligence_brief", "signal_vs_noise"]
    assert any("runs 7x/week but has 2 format(s); needs at least 3" in p
               for p in problems_from(tmp_path, raw))


def test_a_defined_but_unscheduled_content_type_is_rejected(tmp_path, raw):
    raw["slots"]["midday_authority"]["content_types"]["orphan"] = {
        "formats": ["takeaway_checklist"]}
    assert any("never scheduled" in p for p in problems_from(tmp_path, raw))


@pytest.mark.parametrize("value", [-1, 101, "high", True])
def test_out_of_range_thresholds_are_rejected(tmp_path, raw, value):
    raw["slots"]["midday_authority"]["admission"]["source_confidence_min"] = value
    assert any("source_confidence_min" in p for p in problems_from(tmp_path, raw))


def test_a_missing_admission_threshold_is_rejected(tmp_path, raw):
    del raw["slots"]["intelligence_brief"]["admission"]["editorial_quality_min"]
    assert any("missing editorial_quality_min" in p for p in problems_from(tmp_path, raw))


def test_colliding_publish_times_are_rejected(tmp_path, raw):
    raw["slots"]["practical_takeaway"]["publish_at"] = "12:00"
    assert any("collides" in p for p in problems_from(tmp_path, raw))


def test_a_malformed_publish_time_is_rejected(tmp_path, raw):
    raw["slots"]["midday_authority"]["publish_at"] = "25:00"
    assert any("is not HH:MM" in p for p in problems_from(tmp_path, raw))


def test_order_must_match_clock_order(tmp_path, raw):
    """Otherwise `order` says one thing and the schedule does another."""
    raw["slots"]["intelligence_brief"]["order"] = 3
    raw["slots"]["practical_takeaway"]["order"] = 1
    assert any("order does not match clock order" in p
               for p in problems_from(tmp_path, raw))


def test_an_unsupported_version_is_rejected(tmp_path, raw):
    raw["version"] = 99
    assert any("unsupported version" in p for p in problems_from(tmp_path, raw))


def test_a_missing_file_is_reported_clearly(tmp_path):
    with pytest.raises(SlotConfigError) as exc:
        load_slots(tmp_path / "absent.yaml")
    assert any("not found" in p for p in exc.value.problems)


def test_an_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(SlotConfigError):
        load_slots(path)


def test_every_problem_is_reported_not_just_the_first(tmp_path, raw):
    """One edit-and-reload cycle should surface the whole list."""
    broken = copy.deepcopy(raw)
    broken["version"] = 99
    broken["timezone"] = "Nowhere/Nothing"
    broken["slots"]["midday_authority"]["publish_at"] = "99:99"
    del broken["slots"]["intelligence_brief"]["admission"]["editorial_quality_min"]

    problems = problems_from(tmp_path, broken)

    assert len(problems) >= 4
    assert any("version" in p for p in problems)
    assert any("timezone" in p for p in problems)
    assert any("HH:MM" in p for p in problems)
    assert any("editorial_quality_min" in p for p in problems)


def test_a_partially_valid_config_never_loads(tmp_path, raw):
    """Half-loading is worse than refusing: the failure would surface at 08:00."""
    raw["slots"]["practical_takeaway"]["admission"]["source_confidence_min"] = 500
    with pytest.raises(SlotConfigError):
        load_slots(write(tmp_path, raw))
