"""Tests for clean article-text extraction (agent/editorial/content_cleaning.py)."""
from __future__ import annotations

from pathlib import Path

from agent.editorial.content_cleaning import clean_article_text, clean_fetched_evidence


def test_navigation_heavy_news_page():
    """Boilerplate nav/header/sidebar/footer/cookie wall is stripped; the article remains."""
    html = """
    <html><head><title>News</title></head><body>
    <nav><ul><li>Home</li><li>About</li><li>Contact</li></ul></nav>
    <header><div class="logo">SiteLogo</div><div class="menu">Menu items here</div></header>
    <aside class="sidebar"><div>Trending stories</div><div>Related articles</div></aside>
    <article><h1>Breaking: New AI Model Released</h1>
    <p>The new AI model achieves state-of-the-art performance on multiple benchmarks,
    according to the research team. The model demonstrates significant improvements
    in reasoning and coding tasks across a wide range of evaluations.</p></article>
    <footer><div class="copyright">Copyright 2026</div><div class="footer-links">Links</div></footer>
    <div class="cookie-banner">We use cookies. Accept cookies to continue.</div>
    </body></html>
    """
    r = clean_article_text(html)
    assert r["usable_text"] is True
    assert r["extraction_method"] == "article_body"
    assert "state-of-the-art performance" in r["clean_text"]
    assert "Trending stories" not in r["clean_text"]
    assert "We use cookies" not in r["clean_text"]
    assert "Copyright 2026" not in r["clean_text"]
    assert r["clean_content_chars"] < r["raw_content_chars"]
    assert r["boilerplate_ratio"] > 0


def test_documentation_page():
    """Structured documentation content is extracted; chrome is removed."""
    html = """
    <html><body>
    <nav><div>Docs navigation menu</div></nav>
    <div class="md-content"><h2>Installation Guide</h2>
    <p>To install the package, run pip install example. Then configure your
    environment by setting the API key in your environment variables. The
    package supports Python 3.9 and above and requires an active connection.</p></div>
    <footer><div>Footer content</div></footer>
    </body></html>
    """
    r = clean_article_text(html)
    assert r["usable_text"] is True
    assert "pip install example" in r["clean_text"]
    assert "Docs navigation menu" not in r["clean_text"]


def test_github_release_page():
    """A GitHub release page yields the release notes, not the repo chrome."""
    html = """
    <html><body>
    <header><div class="Header">GitHub header bar</div></header>
    <nav class="UnderlineNav"><div>Repository navigation tabs</div></nav>
    <div class="release"><h2>v2.0.0</h2>
    <div class="markdown-body"><p>This release adds support for new features
    including improved performance and bug fixes. The release also includes
    breaking changes to the API that require a migration step.</p></div></div>
    <aside class="sidebar"><div>Sponsors list</div></aside>
    </body></html>
    """
    r = clean_article_text(html)
    assert r["usable_text"] is True
    assert "improved performance and bug fixes" in r["clean_text"]
    assert "GitHub header bar" not in r["clean_text"]
    assert "Sponsors list" not in r["clean_text"]


def test_research_abstract():
    """A research paper abstract is extracted."""
    html = """
    <html><body>
    <header><div class="site-header">Journal header</div></header>
    <article><h1>Deep Learning for Code Generation</h1>
    <div class="abstract"><h2>Abstract</h2>
    <p>We present a novel approach to code generation using deep learning.
    Our method achieves state-of-the-art results on the HumanEval benchmark,
    demonstrating a 2x improvement over prior work. We evaluate our approach
    on multiple programming languages and show consistent improvements.</p></div>
    </article>
    <footer><div class="site-footer">Journal footer</div></footer>
    </body></html>
    """
    r = clean_article_text(html)
    assert r["usable_text"] is True
    assert "novel approach to code generation" in r["clean_text"]
    assert "Journal header" not in r["clean_text"]


def test_empty_page():
    r = clean_article_text("")
    assert r["usable_text"] is False
    assert r["failure_reason"] == "empty_content"
    assert r["clean_content_chars"] == 0

    r2 = clean_article_text("   \n  \t ")
    assert r2["usable_text"] is False
    assert r2["failure_reason"] == "empty_content"


def test_cookie_wall_page():
    """A cookie consent wall is removed; the article behind it is extracted."""
    html = """
    <html><body>
    <div class="cookie-consent"><div class="cookie-banner">We use cookies to improve your
    experience. By continuing to use this site you agree to our use of cookies. Please
    accept cookies to continue browsing. Our cookie policy applies to all visitors.</div></div>
    <article><h1>Article Title</h1><p>This is the actual article content that provides
    valuable information about the topic. The article discusses important developments
    and provides detailed analysis of the situation at hand.</p></article>
    </body></html>
    """
    r = clean_article_text(html)
    assert r["usable_text"] is True
    assert "We use cookies" not in r["clean_text"]
    assert "actual article content" in r["clean_text"]


def test_malformed_html_does_not_crash():
    html = "<html><body><div><p>Unclosed tags <span>some content here"
    r = clean_article_text(html)
    assert isinstance(r, dict)
    assert "clean_text" in r
    assert "usable_text" in r


def test_size_limit_applied_after_cleaning():
    """The size limit is applied to the cleaned text, not the raw HTML."""
    article_text = "The quick brown fox jumps over the lazy dog. " * 1000  # ~45k chars
    html = (f"<html><body><nav>{'menu item ' * 5000}</nav>"
            f"<article>{article_text}</article></body></html>")
    r = clean_article_text(html, max_chars=1000)
    assert r["usable_text"] is True
    assert r["clean_content_chars"] <= 1000
    assert r["raw_content_chars"] > 1000


def test_evidence_quote_found_in_clean_text():
    """A verbatim quote from the article body survives cleaning."""
    html = """
    <html><body>
    <nav><div>Navigation menu</div></nav>
    <article><h1>Product Launch</h1>
    <p>The new model achieves a 2x performance improvement on coding benchmarks.</p>
    </article>
    <footer><div>Footer content</div></footer>
    </body></html>
    """
    r = clean_article_text(html)
    assert "2x performance improvement on coding benchmarks" in r["clean_text"]


def test_feed_summary_fallback_for_js_rendered_page():
    """A JS-rendered page (no readable body) falls back to the feed summary."""
    html = """
    <html><body>
    <script>var data = {article: "Content rendered by JavaScript, not in the HTML."};</script>
    <div id="root"></div>
    </body></html>
    """
    fallback = "The product was released with significant improvements according to the announcement."
    r = clean_article_text(html, fallback_text=fallback)
    assert r["usable_text"] is True
    assert r["extraction_method"] == "feed_summary"
    assert "significant improvements" in r["clean_text"]


def test_clean_fetched_evidence_returns_diagnostics():
    fetched = [
        {"url": "https://a.com/1", "content": "<html><body><nav>menu</nav>"
            "<article>" + "GPT-5 has native tool use and strong performance. " * 20 + "</article></body></html>"},
        {"url": "https://b.com/2", "content": ""},
    ]
    cleaned, diags = clean_fetched_evidence(fetched, fallback_text="A short summary.")
    assert len(cleaned) == 2
    assert len(diags) == 2
    # First source: article body extracted.
    assert diags[0]["extraction_method"] == "article_body"
    assert diags[0]["usable_text"] is True
    assert "native tool use" in cleaned[0]["content"]
    # Diagnostics carry the required fields.
    for d in diags:
        for key in ("raw_content_chars", "clean_content_chars", "extraction_method",
                    "boilerplate_ratio", "usable_text", "failure_reason"):
            assert key in d
    # Empty source is flagged unusable.
    assert diags[1]["usable_text"] is False


def test_no_publisher_or_notification_side_effects():
    """The cleaning module imports no publisher or notification modules."""
    import ast
    import agent.editorial.content_cleaning as cc
    tree = ast.parse(Path(cc.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    forbidden = {"linkedin_poster", "x_poster", "twitter", "telegram",
                 "newsletter", "facebook", "blog_publisher", "notifier"}
    assert not (imported & forbidden), f"forbidden imports: {imported & forbidden}"


class TestSourceQualityFilter:
    """The pre-extraction source-quality filter records skip reasons with no LLM call."""

    def test_aggregator_redirect_skipped(self):
        from agent.editorial.content_cleaning import assess_source_quality, SKIP_AGGREGATOR_REDIRECT
        diag = {"usable_text": True, "failure_reason": None}
        usable, reason = assess_source_quality(
            "https://news.google.com/rss/articles/xyz", "<html>...</html>", diag, set())
        assert usable is False
        assert reason == SKIP_AGGREGATOR_REDIRECT

    def test_unsupported_domain_skipped(self):
        from agent.editorial.content_cleaning import assess_source_quality, SKIP_UNSUPPORTED_DOMAIN
        diag = {"usable_text": True, "failure_reason": None}
        usable, reason = assess_source_quality(
            "https://reddit.com/r/programming/x", "<html>...</html>", diag, set())
        assert usable is False
        assert reason == SKIP_UNSUPPORTED_DOMAIN

    def test_javascript_only_skipped(self):
        from agent.editorial.content_cleaning import assess_source_quality, SKIP_JAVASCRIPT_ONLY
        diag = {"usable_text": True, "failure_reason": None}
        js_html = '<html><body><div id="root"></div><script>var x=1;</script></body></html>'
        usable, reason = assess_source_quality(
            "https://example.com/page", js_html, diag, set())
        assert usable is False
        assert reason == SKIP_JAVASCRIPT_ONLY

    def test_insufficient_text_skipped(self):
        from agent.editorial.content_cleaning import assess_source_quality, SKIP_INSUFFICIENT_TEXT
        diag = {"usable_text": False, "failure_reason": "insufficient_clean_text"}
        usable, reason = assess_source_quality(
            "https://example.com/page", "<html>short</html>", diag, set())
        assert usable is False
        assert reason == SKIP_INSUFFICIENT_TEXT

    def test_no_readable_content_skipped(self):
        from agent.editorial.content_cleaning import assess_source_quality, SKIP_NO_READABLE_CONTENT
        diag = {"usable_text": False, "failure_reason": "empty_content"}
        usable, reason = assess_source_quality(
            "https://example.com/page", "", diag, set())
        assert usable is False
        assert reason == SKIP_NO_READABLE_CONTENT

    def test_duplicate_source_skipped(self):
        from agent.editorial.content_cleaning import assess_source_quality, SKIP_DUPLICATE_SOURCE
        from agent.feed import canonical_url
        diag = {"usable_text": True, "failure_reason": None}
        url = "https://example.com/article?utm_source=x"
        seen = {canonical_url(url)}
        usable, reason = assess_source_quality(url, "<html>content</html>", diag, seen)
        assert usable is False
        assert reason == SKIP_DUPLICATE_SOURCE

    def test_usable_direct_source_passes(self):
        from agent.editorial.content_cleaning import assess_source_quality
        diag = {"usable_text": True, "failure_reason": None}
        usable, reason = assess_source_quality(
            "https://openai.com/blog/gpt-5",
            "<html><article>Real article content here.</article></html>", diag, set())
        assert usable is True
        assert reason is None
