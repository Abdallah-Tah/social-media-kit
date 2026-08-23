"""Tests for platform-specific roundup rendering.

The load-bearing property is that a reader can check the post against the data:
the count in the headline must equal the entries printed below it, and the stated
total must equal their sum. Those are computed in Python precisely so a model
cannot drift them apart.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import social_formatters as SF
from social_formatters import (
    LinkedInRoundupFormatter,
    XPostTooLong,
    XRoundupFormatter,
    build_roundup_content,
    x_weighted_len,
)

ARTICLE = "https://buildwithabdallah.com/tutorials/github-roundup-2026-08-23"


def _repo(name, stars, desc="A developer tool.", owner="acme", **kw):
    data = {
        "full_name": f"{owner}/{name}",
        "name": name,
        "url": f"https://github.com/{owner}/{name}",
        "description": desc,
        "language": "Python",
        "weekly_stars": stars,
    }
    data.update(kw)
    return data


def _content(items, article_url=ARTICLE, **kw):
    # use_llm=False keeps every test deterministic and offline; the LLM path is
    # additive prose only and is covered separately.
    return build_roundup_content(items, article_url=article_url, topic="all",
                                 label="open-source", use_llm=False, **kw)


@pytest.fixture
def ten():
    return [_repo(f"proj{i}", 1000 - i * 50, f"Tool number {i}.") for i in range(10)]


# ── content model: ranking, counting, totals ────────────────────────────────

def test_entries_are_ranked_by_star_gain_descending():
    c = _content([_repo("low", 10), _repo("high", 900), _repo("mid", 100)])
    assert [e.name for e in c.entries] == ["high", "mid", "low"]
    assert [e.rank for e in c.entries] == [1, 2, 3]


def test_count_and_total_are_computed_from_the_dataset(ten):
    c = _content(ten)
    assert c.count == 10
    assert c.total_stars == sum(r["weekly_stars"] for r in ten)
    assert str(c.count) in c.headline()
    assert f"{c.total_stars:,}" in c.headline()


def test_headline_count_always_equals_rendered_entries(ten):
    """The "10 repositories" / 9-shown mismatch this exists to prevent."""
    post = LinkedInRoundupFormatter().render(_content(ten))
    rendered = [ln for ln in post.splitlines() if " — +" in ln and " ⭐" in ln]
    assert len(rendered) == 10
    assert post.startswith(_content(ten).hook[:10])
    assert "10 projects gained" in post


def test_duplicate_repositories_are_dropped_before_totalling():
    dupe = _repo("same", 500)
    c = _content([dupe, dict(dupe), _repo("other", 100)])
    assert c.count == 2
    assert c.total_stars == 600, "a duplicate must not be counted twice"


def test_repository_without_a_usable_url_is_dropped():
    bad = _repo("broken", 900)
    bad["url"] = "not-a-url"
    c = _content([bad, _repo("good", 100)])
    assert [e.name for e in c.entries] == ["good"]
    assert c.count == 1 and c.total_stars == 100


def test_fewer_than_ten_repositories(ten):
    c = _content(ten[:3])
    post = LinkedInRoundupFormatter().render(c)
    assert c.count == 3
    assert "3 projects gained" in post
    assert "4." not in post


def test_more_than_ten_repositories(ten):
    extra = ten + [_repo(f"x{i}", 5 + i) for i in range(8)]
    c = _content(extra)
    assert c.count == 18
    post = LinkedInRoundupFormatter().render(c)
    assert "18 projects gained" in post
    assert f"{c.total_stars:,}" in post


def test_single_repository_uses_singular_wording():
    assert "1 project gained" in _content([_repo("solo", 42)]).headline()


# ── LinkedIn rendering ──────────────────────────────────────────────────────

def test_linkedin_includes_rank_name_stars_summary_and_url(ten):
    post = LinkedInRoundupFormatter().render(_content(ten))
    for e in _content(ten).entries:
        assert f"{e.rank}. {e.name} — +{e.weekly_stars:,} ⭐" in post
        assert f"🔗 {e.url}" in post
        assert e.description in post


def test_linkedin_includes_the_article_url_and_cta(ten):
    post = LinkedInRoundupFormatter().render(_content(ten))
    assert ARTICLE in post
    assert "📖 Full breakdown:" in post
    assert "💡 What stood out" in post
    assert post.rstrip().endswith("#SoftwareEngineering")


def test_linkedin_uses_plain_urls_not_markdown_links(ten):
    post = LinkedInRoundupFormatter().render(_content(ten))
    assert "](" not in post, "markdown links do not render on LinkedIn"
    assert "[" not in post


def test_hashtags_stay_within_a_reasonable_count(ten):
    post = LinkedInRoundupFormatter().render(_content(ten))
    assert 3 <= post.count("#") <= 5


def test_missing_article_url_is_omitted_never_fabricated(ten):
    post = LinkedInRoundupFormatter().render(_content(ten, article_url=""))
    assert "buildwithabdallah.com" not in post
    assert "Full breakdown" not in post


def test_missing_description_renders_without_inventing_one():
    c = _content([_repo("bare", 500, desc=""), _repo("described", 100)])
    post = LinkedInRoundupFormatter().render(c)
    assert "1. bare — +500 ⭐" in post
    assert "🔗 https://github.com/acme/bare" in post
    # The line straight after the bare entry must be its URL: no filler sentence.
    lines = post.splitlines()
    assert lines[lines.index("1. bare — +500 ⭐") + 1].startswith("🔗 ")


def test_github_description_noise_is_cleaned_but_prose_survives():
    from social_formatters import clean_description
    assert clean_description(
        "😎 Awesome lists [NOTE: PRs are disabled until I catch up]"
    ) == "Awesome lists"
    # GitHub's own truncation marker goes; an ordinary full stop stays.
    assert clean_description("A downloader…") == "A downloader"
    assert clean_description("A downloader.") == "A downloader."
    assert clean_description("") == ""


def test_intro_names_at_most_three_categories_with_correct_casing():
    c = _content([
        _repo("selfhost", 500, "Self-hosted media server."),
        _repo("agent", 400, "An AI LLM agent framework."),
        _repo("cli", 300, "A CLI devtool."),
        _repo("flow", 200, "A workflow automation platform."),
        _repo("list", 100, "An awesome curated collection."),
    ])
    assert c.intro.count(",") <= 2, "six categories reads as a tag dump"
    assert "ai and llm" not in c.intro, "must not lowercase an acronym"
    assert c.intro[0].isupper()


def test_special_characters_survive_rendering():
    c = _content([_repo("c++-tools", 700, desc='Handles "quotes", <tags> & emoji 🚀.'),
                  _repo("naïve-ui", 300, desc="A UI library — with an em dash.")])
    post = LinkedInRoundupFormatter().render(c)
    assert "c++-tools" in post and "naïve-ui" in post
    assert '"quotes", <tags> & emoji 🚀.' in post
    assert "em dash" in post


# ── X rendering ─────────────────────────────────────────────────────────────

def test_x_weighted_length_counts_urls_as_23():
    long_url = "https://github.com/some-org/some-really-long-repository-name-here"
    assert len(long_url) > 23
    assert x_weighted_len(long_url) == 23


def test_every_thread_post_is_within_the_limit(ten):
    posts = XRoundupFormatter().render_thread(_content(ten))
    assert len(posts) > 1
    for p in posts:
        assert x_weighted_len(p) <= 280, f"{x_weighted_len(p)} > 280:\n{p}"


def test_thread_numbering_is_sequential_and_totals_match(ten):
    posts = XRoundupFormatter().render_thread(_content(ten))
    total = len(posts)
    for i, p in enumerate(posts, 1):
        assert p.rstrip().endswith(f"🧵 {i}/{total}")


def test_thread_covers_every_repository_exactly_once(ten):
    c = _content(ten)
    joined = "\n".join(XRoundupFormatter().render_thread(c))
    for e in c.entries:
        assert joined.count(e.url) == 1, f"{e.url} appeared more than once"


def test_thread_never_splits_a_url(ten):
    c = _content(ten)
    for p in XRoundupFormatter().render_thread(c):
        for token in p.split():
            if token.startswith("https://"):
                assert any(token == e.url or token == c.article_url
                           for e in c.entries), f"mangled URL: {token}"


def test_first_post_carries_the_hook_and_totals(ten):
    posts = XRoundupFormatter().render_thread(_content(ten))
    assert "10 projects gained" in posts[0]
    assert "👇" in posts[0]


def test_final_post_carries_takeaway_article_and_cta(ten):
    posts = XRoundupFormatter().render_thread(_content(ten))
    last = posts[-1]
    assert "💡 Takeaway:" in last
    assert ARTICLE in last
    assert last.rstrip().endswith(f"🧵 {len(posts)}/{len(posts)}")


def test_a_small_roundup_that_fits_stays_one_post():
    c = _content([_repo("a", 100, desc="Short.")], article_url="")
    posts = XRoundupFormatter().render_thread(c)
    assert len(posts) == 1
    assert "🧵" not in posts[0]


def test_x_is_not_a_truncation_of_the_linkedin_post(ten):
    """Sharing a hook is fine; sharing a *shape* is not.

    The two renderers must differ structurally, not by where the text was cut.
    """
    c = _content(ten)
    linkedin = LinkedInRoundupFormatter().render(c)
    posts = XRoundupFormatter().render_thread(c)
    joined = "\n".join(posts)

    assert "#OpenSource" in linkedin and "#OpenSource" not in joined
    assert "💡 What stood out" in linkedin and "💡 What stood out" not in joined
    assert "💡 Takeaway:" in joined and "💡 Takeaway:" not in linkedin
    assert "🧵" in joined and "🧵" not in linkedin
    # No X post is a verbatim slice of the LinkedIn post.
    for p in posts:
        assert p not in linkedin


def test_impossible_entry_is_reported_not_silently_mangled():
    huge = _repo("x" * 400, 100, desc="")
    c = _content([huge])
    with pytest.raises(XPostTooLong):
        XRoundupFormatter().render_thread(c)


def test_validate_rejects_an_over_length_post():
    with pytest.raises(XPostTooLong):
        XRoundupFormatter().validate(["y" * 400])


def test_char_counts_report_index_total_and_width(ten):
    posts = XRoundupFormatter().render_thread(_content(ten))
    counts = XRoundupFormatter.char_counts(posts)
    assert [c[0] for c in counts] == list(range(1, len(posts) + 1))
    assert all(c[1] == len(posts) and c[3] == 280 for c in counts)
    assert all(0 < c[2] <= 280 for c in counts)


def test_single_post_form_stays_within_the_limit(ten):
    text = XRoundupFormatter().render_single(_content(ten))
    assert x_weighted_len(text) <= 280
    assert ARTICLE in text


def test_missing_article_url_omitted_from_the_thread(ten):
    posts = XRoundupFormatter().render_thread(_content(ten, article_url=""))
    assert "buildwithabdallah.com" not in "\n".join(posts)


# ── tone ────────────────────────────────────────────────────────────────────

def test_no_banned_hype_in_either_renderer(ten):
    import content_formats as CF
    c = _content(ten)
    texts = [LinkedInRoundupFormatter().render(c)] + XRoundupFormatter().render_thread(c)
    for text in texts:
        assert not [p for p in CF.FORBIDDEN_PHRASES if p in text.lower()]


def test_observations_are_absent_when_there_is_no_data():
    c = _content([])
    assert c.observations == []
    assert XRoundupFormatter().render_thread(c) == []


# ── the LLM path is additive, never load-bearing ────────────────────────────

def test_llm_failure_leaves_the_deterministic_post_intact(ten, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class Boom:
        ok = False
        error_class = "timeout"

    monkeypatch.setattr("agent.llm_ops.chat", lambda *a, **k: Boom())
    c = build_roundup_content(ten, article_url=ARTICLE, topic="all",
                              label="open-source", use_llm=True)
    post = LinkedInRoundupFormatter().render(c)
    assert c.count == 10 and c.total_stars == sum(r["weekly_stars"] for r in ten)
    assert "10 projects gained" in post


def test_llm_never_fills_a_blank_description(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class Ok:
        ok = True
        text = ('{"hook":"h","intro":"i","observations":["o"],"cta":"c",'
                '"summaries":{"acme/bare":"An invented description."}}')

    monkeypatch.setattr("agent.llm_ops.chat", lambda *a, **k: Ok())
    c = build_roundup_content([_repo("bare", 100, desc="")], article_url=ARTICLE,
                              topic="all", label="open-source", use_llm=True)
    assert c.entries[0].description == "", "a blank description must stay blank"


def test_llm_totals_are_ignored_even_if_returned(ten, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class Ok:
        ok = True
        text = ('{"hook":"999 projects gained 1 star","intro":"i",'
                '"observations":["o"],"cta":"c","summaries":{}}')

    monkeypatch.setattr("agent.llm_ops.chat", lambda *a, **k: Ok())
    c = build_roundup_content(ten, article_url=ARTICLE, topic="all",
                              label="open-source", use_llm=True)
    # The hook is prose and may say anything; the headline is application code.
    assert "10 projects gained" in c.headline()
    assert c.total_stars == sum(r["weekly_stars"] for r in ten)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
