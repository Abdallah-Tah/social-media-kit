"""Clean article-text extraction (readability-style) using BeautifulSoup + lxml.

The evidence fetcher stores raw page HTML, which is dominated by navigation,
scripts, cookie walls, sidebars, and footers (often ~450k chars). Passing that
to the structured extractor wastes the input budget on chrome and yields few or
no claims. This module parses the HTML, strips boilerplate, and extracts the
primary article / documentation body BEFORE the size limit is applied.

Fallback order for usable text:
  1. main article / document body (<article>, <main>, or densest container)
  2. structured documentation content (md-content / rst-content / ...)
  3. metadata description (<meta name=description> / og:description)
  4. existing feed summary (caller-supplied fallback text)

Raw HTML is never silently treated as clean article text: if nothing usable can
be extracted, the result is flagged (usable_text=False) with a failure_reason.
"""
from __future__ import annotations

import re
from typing import Any

try:
    from bs4 import BeautifulSoup
    _HAVE_BS4 = True
except Exception:  # pragma: no cover - bs4 is a hard dependency in practice
    BeautifulSoup = None  # type: ignore
    _HAVE_BS4 = False

MIN_USABLE_CHARS = 200

_BOILERPLATE_TAGS = {
    "script", "style", "noscript", "svg", "iframe", "nav", "header", "footer",
    "aside", "form", "button", "figure", "picture", "video", "audio", "canvas",
    "template", "object", "embed",
}
_BOILERPLATE_ROLES = {
    "navigation", "banner", "contentinfo", "complementary", "search", "menu",
    "menubar", "toolbar", "dialog", "alert", "alertdialog", "tablist",
}
# Word-boundary class/id patterns for repeated page chrome. Word boundaries keep
# content words like "heading" or "gradient" from being mistaken for chrome.
_BOILERPLATE_PATTERN = re.compile(
    r"\b(nav|navbar|menu|sidebar|side-bar|footer|header|cookie|consent|gdpr|"
    r"banner|ad|ads|advert|advertis|advertisement|comment|comments|related|"
    r"share|social|breadcrumb|breadcrumbs|pagination|toc|widget|popup|modal|"
    r"newsletter|subscribe|promo|promotion|sponsor|sponsored|recirculation|"
    r"recommended|most-popular|trending|skip|toolbar|signin|signup|login|log-in)\b",
    re.I,
)
_DOC_CONTENT_PATTERN = re.compile(
    r"(md-content|rst-content|documentation|doc-content|markdown-body|"
    r"article-body|post-content|entry-content|content-body|main-content|"
    r"article-content|story-body)",
    re.I,
)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _limit(text: str, max_chars: int | None) -> str:
    if max_chars and len(text) > max_chars:
        return text[:max_chars]
    return text


def _diag(clean_text: str, raw_chars: int, method: str, usable: bool,
          failure_reason: str | None) -> dict[str, Any]:
    clean_chars = len(clean_text)
    boilerplate_ratio = round(1 - (clean_chars / raw_chars), 4) if raw_chars else 0.0
    return {
        "clean_text": clean_text,
        "raw_content_chars": raw_chars,
        "clean_content_chars": clean_chars,
        "extraction_method": method,
        "boilerplate_ratio": boilerplate_ratio,
        "usable_text": usable,
        "failure_reason": failure_reason,
    }


def _remove_boilerplate(soup: "BeautifulSoup") -> None:
    for tag_name in _BOILERPLATE_TAGS:
        for el in soup.find_all(tag_name):
            el.decompose()
    for el in soup.find_all(attrs={"role": True}):
        if str(el.get("role", "")).lower() in _BOILERPLATE_ROLES:
            el.decompose()
    for el in soup.find_all(True):
        attrs = el.attrs or {}
        cls = " ".join(attrs.get("class", []) or [])
        eid = attrs.get("id", "") or ""
        if _BOILERPLATE_PATTERN.search(cls) or _BOILERPLATE_PATTERN.search(eid):
            el.decompose()


def _extract_article_body(soup: "BeautifulSoup") -> str:
    main = soup.find("article") or soup.find("main")
    if main:
        return _collapse(main.get_text(" ", strip=True))
    # Densest content container after boilerplate removal.
    best, best_len = "", 0
    for el in soup.find_all(["div", "section", "td"]):
        text = _collapse(el.get_text(" ", strip=True))
        if len(text) > best_len:
            best, best_len = text, len(text)
    return best


def _extract_doc_content(soup: "BeautifulSoup") -> str:
    for el in soup.find_all(attrs={"class": True}):
        val = " ".join(el.get("class", []) or [])
        if _DOC_CONTENT_PATTERN.search(val):
            text = _collapse(el.get_text(" ", strip=True))
            if len(text) >= MIN_USABLE_CHARS:
                return text
    return ""


def _extract_meta_description(soup: "BeautifulSoup") -> str:
    for attr, key in (("name", "description"), ("property", "og:description")):
        meta = soup.find("meta", attrs={attr: re.compile(rf"^{re.escape(key)}$", re.I)})
        if meta and meta.get("content"):
            return _collapse(meta.get("content", ""))
    return ""


def clean_article_text(raw_html: str, source_url: str = "", fallback_text: str = "",
                       max_chars: int | None = None) -> dict[str, Any]:
    """Extract clean article text from raw HTML.

    Returns a diagnostics dict with clean_text plus raw_content_chars,
    clean_content_chars, extraction_method, boilerplate_ratio, usable_text,
    and failure_reason.
    """
    raw_chars = len(raw_html or "")
    if not raw_html or not raw_html.strip():
        return _diag("", raw_chars, "empty", False, "empty_content")

    if not _HAVE_BS4:
        if fallback_text and len(fallback_text.strip()) >= MIN_USABLE_CHARS:
            return _diag(_limit(_collapse(fallback_text), max_chars), raw_chars,
                         "feed_summary", True, None)
        return _diag("", raw_chars, "empty", False, "no_html_parser")

    try:
        soup = BeautifulSoup(raw_html, "lxml")
    except Exception as e:  # malformed HTML the parser cannot handle
        if fallback_text and len(fallback_text.strip()) >= MIN_USABLE_CHARS:
            return _diag(_limit(_collapse(fallback_text), max_chars), raw_chars,
                         "feed_summary", True, None)
        return _diag("", raw_chars, "empty", False, f"parse_error:{type(e).__name__}")

    _remove_boilerplate(soup)

    _SUBSTANTIAL = 200  # chars for a substantial article/documentation body
    _USABLE = 40        # chars for any usable clean text (e.g. a summary sentence)

    article_body = _extract_article_body(soup)
    doc_content = _extract_doc_content(soup)
    body = soup.find("body")
    whole_body = _collapse(body.get_text(" ", strip=True)) if body else _collapse(soup.get_text(" ", strip=True))
    meta_desc = _extract_meta_description(soup)
    feed_summary = _collapse(fallback_text) if fallback_text else ""

    # 1+2. Prefer an explicit article / documentation container (cleanest text).
    text, method = "", "empty"
    for candidate, m in ((article_body, "article_body"), (doc_content, "doc_content")):
        if len(candidate) >= _SUBSTANTIAL and len(candidate) > len(text):
            text, method = candidate, m
    # Fall back to the whole (boilerplate-stripped) body if no substantial container.
    if len(text) < _SUBSTANTIAL and len(whole_body) >= _SUBSTANTIAL:
        text, method = whole_body, "article_body"
    # 3+4. No substantial body: pick the longest available clean text (residual
    # article body, whole boilerplate-stripped body, metadata description, then
    # the existing feed summary). For JS-rendered pages the whole body is empty,
    # so this naturally falls through to the feed summary.
    if len(text) < _SUBSTANTIAL:
        for candidate, m in ((article_body, "article_body"), (whole_body, "article_body"),
                             (meta_desc, "meta_description"), (feed_summary, "feed_summary")):
            if candidate and len(candidate) > len(text):
                text, method = candidate, m

    text = _limit(text, max_chars)
    clean_chars = len(text)
    usable = clean_chars >= _USABLE
    return _diag(text, raw_chars, method, usable, None if usable else "insufficient_clean_text")


def clean_fetched_evidence(fetched_evidence: list[dict[str, Any]], fallback_text: str = "",
                           max_chars: int | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Clean each fetched evidence source's content.

    Returns (cleaned_evidence, diagnostics). cleaned_evidence mirrors
    fetched_evidence but with content replaced by clean text and an
    extraction_method recorded; the size limit is applied to the clean text.
    """
    cleaned: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for e in fetched_evidence:
        raw = e.get("content", "") or ""
        result = clean_article_text(raw, source_url=e.get("url", ""),
                                    fallback_text=fallback_text, max_chars=max_chars)
        entry = dict(e)
        entry["content"] = result["clean_text"]
        entry["extraction_method"] = result["extraction_method"]
        cleaned.append(entry)
        diagnostics.append({
            "url": e.get("url", ""),
            "raw_content_chars": result["raw_content_chars"],
            "clean_content_chars": result["clean_content_chars"],
            "extraction_method": result["extraction_method"],
            "boilerplate_ratio": result["boilerplate_ratio"],
            "usable_text": result["usable_text"],
            "failure_reason": result["failure_reason"],
        })
    return cleaned, diagnostics


# ── Source-quality filter (pre-extraction, no LLM call) ──────────────────────
# Skip reasons are recorded WITHOUT an LLM call so low-value pages never incur a
# paid extraction.
SKIP_AGGREGATOR_REDIRECT = "aggregator_redirect"
SKIP_NO_READABLE_CONTENT = "no_readable_content"
SKIP_JAVASCRIPT_ONLY = "javascript_only"
SKIP_INSUFFICIENT_TEXT = "insufficient_text"
SKIP_DUPLICATE_SOURCE = "duplicate_source"
SKIP_UNSUPPORTED_DOMAIN = "unsupported_domain"

# Domains never worth a paid extraction: aggregators, redirectors, social feeds.
_UNSUPPORTED_DOMAINS = frozenset({
    "news.google.com", "news.yahoo.com", "msn.com", "flipboard.com",
    "feedly.com", "feedburner.com", "reddit.com", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "linkedin.com", "tiktok.com",
    "youtube.com", "youtu.be", "medium.com", "substack.com", "biztoc.com",
    "newsbreak.com",
})

# High-value direct sources that are preferred (informational; used to rank).
PREFERRED_DOMAINS = frozenset({
    "github.com", "arxiv.org", "aclanthology.org", "ieee.org", "acm.org",
    "nature.com", "springer.com", "docs.python.org", "developer.mozilla.org",
    "readthedocs.io", "developer.apple.com", "developer.android.com",
})

# URL patterns that indicate an aggregator/redirect page.
_AGGREGATOR_REDIRECT_PATTERN = re.compile(
    r"(news\.google\.com/rss/articles|/rss/articles|/rss/|/url\?|/aclk\?|"
    r"feedburner|feedproxy|/redirect)", re.I)
_JS_ONLY_BODY_PATTERN = re.compile(
    r'<div[^>]*id=["\']?(root|app|__next|__nuxt)["\']?[^>]*>\s*</div>', re.I)


def is_aggregator_redirect(url: str, raw_html: str = "") -> bool:
    """Detect aggregator/redirect URLs (Google News redirects, RSS redirectors)."""
    if _AGGREGATOR_REDIRECT_PATTERN.search(url or ""):
        return True
    head = (raw_html or "")[:5000].lower()
    if 'http-equiv="refresh"' in head or "http-equiv='refresh'" in head:
        return True
    return False


def is_javascript_only(raw_html: str) -> bool:
    """Detect pages whose body is essentially empty (JS-rendered shell)."""
    if not raw_html:
        return False
    head = raw_html[:10000]
    if _JS_ONLY_BODY_PATTERN.search(head):
        return True
    if re.search(r"<body[^>]*>\s*</body>", head, re.I):
        return True
    return False


def assess_source_quality(url: str, raw_html: str, cleaning_diag: dict[str, Any],
                          seen_canonical: set[str],
                          unsupported_domains: frozenset[str] = _UNSUPPORTED_DOMAINS,
                          ) -> tuple[bool, str | None]:
    """Assess source quality before any paid extraction (no LLM call).

    Returns (usable, skip_reason). skip_reason is one of the SKIP_* constants
    when the source should be skipped, else None.
    """
    from agent.feed import canonical_url
    from .models import registrable_domain

    canonical = canonical_url(url)
    if canonical and canonical in seen_canonical:
        return False, SKIP_DUPLICATE_SOURCE
    domain = registrable_domain(url)
    if domain in unsupported_domains:
        return False, SKIP_UNSUPPORTED_DOMAIN
    if is_aggregator_redirect(url, raw_html):
        return False, SKIP_AGGREGATOR_REDIRECT
    if is_javascript_only(raw_html):
        return False, SKIP_JAVASCRIPT_ONLY
    if not cleaning_diag.get("usable_text"):
        if cleaning_diag.get("failure_reason") == "insufficient_clean_text":
            return False, SKIP_INSUFFICIENT_TEXT
        return False, SKIP_NO_READABLE_CONTENT
    return True, None
