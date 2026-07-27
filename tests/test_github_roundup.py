"""Tests for the weekly GitHub roundup pillar.

The load-bearing property is honesty: every star figure must come from the
scraped page, and the headline must describe what is actually in the list.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import github_roundup as GR

ROW = """<article class="Box-row">
  <h2 class="h3 lh-condensed"><a href="/acme/{name}"><span>acme /</span> {name}</a></h2>
  <p class="col-9 color-fg-muted my-1 pr-4">{desc}</p>
  <span itemprop="programmingLanguage">Python</span>
  <span class="d-inline-block float-sm-right">{stars} stars this week</span>
</article>"""


def _page(rows):
    return "<html>" + "".join(rows) + "</html>"


def _row(name, stars, desc="A tool."):
    return ROW.format(name=name, stars=stars, desc=desc)


class FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(GR, "LEDGER", str(tmp_path / "roundups.json"))
    return tmp_path / "roundups.json"


def test_scrape_parses_name_delta_description_language(monkeypatch):
    monkeypatch.setattr(GR.requests, "get",
                        lambda *a, **k: FakeResp(_page([_row("widget", "1,234", "An LLM agent.")])))
    items = GR.scrape_trending()
    assert len(items) == 1
    it = items[0]
    assert it["full_name"] == "acme/widget"
    assert it["name"] == "widget"
    assert it["weekly_stars"] == 1234
    assert it["url"] == "https://github.com/acme/widget"
    assert it["description"] == "An LLM agent."
    assert it["language"] == "Python"


def test_rows_without_a_weekly_delta_are_dropped_not_guessed(monkeypatch):
    """A repo with no scrapeable number must vanish, never get an estimate."""
    broken = '<article class="Box-row"><h2><a href="/acme/x">acme / x</a></h2></article>'
    monkeypatch.setattr(GR.requests, "get",
                        lambda *a, **k: FakeResp(_page([broken, _row("good", "50")])))
    items = GR.scrape_trending()
    assert [i["name"] for i in items] == ["good"]


def test_collect_sorts_by_weekly_stars(monkeypatch):
    rows = [_row("low", "10", "An AI model."), _row("high", "900", "An AI agent."),
            _row("mid", "100", "An LLM tool."), _row("a", "5", "AI rag."),
            _row("b", "7", "AI prompt.")]
    monkeypatch.setattr(GR.requests, "get", lambda *a, **k: FakeResp(_page(rows)))
    items, topic = GR.collect("ai", limit=10)
    assert [i["name"] for i in items] == ["high", "mid", "low", "b", "a"]
    assert topic == "ai"


def test_thin_topic_falls_back_to_all_rather_than_mislabelling(monkeypatch):
    """The old behaviour padded an 'AI' list with unrelated repos. It must not."""
    rows = [_row("onlyai", "100", "An LLM agent.")] + [
        _row(f"plain{i}", str(50 - i), "A media server.") for i in range(6)
    ]
    monkeypatch.setattr(GR.requests, "get", lambda *a, **k: FakeResp(_page(rows)))
    items, topic = GR.collect("ai", limit=10)
    assert topic == "all", "thin AI week must not be published as an AI roundup"
    title, _slug, _body = GR.build_article(items, topic)
    assert "AI" not in title
    assert "Open-Source" in title


def test_article_totals_match_the_scraped_numbers(monkeypatch):
    rows = [_row("a", "100", "An AI agent."), _row("b", "250", "An LLM tool."),
            _row("c", "25", "AI rag."), _row("d", "10", "AI model."),
            _row("e", "5", "AI prompt.")]
    monkeypatch.setattr(GR.requests, "get", lambda *a, **k: FakeResp(_page(rows)))
    items, topic = GR.collect("ai", limit=10)
    title, slug, body = GR.build_article(items, topic)

    assert "390" in body, "the stated total must equal the sum of the parts"
    assert title.startswith("5 ")
    assert slug.startswith("github-ai-roundup-")
    for it in items:
        assert it["url"] in body
        assert f"{it['weekly_stars']:,}" in body
    assert "## Sources" in body and "## What I'll Be Watching" in body


def test_social_post_carries_every_repo_and_the_total(monkeypatch):
    rows = [_row(f"r{i}", str(100 - i), "An AI agent.") for i in range(5)]
    monkeypatch.setattr(GR.requests, "get", lambda *a, **k: FakeResp(_page(rows)))
    items, topic = GR.collect("ai", limit=10)
    post = GR.build_social(items, "https://buildwithabdallah.com/tutorials/x", topic)

    assert str(sum(i["weekly_stars"] for i in items)) in post.replace(",", "")
    for rank, it in enumerate(items, 1):
        assert f"{rank}. {it['name']}" in post
        assert it["url"] in post
    assert "buildwithabdallah.com" in post


def test_no_banned_hype_in_generated_copy(monkeypatch):
    import content_formats as CF

    rows = [_row(f"r{i}", str(100 - i), "An AI agent.") for i in range(5)]
    monkeypatch.setattr(GR.requests, "get", lambda *a, **k: FakeResp(_page(rows)))
    items, topic = GR.collect("ai", limit=10)
    _t, _s, body = GR.build_article(items, topic)
    post = GR.build_social(items, "https://example.com/x", topic)

    for text in (body, post):
        assert not [p for p in CF.FORBIDDEN_PHRASES if p in text.lower()]


def test_ledger_roundtrips_and_bounds_growth(ledger):
    GR.record_roundup("slug-1", [{"full_name": "acme/one"}])
    GR.record_roundup("slug-2", [{"full_name": "acme/two"}])
    assert GR.previously_featured(weeks=2) == {"acme/one", "acme/two"}
    assert GR.previously_featured(weeks=1) == {"acme/two"}

    for i in range(40):
        GR.record_roundup(f"s{i}", [{"full_name": f"acme/{i}"}])
    assert len(GR._load_ledger()["runs"]) == 30


def test_ledger_survives_a_corrupt_file(ledger):
    ledger.write_text("{broken", encoding="utf-8")
    assert GR._load_ledger() == {}
    GR.record_roundup("s", [{"full_name": "acme/x"}])  # must not raise
    assert GR.previously_featured() == {"acme/x"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
