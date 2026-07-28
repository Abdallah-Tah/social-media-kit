"""Tests for the article format registry (scripts/content_formats.py).

The point of the registry is that consecutive posts don't share a shape, so
these tests mostly guard the rotation and the per-format gating.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

import content_formats as CF


@pytest.fixture
def history(tmp_path, monkeypatch):
    """Point the rotation state at a throwaway file."""
    path = tmp_path / "format_history.json"
    monkeypatch.setattr(CF, "HISTORY_PATH", str(path))
    return path


# Minimum length floor per registry kind. The live lanes keep the original 800.
# `editorial` is lower on purpose: the intelligence brief is assembled from
# ContentDecision records and may contain nothing that is not in a record, so an
# 800-word floor would be a standing instruction to pad it with invented prose.
# The floor still exists — it is just set where the shortest honest artifact
# lands rather than where a long-form article does.
MIN_WORDS_FLOOR = {"news": 800, "tutorial": 800, "editorial": 500}


def test_every_format_is_well_formed():
    for kind, table in CF.REGISTRY.items():
        for fid, spec in table.items():
            assert spec["sections"], f"{kind}/{fid} has no sections"
            assert len(set(spec["sections"])) == len(spec["sections"]), \
                f"{kind}/{fid} repeats a section"
            assert all(s.startswith("## ") for s in spec["sections"])
            assert spec["angle"] and spec["title_hint"]
            assert spec["min_words"] >= MIN_WORDS_FLOOR[kind], \
                f"{kind}/{fid} below the {kind} floor"


def test_the_live_lanes_keep_their_original_length_floor():
    """Guards the scoping above from quietly relaxing production standards."""
    assert MIN_WORDS_FLOOR["news"] == 800
    assert MIN_WORDS_FLOOR["tutorial"] == 800
    for kind in ("news", "tutorial"):
        for fid, spec in CF.REGISTRY[kind].items():
            assert spec["min_words"] >= 800, f"{kind}/{fid}"


def test_every_editorial_format_carries_a_sources_section():
    """Traceability is the point of the whole editorial layer."""
    for fid, spec in CF.EDITORIAL_FORMATS.items():
        assert any(s in ("## Sources", "## Primary Sources") for s in spec["sections"]), fid


def test_tutorial_split_divides_sections():
    for fid, spec in CF.TUTORIAL_FORMATS.items():
        assert 0 < spec["split"] < len(spec["sections"]), f"{fid} split is out of range"
        assert spec["brief_a"] and spec["brief_b"]


def test_news_formats_end_on_watching_and_carry_sources():
    for fid, spec in CF.NEWS_FORMATS.items():
        assert spec["sections"][-1] == "## What I'll Be Watching", fid
        assert "## Sources" in spec["sections"], fid


def test_no_two_formats_share_a_skeleton():
    """The whole point — identical bones across formats would defeat the rotation."""
    for kind, table in CF.REGISTRY.items():
        seen = {}
        for fid, spec in table.items():
            key = tuple(spec["sections"])
            assert key not in seen, f"{kind}: {fid} duplicates {seen.get(key)}"
            seen[key] = fid


def test_pick_format_rotates_away_from_recent(history):
    kind = "tutorial"
    picks = []
    for _ in range(4):
        fid = CF.pick_format(kind)
        CF.record(kind, fid, f"slug-{fid}")
        picks.append(fid)
    assert len(set(picks)) == len(picks), f"format repeated inside the cooldown: {picks}"


def test_pick_format_prefers_never_used(history):
    kind = "news"
    for fid in list(CF.NEWS_FORMATS)[:-1]:
        CF.record(kind, fid, f"slug-{fid}")
    unused = list(CF.NEWS_FORMATS)[-1]
    assert CF.pick_format(kind) == unused


def test_pick_format_survives_exhausted_registry(history):
    """Every format used recently must still yield a pick, not raise."""
    for fid in CF.NEWS_FORMATS:
        CF.record("news", fid, f"slug-{fid}")
    assert CF.pick_format("news") in CF.NEWS_FORMATS


def test_pick_format_honours_exclude(history):
    excluded = set(list(CF.TUTORIAL_FORMATS)[:3])
    for _ in range(10):
        assert CF.pick_format("tutorial", exclude=excluded) not in excluded


def test_format_for_slug_returns_latest_record(history):
    CF.record("tutorial", "benchmark", "my-post")
    CF.record("tutorial", "debug_story", "other-post")
    assert CF.format_for_slug("tutorial", "my-post") == "benchmark"
    assert CF.format_for_slug("tutorial", "missing") is None


def test_history_survives_a_corrupt_file(history):
    history.write_text("{not json", encoding="utf-8")
    assert CF.load_history() == {}
    CF.record("news", "context", "s")  # must not raise
    assert CF.format_for_slug("news", "s") == "context"


def _body_for(kind, format_id, words=1500, code_blocks=8):
    spec = CF.get(kind, format_id)
    filler = " ".join(["word"] * (words // max(len(spec["sections"]), 1)))
    parts = [f"# Title"]
    for section in spec["sections"]:
        parts.append(f"{section}\n\n{filler}")
    parts.append("\n\n".join("```python\nx = 1\n```" for _ in range(code_blocks)))
    return "\n\n".join(parts)


def test_quality_issues_passes_a_conforming_body():
    for kind, table in CF.REGISTRY.items():
        for fid in table:
            body = _body_for(kind, fid)
            assert CF.quality_issues(kind, body, fid) == [], f"{kind}/{fid}: {body[:80]}"


def test_quality_issues_flags_the_wrong_skeleton():
    """A debug_story body must FAIL the build_along gate — the old code's bug."""
    body = _body_for("tutorial", "debug_story")
    assert CF.quality_issues("tutorial", body, "build_along")
    assert CF.quality_issues("tutorial", body, "debug_story") == []


def test_quality_issues_flags_hype_and_thinness():
    body = _body_for("news", "whats_new")
    assert any("forbidden phrase" in i
               for i in CF.quality_issues("news", body + "\n\nThis is groundbreaking.", "whats_new"))
    thin = _body_for("news", "whats_new", words=50)
    assert any("below" in i for i in CF.quality_issues("news", thin, "whats_new"))


def test_every_banned_phrase_has_a_replacement():
    """Without a swap the news lane can only bin the draft, not repair it."""
    missing = [p for p in CF.FORBIDDEN_PHRASES if p not in CF.FORBIDDEN_REPLACEMENTS]
    assert not missing, f"no replacement for: {missing}"


def test_clean_forbidden_removes_every_banned_phrase():
    text = " ".join(f"This is {p}." for p in CF.FORBIDDEN_PHRASES)
    cleaned = CF.clean_forbidden(text).lower()
    assert not [p for p in CF.FORBIDDEN_PHRASES if p in cleaned]


def test_clean_forbidden_prefers_the_longest_match():
    """'seamless' must not chew the middle out of 'seamlessly'."""
    assert "ly" not in CF.clean_forbidden("It works seamlessly.").replace("without extra work", "")
    assert CF.clean_forbidden("unlock the power of X") == "get the most out of X"


def test_news_lane_reuses_the_shared_replacement_map():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
    import news_publish

    cleaned = news_publish.clean_forbidden_phrases("Developers should stay tuned for a robust release.")
    assert "stay tuned" not in cleaned.lower()
    assert "robust" not in cleaned.lower()
    assert news_publish.news_quality_issues(cleaned) == [
        i for i in news_publish.news_quality_issues(cleaned) if "forbidden phrase" not in i
    ]


def test_quality_issues_flags_missing_code_blocks():
    body = _body_for("tutorial", "from_scratch", code_blocks=1)
    assert any("code blocks" in i for i in CF.quality_issues("tutorial", body, "from_scratch"))


def test_detect_format_identifies_a_known_skeleton():
    assert CF.detect_format("tutorial", _body_for("tutorial", "migration_diary")) == "migration_diary"
    assert CF.detect_format("news", _body_for("news", "claim_check")) == "claim_check"


def test_detect_format_declines_to_guess_on_unknown_shapes():
    assert CF.detect_format("tutorial", "# T\n\n## Random\n\ntext\n\n## Other\n\ntext") is None


def test_get_falls_back_for_unknown_format_id():
    spec = CF.get("tutorial", "no-such-format")
    assert spec["id"] in CF.TUTORIAL_FORMATS


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        CF.formats_for("podcast")


def test_title_rules_ban_the_old_openers():
    rules = CF.title_rules(CF.get("tutorial", "build_along"))
    for opener in ("building", "mastering", "getting started"):
        assert opener in rules.lower()


def test_every_social_shape_is_well_formed():
    for sid, shape in CF.SOCIAL_SHAPES.items():
        assert shape["label"] and shape["structure"], sid
        # The fallback is .format()ed with a single `value` placeholder.
        rendered = shape["fallback"].format(value="X")
        assert "X" in rendered and "{" not in rendered, sid


def test_social_shapes_are_distinct():
    structures = [s["structure"] for s in CF.SOCIAL_SHAPES.values()]
    assert len(set(structures)) == len(structures)
    # Fallbacks must also differ on their FIRST line — that's the only part a
    # reader sees before the "see more" fold.
    openers = [s["fallback"].format(value="V").split("\n")[0] for s in CF.SOCIAL_SHAPES.values()]
    assert len(set(openers)) == len(openers), f"shared opening line: {openers}"


def test_pick_social_shape_rotates(history):
    picks = []
    for _ in range(4):
        sid = CF.pick_social_shape()
        CF.record("social", sid, f"https://example.com/{sid}")
        picks.append(sid)
    assert len(set(picks)) == len(picks), f"social shape repeated: {picks}"


def test_social_shape_falls_back_on_unknown_id():
    assert CF.social_shape("nope")["id"] in CF.SOCIAL_SHAPES


def test_social_copy_uses_the_rotating_shape(history, monkeypatch):
    """With no API key, make_social_copy must still emit a shaped post with the link."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
    import social_copy

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    body = "# T\n\n## Wiring The Queue\n\ntext\n"
    seen = set()
    for _ in range(4):
        post = social_copy.make_social_copy("A Title", body, "https://example.com/x")
        assert "https://example.com/x" in post
        assert "#BuildWithAbdallah" in post
        assert "{value}" not in post
        seen.add(post.split("\n")[0])
    # Four consecutive posts must open four different ways — the rotation is
    # recorded even on the fallback path, so it cannot repeat inside a cycle.
    assert len(seen) == 4, f"fallback copy repeated a shape: {seen}"


def test_outline_slices_by_split():
    spec = CF.get("tutorial", "build_along")
    first = CF.outline(spec, 0, spec["split"])
    second = CF.outline(spec, spec["split"])
    assert spec["sections"][0] in first
    assert spec["sections"][0] not in second
    assert spec["sections"][-1] in second
