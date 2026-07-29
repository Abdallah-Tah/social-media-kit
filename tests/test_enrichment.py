"""Phase 1 Stage 7C.5 — editorial candidate enrichment tests.

Covers:
  * Official release source identified correctly
  * Secondary article does not become primary
  * Same-day related sources become corroboration candidates
  * Syndicated copies are excluded
  * Repository release creates code/repository practical signals
  * Pricing article creates pricing impact only when sourced
  * Security advisory creates remediation signal only when explicit
  * Development type is classified correctly
  * Unknown type remains unknown
  * Recommended artifact types are slot-compatible
  * Missing evidence returns partial or insufficient result
  * No fabricated primary source
  * No LLM or network calls
  * Same input produces deterministic output
  * Raw feed record is not mutated
  * Production behavior remains unchanged
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent.editorial.enrichment import (
    EnrichmentResult,
    STATUS_ENRICHED,
    STATUS_PARTIALLY_ENRICHED,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_FAILED,
    enrich_candidate,
    enrich_many,
)


# ── primary-source resolution ────────────────────────────────────────────────

class TestPrimarySourceResolution:
    def test_official_domain_identified(self):
        result = enrich_candidate({
            "title": "OpenAI releases GPT-5",
            "url": "https://openai.com/blog/gpt-5",
            "source": "hackernews",
        })
        assert result.primary_source is not None
        assert result.primary_source["kind"] == "official_announcement"
        assert result.primary_source["is_primary"] is True

    def test_github_release_identified(self):
        result = enrich_candidate({
            "title": "Rust 2.0 released",
            "url": "https://github.com/rust-lang/rust/releases/tag/2.0.0",
            "source": "hackernews",
        })
        assert result.primary_source is not None
        assert result.primary_source["kind"] == "repository_release"

    def test_github_repo_identified(self):
        result = enrich_candidate({
            "title": "New open-source project",
            "url": "https://github.com/example/project",
            "source": "hackernews",
        })
        assert result.primary_source is not None
        assert result.primary_source["kind"] == "repository"

    def test_arxiv_paper_identified(self):
        result = enrich_candidate({
            "title": "Attention Is All You Need",
            "url": "https://arxiv.org/abs/1706.03762",
            "source": "hackernews",
        })
        assert result.primary_source is not None
        assert result.primary_source["kind"] == "research_paper"

    def test_secondary_article_not_primary(self):
        result = enrich_candidate({
            "title": "TechCrunch covers GPT-5",
            "url": "https://techcrunch.com/2026/07/20/gpt-5-review",
            "source": "hackernews",
        })
        assert result.primary_source is None
        assert "no_primary_source" in result.warnings

    def test_no_fabricated_primary(self):
        result = enrich_candidate({
            "title": "Random blog post",
            "url": "https://randomblog.example.com/post",
            "source": "reddit",
        })
        assert result.primary_source is None
        assert "no_primary_source" in result.warnings

    def test_docs_path_identified(self):
        result = enrich_candidate({
            "title": "React documentation updated",
            "url": "https://react.dev/docs/hooks",
            "source": "hackernews",
        })
        assert result.primary_source is not None
        assert result.primary_source["kind"] == "official_documentation"


# ── corroboration ────────────────────────────────────────────────────────────

class TestCorroboration:
    def test_same_day_related_becomes_corroboration(self):
        item = {
            "title": "OpenAI releases GPT-5 with native tool use",
            "url": "https://openai.com/blog/gpt-5",
            "source": "hackernews",
        }
        related = [
            {
                "title": "GPT-5 review: native tool use changes everything",
                "url": "https://techcrunch.com/2026/07/20/gpt-5-review",
                "source": "google_news",
            },
        ]
        result = enrich_candidate(item, related_items=related)
        # Should have at least the primary + corroboration + original URL
        assert len(result.sources) >= 2
        corroborating = [s for s in result.sources if s.get("adds_independent_evidence")]
        assert len(corroborating) >= 1

    def test_syndicated_copy_excluded(self):
        item = {
            "title": "OpenAI releases GPT-5",
            "url": "https://openai.com/blog/gpt-5",
            "source": "hackernews",
        }
        related = [
            {
                "title": "OpenAI releases GPT-5",
                "url": "https://prnewswire.com/releases/openai-gpt-5",
                "source": "press_release",
            },
        ]
        result = enrich_candidate(item, related_items=related)
        corroborating = [s for s in result.sources
                         if s.get("adds_independent_evidence")
                         and "prnewswire" in s.get("url", "")]
        assert len(corroborating) == 0

    def test_same_domain_not_counted_twice(self):
        item = {
            "title": "OpenAI releases GPT-5",
            "url": "https://openai.com/blog/gpt-5",
            "source": "hackernews",
        }
        related = [
            {
                "title": "GPT-5 API documentation",
                "url": "https://openai.com/docs/gpt-5",
                "source": "google_news",
            },
        ]
        result = enrich_candidate(item, related_items=related)
        # Same domain should not be counted as independent corroboration
        openai_sources = [s for s in result.sources
                          if "openai.com" in s.get("url", "")
                          and s.get("adds_independent_evidence")]
        assert len(openai_sources) == 0


# ── practical signals ────────────────────────────────────────────────────────

class TestPracticalSignals:
    def test_repository_release_signals(self):
        result = enrich_candidate({
            "title": "Rust 2.0 released with new compiler",
            "url": "https://github.com/rust-lang/rust/releases/tag/2.0.0",
            "source": "hackernews",
        })
        assert result.practical_signals.get("has_repository_reference") is True
        assert result.practical_signals.get("has_code_change") is True

    def test_pricing_signal_only_when_sourced(self):
        result_with = enrich_candidate({
            "title": "AWS Lambda pricing changes to $0.20/request",
            "url": "https://aws.amazon.com/lambda/pricing",
            "source": "hackernews",
        })
        assert result_with.practical_signals.get("has_pricing_impact") is True

        result_without = enrich_candidate({
            "title": "New programming language announced",
            "url": "https://example.com/lang",
            "source": "hackernews",
        })
        assert result_without.practical_signals.get("has_pricing_impact") is False

    def test_security_signal_only_when_explicit(self):
        result_with = enrich_candidate({
            "title": "Critical vulnerability CVE-2026-1234 patched",
            "url": "https://github.com/advisories/CVE-2026-1234",
            "source": "hackernews",
        })
        assert result_with.practical_signals.get("has_security_action") is True

        result_without = enrich_candidate({
            "title": "New web framework released",
            "url": "https://example.com/framework",
            "source": "hackernews",
        })
        assert result_without.practical_signals.get("has_security_action") is False


# ── development type classification ──────────────────────────────────────────

class TestDevelopmentType:
    def test_model_release(self):
        result = enrich_candidate({
            "title": "OpenAI releases GPT-5",
            "url": "https://openai.com/blog/gpt-5",
        })
        assert result.development_type == "model_release"

    def test_repository_release(self):
        result = enrich_candidate({
            "title": "Version 3.2 released",
            "url": "https://github.com/example/project/releases/tag/v3.2.0",
        })
        assert result.development_type == "repository_release"

    def test_security_issue(self):
        result = enrich_candidate({
            "title": "Critical security vulnerability found in OpenSSL",
            "url": "https://openssl.org/news/secadv.html",
        })
        assert result.development_type == "security_issue"

    def test_research_paper(self):
        result = enrich_candidate({
            "title": "New paper on transformer architectures",
            "url": "https://arxiv.org/abs/2401.12345",
        })
        assert result.development_type == "research_paper"

    def test_unknown_remains_unknown(self):
        result = enrich_candidate({
            "title": "Interesting discussion about programming",
            "url": "https://news.ycombinator.com/item?id=12345",
        })
        assert result.development_type == "unknown"
        assert "development_type_unknown" in result.warnings

    def test_metadata_override(self):
        result = enrich_candidate({
            "title": "Some title",
            "url": "https://example.com",
            "metadata": {"development_type": "pricing_change"},
        })
        assert result.development_type == "pricing_change"


# ── artifact recommendations ─────────────────────────────────────────────────

class TestArtifactRecommendations:
    def test_model_release_artifacts(self):
        result = enrich_candidate({
            "title": "OpenAI releases GPT-5",
            "url": "https://openai.com/blog/gpt-5",
        })
        assert "technical_analysis" in result.recommended_artifact_types
        assert "intelligence_brief" in result.recommended_artifact_types

    def test_security_issue_artifacts(self):
        result = enrich_candidate({
            "title": "Critical vulnerability patched",
            "url": "https://github.com/advisories/CVE-2026-1234",
        })
        assert "migration_note" in result.recommended_artifact_types or \
               "takeaway_checklist" in result.recommended_artifact_types

    def test_not_all_news(self):
        result = enrich_candidate({
            "title": "Repository release v2.0",
            "url": "https://github.com/example/project/releases/tag/v2.0.0",
        })
        assert result.recommended_artifact_types != ("intelligence_brief",)
        assert len(result.recommended_artifact_types) >= 2


# ── claims ───────────────────────────────────────────────────────────────────

class TestClaims:
    def test_version_claim_extracted(self):
        result = enrich_candidate({
            "title": "Python 3.14 released",
            "url": "https://python.org/downloads/release/3-14-0",
        })
        version_claims = [c for c in result.claims if c["claim_type"] == "version_fact"]
        assert len(version_claims) >= 1

    def test_pricing_claim_extracted(self):
        result = enrich_candidate({
            "title": "New pricing at $20/month",
            "url": "https://example.com/pricing",
        })
        pricing_claims = [c for c in result.claims if c["claim_type"] == "pricing"]
        assert len(pricing_claims) >= 1

    def test_claims_have_verification_status(self):
        result = enrich_candidate({
            "title": "OpenAI releases GPT-5",
            "url": "https://openai.com/blog/gpt-5",
        })
        for claim in result.claims:
            assert "verification" in claim
            assert claim["verification"] in (
                "independently_established", "vendor_provided", "unverified")

    def test_claims_have_traceability(self):
        result = enrich_candidate({
            "title": "OpenAI releases GPT-5",
            "url": "https://openai.com/blog/gpt-5",
        })
        for claim in result.claims:
            assert "traceability" in claim


# ── missing evidence ─────────────────────────────────────────────────────────

class TestMissingEvidence:
    def test_no_title_no_url_fails(self):
        result = enrich_candidate({"title": "", "url": ""})
        assert result.status == STATUS_FAILED

    def test_minimal_input_insufficient(self):
        result = enrich_candidate({
            "title": "Something happened",
            "url": "https://random.example.com/post",
        })
        assert result.status in (STATUS_PARTIALLY_ENRICHED, STATUS_INSUFFICIENT_EVIDENCE)
        assert result.confidence < 60

    def test_no_excerpt_recorded(self):
        result = enrich_candidate({
            "title": "Something",
            "url": "https://example.com",
            "summary": "",
        })
        assert "no_excerpt_available" in result.warnings


# ── purity guarantees ────────────────────────────────────────────────────────

class TestPurity:
    def test_no_llm_calls(self):
        import agent.llm_ops as LLM
        with patch.object(LLM, "chat", side_effect=AssertionError("no LLM")):
            enrich_candidate({
                "title": "OpenAI releases GPT-5",
                "url": "https://openai.com/blog/gpt-5",
            })

    def test_no_network_calls(self):
        import urllib.request
        with patch.object(urllib.request, "urlopen",
                          side_effect=AssertionError("no network")):
            enrich_candidate({
                "title": "OpenAI releases GPT-5",
                "url": "https://openai.com/blog/gpt-5",
            })

    def test_deterministic_output(self):
        item = {
            "title": "OpenAI releases GPT-5",
            "url": "https://openai.com/blog/gpt-5",
            "source": "hackernews",
            "summary": "GPT-5 is here with native tool use.",
        }
        r1 = enrich_candidate(item)
        r2 = enrich_candidate(item)
        assert r1.to_dict() == r2.to_dict()

    def test_input_not_mutated(self):
        item = {
            "title": "OpenAI releases GPT-5",
            "url": "https://openai.com/blog/gpt-5",
            "source": "hackernews",
            "summary": "GPT-5 is here.",
            "metadata": {"key": "value"},
        }
        original = copy.deepcopy(item)
        enrich_candidate(item)
        assert item == original

    def test_feature_flag_unchanged(self):
        from agent.editorial.flags import editorial_slots_enabled
        assert editorial_slots_enabled() is False


# ── enrich_many ──────────────────────────────────────────────────────────────

class TestEnrichMany:
    def test_batch_enrichment(self):
        items = [
            {"title": "OpenAI releases GPT-5", "url": "https://openai.com/blog/gpt-5",
             "source": "hackernews"},
            {"title": "GPT-5 review by TechCrunch", "url": "https://techcrunch.com/gpt-5",
             "source": "google_news"},
        ]
        results = enrich_many(items)
        assert len(results) == 2
        # First item should see second as corroboration
        _, r1 = results[0]
        assert len(r1.sources) >= 2

    def test_empty_batch(self):
        results = enrich_many([])
        assert results == []


# ── excerpts ─────────────────────────────────────────────────────────────────

class TestExcerpts:
    def test_summary_captured(self):
        result = enrich_candidate({
            "title": "Test",
            "url": "https://example.com",
            "summary": "This is a test summary.",
        })
        assert len(result.excerpts) >= 1
        assert result.excerpts[0]["source"] == "feed_summary"

    def test_metadata_description_captured(self):
        result = enrich_candidate({
            "title": "Test",
            "url": "https://example.com",
            "metadata": {"description": "A longer description."},
        })
        sources = [e["source"] for e in result.excerpts]
        assert "metadata_description" in sources


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
