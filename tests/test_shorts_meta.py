"""Tests for pitch_agent.shorts_meta — metadata generation + template selection."""
import pytest

from pitch_agent import shorts_meta as sm

DATA = {
    "home": "England", "away": "Croatia", "competition": "World Cup 2026",
    "leader": "England", "verdict": "England to win", "confidence": 58,
    "factors": ["England's attack rates higher", "Croatia controls midfield",
                "First goal swings it"],
    "ledger": "16-10 · 61.5%",
}

META_FIELDS = {"short_title", "youtube_title", "youtube_description",
               "pinned_comment", "hashtags", "hook_variant", "cta_text"}


def test_select_template_known_and_fallback():
    assert sm.select_template("match-tension")[0] == "match-tension"
    # unknown / None fall back to the default variant
    assert sm.select_template("nope")[0] == sm.DEFAULT_VARIANT
    assert sm.select_template(None)[0] == sm.DEFAULT_VARIANT


@pytest.mark.parametrize("variant", list(sm.VARIANTS))
def test_metadata_has_all_required_fields(variant):
    meta = sm.generate_metadata(DATA, variant)
    assert META_FIELDS <= set(meta)
    assert meta["variant"] == variant
    assert all(meta[f] for f in META_FIELDS)          # nothing empty
    assert isinstance(meta["hashtags"], list) and meta["hashtags"]


def test_hook_is_football_first_not_creator_first():
    # The lead hook must NOT open with "I built ..." (creator-first)
    for variant in sm.VARIANTS:
        hook = sm.generate_metadata(DATA, variant)["hook"]
        assert not hook.lower().startswith("i built")
    # key-factor uses the exact match-focused headline
    assert sm.generate_metadata(DATA, "key-factor")["hook"] == \
        "One stat changed the England vs Croatia prediction."


def test_at_least_three_hook_variants_structured():
    variants = sm.generate_hook_variants(DATA)
    assert len(variants) >= 3
    assert all({"hook_variant", "hook"} <= set(v) for v in variants)
    # the football-first types we promised are present
    ids = {v["hook_variant"] for v in variants}
    assert {"factor_first", "match_tension", "result_curiosity"} <= ids


@pytest.mark.parametrize("variant", list(sm.VARIANTS) + [None])
def test_no_betting_language_anywhere(variant):
    meta = sm.generate_metadata(DATA, variant)
    blob = " ".join([
        meta["hook"], meta["subheadline"], meta["short_title"],
        meta["youtube_title"], meta["youtube_description"],
        meta["pinned_comment"], meta["cta_text"], *meta["hashtags"],
    ]).lower()
    for w in sm.BETTING_WORDS:
        assert w not in blob, f"banned word {w!r} leaked into metadata"


def test_assert_no_betting_raises():
    with pytest.raises(sm.BettingLanguageError):
        sm.assert_no_betting("our best bet to win")
    with pytest.raises(sm.BettingLanguageError):
        sm.assert_no_betting("guaranteed lock of the day")
    # clean copy passes
    sm.assert_no_betting("the model favors England by a narrow margin")


def test_draw_has_no_leader_crash():
    draw = dict(DATA, leader=None, verdict="Too close to call")
    meta = sm.generate_metadata(draw, "key-factor")
    assert meta["hook"]  # still produces a football-first hook
