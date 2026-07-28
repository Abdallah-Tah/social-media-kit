"""Phase 1 Stage 1 — proof that the editorial work is dormant.

Written and run GREEN against the registry *before* a single editorial format
existed, so the values below are a genuine record of live behaviour rather than
a description of whatever the code happens to do now.

What this protects: `pick_format('news')` runs live 5x/day on cron. It rotates
least-recently-used over `NEWS_FORMATS`, so appending entries there would
immediately change which shape every production post takes. Phase 1 must be
invisible until the approved cadence cutover.

The isolation is structural, not conditional: editorial formats live in their
own registry kind and are never members of the `news` or `tutorial` pools. That
is stronger than a flag-guarded merge, because there is no value of
EDITORIAL_SLOTS_ENABLED that can leak one into a production rotation.
"""
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import content_formats as CF  # noqa: E402

# ── Baselines captured from the unmodified registry ─────────────────────────
SEED = 20260727

LIVE_NEWS_IDS = [
    "whats_new", "upgrade_impact", "first_look", "claim_check",
    "who_should_care", "under_the_hood", "ecosystem_ripple", "context",
]
LIVE_TUTORIAL_IDS = [
    "build_along", "debug_story", "benchmark", "migration_diary",
    "head_to_head", "from_scratch", "hardening", "refactor",
]
LIVE_SOCIAL_IDS = [
    "problem_first", "one_lesson", "before_after", "common_mistake",
    "concrete_number", "open_question",
]

LIVE_NEWS_SEQUENCE = [
    "under_the_hood", "whats_new", "upgrade_impact", "ecosystem_ripple",
    "who_should_care", "context", "first_look", "claim_check",
    "under_the_hood", "whats_new", "upgrade_impact", "ecosystem_ripple",
]
LIVE_TUTORIAL_SEQUENCE = [
    "from_scratch", "build_along", "debug_story", "hardening",
    "head_to_head", "refactor", "benchmark", "migration_diary",
    "from_scratch", "build_along", "debug_story", "hardening",
]
LIVE_SOCIAL_SEQUENCE = [
    "before_after", "problem_first", "one_lesson", "concrete_number",
    "open_question", "common_mistake", "before_after", "problem_first",
    "one_lesson", "concrete_number", "open_question", "common_mistake",
]


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    """Never read or write the live content/format_history.json."""
    monkeypatch.setattr(CF, "HISTORY_PATH", str(tmp_path / "format_history.json"))
    monkeypatch.delenv("EDITORIAL_SLOTS_ENABLED", raising=False)
    yield


def drive(kind, picker, n=12):
    """Replay n picks, recording each one so LRU rotation actually advances."""
    random.seed(SEED)
    out = []
    for i in range(n):
        chosen = picker()
        out.append(chosen)
        CF.record(kind, chosen, f"slug-{i}")
    return out


# ── The registries themselves ───────────────────────────────────────────────

def test_live_registries_have_exactly_their_original_members():
    assert list(CF.NEWS_FORMATS) == LIVE_NEWS_IDS
    assert list(CF.TUTORIAL_FORMATS) == LIVE_TUTORIAL_IDS
    assert list(CF.SOCIAL_SHAPES) == LIVE_SOCIAL_IDS


def test_the_production_kinds_resolve_to_the_untouched_tables():
    assert CF.formats_for("news") is CF.NEWS_FORMATS
    assert CF.formats_for("tutorial") is CF.TUTORIAL_FORMATS


# ── The rotation sequence, which is what production actually consumes ───────

def test_news_rotation_sequence_is_byte_for_byte_unchanged():
    assert drive("news", lambda: CF.pick_format("news")) == LIVE_NEWS_SEQUENCE


def test_tutorial_rotation_sequence_is_byte_for_byte_unchanged():
    assert drive("tutorial", lambda: CF.pick_format("tutorial")) == LIVE_TUTORIAL_SEQUENCE


def test_social_rotation_sequence_is_byte_for_byte_unchanged():
    assert drive("social", CF.pick_social_shape) == LIVE_SOCIAL_SEQUENCE


@pytest.mark.parametrize("flag", ["1", "true", "0", "false", None])
def test_the_flag_cannot_influence_live_rotation_in_either_direction(monkeypatch, flag):
    """Structural isolation: even EDITORIAL_SLOTS_ENABLED=true must not leak.

    The flag governs whether editorial *slots* run. It is deliberately not a
    switch that merges formats into a production pool, so there is no setting
    that changes what the 5x/day news lane picks.
    """
    if flag is None:
        monkeypatch.delenv("EDITORIAL_SLOTS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("EDITORIAL_SLOTS_ENABLED", flag)

    assert list(CF.formats_for("news")) == LIVE_NEWS_IDS
    assert drive("news", lambda: CF.pick_format("news")) == LIVE_NEWS_SEQUENCE


# ── Disjointness ────────────────────────────────────────────────────────────

def test_editorial_formats_are_a_separate_registry_kind():
    editorial = getattr(CF, "EDITORIAL_FORMATS", None)
    if editorial is None:
        pytest.skip("EDITORIAL_FORMATS not authored yet")
    assert CF.formats_for("editorial") is editorial


def test_no_editorial_id_collides_with_a_live_format_id():
    """A collision would make get()/detect_format() ambiguous across kinds."""
    editorial = getattr(CF, "EDITORIAL_FORMATS", None)
    if editorial is None:
        pytest.skip("EDITORIAL_FORMATS not authored yet")
    live = set(CF.NEWS_FORMATS) | set(CF.TUTORIAL_FORMATS) | set(CF.SOCIAL_SHAPES)
    assert set(editorial) & live == set(), "editorial ids must be disjoint from live ids"


def test_no_editorial_format_is_reachable_from_a_production_pool():
    editorial = getattr(CF, "EDITORIAL_FORMATS", None)
    if editorial is None:
        pytest.skip("EDITORIAL_FORMATS not authored yet")
    for kind in ("news", "tutorial"):
        assert not (set(CF.formats_for(kind)) & set(editorial))
