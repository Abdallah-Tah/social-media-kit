"""Confirmation that the production gate rejects each disallowed article class.

One test per category, asserted against the *production* entry points
(`content_formats.substance_issues` for articles, `agent.social_drafts`'
publish gate for social copy) — not against helpers — so this file fails if the
rules are ever loosened or bypassed.

Categories:
  1. security article with no CVE, advisory, or official security source
  2. release article with no exact version / no official release source
  3. API article with no named API / no official documentation
  4. Wikipedia or a personal blog as the sole source for technical claims
  5. generic social copy with no concrete fact
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
from agent.social_drafts import social_post_quality_error

PROSE = ("The change alters how the router resolves middleware before the "
         "handler runs, and the old behaviour is gone. ") * 8


def article(body, sources):
    links = "\n".join(f"- [src]({u})" for u in sources)
    return (f"{body}\n\n## Sources\n\n{links}\n\n"
            "## What I'll Be Watching\n\nAdoption over the next release.\n")


def reasons(title, body):
    return CF.substance_issues(title, body)


# --- 1. security ------------------------------------------------------------

def test_rejects_security_article_without_cve_advisory_or_official_source():
    art = article(PROSE, ["https://randomnewsblog.example/post"])
    why = reasons("Framework ships a critical security patch", art)
    assert any("CVE" in r or "security" in r for r in why), why


def test_accepts_security_article_with_cve_and_official_source():
    art = article(PROSE + " The fix is CVE-2026-12345. ",
                  ["https://nextjs.org/blog/security-update-2026"])
    why = reasons("Next.js ships a critical security patch", art)
    assert not any("CVE" in r or "security" in r for r in why), why


# --- 2. release -------------------------------------------------------------

def test_rejects_release_article_without_an_exact_version():
    art = article(PROSE, ["https://kubernetes.io/blog/"])
    why = reasons("Kubernetes releases new extensible features", art)
    assert any("no exact version" in r for r in why), why


def test_rejects_release_article_without_an_official_release_source():
    art = article(PROSE + " This covers version 1.36 of the platform. ",
                  ["https://somerandomblog.example/k8s-thoughts"])
    why = reasons("Kubernetes 1.36 released with new features", art)
    assert any("official release source" in r or "sole source" in r for r in why), why


def test_accepts_release_article_with_version_and_official_source():
    art = article(PROSE + " Kubernetes v1.36.0 is the tagged release. ",
                  ["https://github.com/kubernetes/kubernetes/releases/tag/v1.36.0"])
    why = reasons("Kubernetes v1.36 released with new features", art)
    assert not any("release story" in r for r in why), why


def test_deprecation_headline_is_not_treated_as_a_release():
    art = article(PROSE, ["https://developers.openai.com/changelog"])
    why = reasons("OpenAI deprecates the Realtime API Beta", art)
    assert not any("release story" in r for r in why), why


# --- 3. API -----------------------------------------------------------------

def test_rejects_api_article_without_a_named_api_surface():
    vague = ("The API has been improved for developers and the experience is "
             "better than before across the board. ") * 8
    art = article(vague, ["https://developers.openai.com/changelog"])
    why = reasons("OpenAI improves its API platform", art)
    assert any("no specific endpoint" in r for r in why), why


def test_rejects_api_article_without_an_official_source():
    art = article(PROSE + " Call POST /v1/responses to migrate. ",
                  ["https://releasebot.io/openai/prompts"])
    why = reasons("OpenAI announces the Prompts API", art)
    assert any("official documentation" in r or "sole source" in r for r in why), why


def test_accepts_api_article_with_named_surface_and_official_docs():
    art = article(PROSE + " Call POST /v1/responses instead of /v1/chat/completions. ",
                  ["https://developers.openai.com/docs/api-reference/responses"])
    why = reasons("OpenAI announces the Responses API", art)
    assert not any("API story" in r for r in why), why


# --- 4. weak sole sources ---------------------------------------------------

def test_rejects_wikipedia_as_the_sole_source():
    art = article(PROSE, ["https://en.wikipedia.org/wiki/Python_(programming_language)"])
    why = reasons("Python 3.14.6 ships key updates", art)
    assert any("no primary source" in r for r in why), why


def test_rejects_unrelated_personal_blog_as_the_sole_source():
    art = article(PROSE, ["https://kunalganglani.com/posts/gpt-5-5"])
    why = reasons("GPT-5.5 and the Agents SDK: OpenAI's evolution", art)
    assert any("sole source" in r for r in why), why


def test_accepts_personal_blog_when_corroborated_by_the_vendor():
    art = article(PROSE, ["https://kunalganglani.com/posts/gpt-5-5",
                          "https://developers.openai.com/changelog"])
    why = reasons("GPT-5.5 and the Agents SDK: OpenAI's evolution", art)
    assert not any("sole source" in r for r in why), why


# --- 5. generic social copy -------------------------------------------------

GENERIC = ("OpenAI has updated their API to improve usability and performance "
           "for developers. This means you can spend less time fixing issues "
           "and more time building innovative AI applications.\n\n"
           "https://buildwithabdallah.com/tutorials/openai-api-changelog")

CONCRETE = ("Next.js patched a middleware bypass in 16.2 and 15.5. If you run "
            "either line, upgrade before your next deploy or the auth check "
            "can be skipped entirely.\n\n"
            "https://buildwithabdallah.com/tutorials/nextjs-security")


def test_rejects_generic_social_copy_without_a_concrete_fact():
    why = social_post_quality_error("OpenAI Enhances Its API Platform", GENERIC)
    assert why is not None and "concrete fact" in why, why


def test_accepts_social_copy_carrying_a_version_and_a_consequence():
    assert social_post_quality_error("Next.js Security Patch Released", CONCRETE) is None


def test_a_bare_year_is_not_a_concrete_fact():
    year_only = ("Google announced changes to its developer tooling in 2026 and "
                 "developers should take a look at what shipped this time round. "
                 "The tooling story keeps moving and it is worth a read for anyone "
                 "who builds on the platform day to day.\n\n"
                 "https://buildwithabdallah.com/tutorials/google-io")
    why = social_post_quality_error("Google Ships Developer Tooling Changes", year_only)
    assert why is not None and "concrete fact" in why, why


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
