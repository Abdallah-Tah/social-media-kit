"""Tests for the substance gate on the news lane.

The structural gate (`quality_issues`) measures shape. These cover the checks
that measure whether the article is about anything — added after a piece titled
"Python 3.14.6 Release: Key Security Updates" shipped naming zero CVEs with the
Wikipedia page for "Python (programming language)" as its only source.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

import content_formats as CF


def _article(body_text, sources):
    links = "\n".join(f"- [src]({u})" for u in sources)
    return (
        f"{body_text}\n\n"
        f"## Sources\n\n{links}\n\n"
        "## What I'll Be Watching\n\nWhether the rollout holds up.\n"
    )


BODY = (
    "The release changes how the parser handles untrusted input. "
    "Upgrading is the whole fix; there is no configuration workaround. "
) * 8


def test_wikipedia_alone_is_not_a_primary_source():
    art = _article(BODY, ["https://en.wikipedia.org/wiki/Python_(programming_language)"])
    issues = CF.substance_issues("Python 3.14.6 Release: Key Security Updates", art)
    assert any("no primary source" in i for i in issues)


def test_security_article_must_name_a_cve_or_advisory():
    art = _article(BODY, ["https://www.python.org/downloads/release/python-3146/"])
    issues = CF.substance_issues("Python 3.14.6 security update", art)
    assert any("names no CVE" in i for i in issues)


def test_security_article_passes_with_a_cve():
    art = _article(BODY + " The fix addresses CVE-2026-12345 in the parser. ",
                   ["https://www.python.org/downloads/release/python-3146/"])
    issues = CF.substance_issues("Python 3.14.6 security update", art)
    assert not any("names no CVE" in i for i in issues)


def test_vendor_subdomain_is_an_acceptable_sole_source():
    """learn.microsoft.com alone is fine; the rule targets unrelated blogs."""
    art = _article(BODY, ["https://learn.microsoft.com/dotnet/whats-new"])
    issues = CF.substance_issues("Visual Studio 2026 .NET and Azure skills", art)
    assert not any("sole source" in i for i in issues)


def test_unrelated_personal_blog_alone_is_rejected():
    art = _article(BODY, ["https://kunalganglani.com/posts/gpt-5-5"])
    issues = CF.substance_issues("GPT-5.5 and Agents SDK: OpenAI's Evolution", art)
    assert any("sole source" in i for i in issues)


def test_host_named_in_the_headline_qualifies():
    art = _article(BODY, ["https://investor.workday.com/news/ai-agents"])
    issues = CF.substance_issues("Workday's New AI Agent Tools", art)
    assert not any("sole source" in i for i in issues)


def test_headline_version_must_appear_in_the_body():
    art = _article("Nothing specific is discussed here at all. " * 20,
                   ["https://blog.google/product"])
    issues = CF.substance_issues("Gemini 3.5 Flash changes the defaults", art)
    assert any("never mentions it" in i for i in issues)


def test_filler_density_is_flagged():
    filler = ("In this ever-evolving landscape it is worth noting the pivotal "
              "and crucial paradigm, a testament to comprehensive myriad. ") * 10
    art = _article(filler, ["https://blog.google/product"])
    issues = CF.substance_issues("Google ships a thing", art)
    assert any("filler density" in i for i in issues)


def test_clean_vendor_sourced_article_passes():
    art = _article(BODY, ["https://blog.google/tech/ai",
                          "https://developers.googleblog.com/io-2026"])
    # Title deliberately free of release/API triggers — this fixture exists to
    # prove a well-sourced article raises nothing, not to exercise those rules.
    assert CF.substance_issues("Google rethinks agentic workflows", art) == []


def test_source_urls_reads_only_the_sources_section():
    art = _article("See https://example.com/inline for context. " * 10,
                   ["https://blog.google/tech/ai"])
    assert CF.source_urls(art) == ["https://blog.google/tech/ai"]


def test_ungrounded_extraction_is_measured_without_scaffolding():
    import news_publish
    thin = "URL: https://example.com/a\nEXTRACT:\n\n\n---\n\nURL: https://x.com/b\nEXTRACT:\nshort"
    assert news_publish.extracted_chars(thin) < 50


# --- regressions from real production blocks (2026-07-31 / 08-01) ------------

def test_vendor_dev_domain_is_authoritative():
    """ai.google.dev blocked a Gemini story sourced from Google's own site."""
    art = _article(BODY, ["https://ai.google.dev/pricing"])
    issues = CF.substance_issues(
        "Google's Gemini API Introduces Pay-As-You-Go Billing", art)
    assert not any("sole source" in i for i in issues)


def test_code_host_is_authoritative_for_a_release():
    """Kubernetes publishes releases on GitHub; github.com is primary there."""
    art = _article(BODY, ["https://github.com/kubernetes/kubernetes/releases/tag/v1.36.0"])
    issues = CF.substance_issues(
        "Kubernetes v1.36 Release Packs New Extensible Features", art)
    assert not any("sole source" in i for i in issues)


def test_every_host_label_is_checked_not_just_the_first():
    assert CF._looks_authoritative("ai.google.dev", "Google ships Gemini")
    assert CF._looks_authoritative("learn.microsoft.com", "Microsoft ships something")
    # Generic labels must not create matches on their own.
    assert not CF._looks_authoritative("randomblog.dev", "A story about developers")


def test_unrelated_blog_still_rejected_after_widening():
    art = _article(BODY, ["https://kunalganglani.com/posts/gpt-5-5"])
    issues = CF.substance_issues("GPT-5.5 and Agents SDK: OpenAI's Evolution", art)
    assert any("sole source" in i for i in issues)


def test_short_vendor_token_matches_exactly():
    """php.net blocked a PHP release story: "php" is under the loose-match floor."""
    assert CF._looks_authoritative("php.net", "PHP 8.6.0 Alpha 2 released for testing")
    assert CF._looks_authoritative("vuejs.org", "Vue 4 ships new reactivity")


def test_short_token_does_not_match_loosely():
    """Substring matching on 3 letters would read 'the' as endorsing theverge."""
    assert not CF._looks_authoritative("theverge.com", "The new API changes things")


def test_devblogs_subdomain_is_official():
    assert CF._looks_authoritative("devblogs.microsoft.com", ".NET 11 Preview 6 first look")


def test_passing_mention_of_security_does_not_trigger_the_cve_rule():
    """One "reduces vulnerabilities" in a launch piece is not a security story."""
    body = ("The model ships with a larger context window. " * 25 +
            "Anthropic says it reduces vulnerabilities in generated code. ")
    art = _article(body, ["https://www.anthropic.com/news/fable-5"])
    issues = CF.substance_issues("Anthropic Releases Claude Fable 5", art)
    assert not any("CVE" in i for i in issues)


def test_article_substantially_about_security_still_triggers():
    body = ("This security update addresses a vulnerability in the parser. " * 6 +
            "The security patch is mandatory. " * 4)
    art = _article(body, ["https://example.invalid/post"])
    issues = CF.substance_issues("Framework ships an update", art)
    assert any("CVE" in i for i in issues)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
