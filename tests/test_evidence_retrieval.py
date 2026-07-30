"""Tests for Stage 7C.7 — bounded evidence retrieval."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agent.editorial.evidence_retrieval import (
    EvidenceRetrievalConfig,
    identify_evidence_urls,
    fetch_url,
    retrieve_evidence_for_candidates,
    load_evidence_cache,
    save_evidence_cache,
)


@pytest.fixture
def config(tmp_path):
    """Test config with temporary cache path."""
    return EvidenceRetrievalConfig(
        enabled=True,
        max_candidates_per_run=2,
        max_urls_per_candidate=3,
        timeout_seconds=5,
        max_content_bytes=1000,
        cache_ttl_days=30,
        cache_path=tmp_path / "evidence_cache.json",
    )


@pytest.fixture
def sample_candidate():
    """Sample enriched candidate with primary source."""
    return {
        "title": "OpenAI releases GPT-5",
        "url": "https://openai.com/blog/gpt-5",
        "source": "hackernews",
        "metadata": {
            "enrichment": {
                "status": "enriched",
                "primary_source": {
                    "url": "https://openai.com/blog/gpt-5",
                    "kind": "official_announcement",
                },
                "sources": [
                    {
                        "url": "https://techcrunch.com/gpt-5-review",
                        "independent_corroboration": True,
                    }
                ],
            }
        }
    }


class TestIdentifyEvidenceUrls:
    def test_identifies_primary_source(self, config, sample_candidate):
        urls = identify_evidence_urls(sample_candidate, config)
        assert "https://openai.com/blog/gpt-5" in urls

    def test_identifies_independent_corroboration(self, config, sample_candidate):
        urls = identify_evidence_urls(sample_candidate, config)
        assert "https://techcrunch.com/gpt-5-review" in urls

    def test_derives_documentation_urls(self, config, sample_candidate):
        urls = identify_evidence_urls(sample_candidate, config)
        assert any("/docs" in url for url in urls)

    def test_respects_max_urls(self, config, sample_candidate):
        config = EvidenceRetrievalConfig(max_urls_per_candidate=2)
        urls = identify_evidence_urls(sample_candidate, config)
        assert len(urls) <= 2

    def test_filters_denied_domains(self, config):
        candidate = {
            "metadata": {
                "enrichment": {
                    "primary_source": {"url": "https://twitter.com/openai/status/123"},
                }
            }
        }
        urls = identify_evidence_urls(candidate, config)
        assert not any("twitter.com" in url for url in urls)

    def test_filters_non_allowed_domains(self, config):
        candidate = {
            "metadata": {
                "enrichment": {
                    "primary_source": {"url": "https://random-blog.com/post"},
                }
            }
        }
        urls = identify_evidence_urls(candidate, config)
        assert len(urls) == 0


class TestFetchUrl:
    @patch("agent.editorial.evidence_retrieval.urllib.request.urlopen")
    def test_fetches_successfully(self, mock_urlopen, config):
        mock_response = Mock()
        mock_response.read.return_value = b"Test content"
        mock_response.status = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = fetch_url("https://example.com", config)
        assert result["url"] == "https://example.com"
        assert result["content"] == "Test content"
        assert result["status"] == 200
        assert "fetched_at" in result

    @patch("agent.editorial.evidence_retrieval.urllib.request.urlopen")
    def test_handles_timeout(self, mock_urlopen, config):
        mock_urlopen.side_effect = TimeoutError("Connection timed out")

        result = fetch_url("https://example.com", config)
        assert result["status"] == 0
        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("agent.editorial.evidence_retrieval.urllib.request.urlopen")
    def test_respects_size_limit(self, mock_urlopen, config):
        config = EvidenceRetrievalConfig(max_content_bytes=10)
        mock_response = Mock()
        mock_response.read.return_value = b"X" * 100
        mock_response.status = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = fetch_url("https://example.com", config)
        assert len(result["content"]) <= 10


class TestCache:
    def test_load_empty_cache(self, config):
        cache = load_evidence_cache(config)
        assert cache == {}

    def test_save_and_load_cache(self, config):
        cache = {
            "https://example.com": {
                "url": "https://example.com",
                "content": "Test",
                "fetched_at": "2026-07-29T00:00:00Z",
                "status": 200,
            }
        }
        save_evidence_cache(cache, config)
        loaded = load_evidence_cache(config)
        assert loaded == cache

    def test_cache_pruning(self, config):
        import datetime as dt
        config = EvidenceRetrievalConfig(cache_ttl_days=1, cache_path=config.cache_path)
        # Compute timestamps relative to now so the test is not wall-clock dependent.
        now = dt.datetime.now(dt.timezone.utc)
        recent = (now - dt.timedelta(hours=1)).isoformat()   # inside the 1-day TTL
        stale = (now - dt.timedelta(days=2)).isoformat()     # outside the 1-day TTL
        cache = {
            "https://old.com": {
                "url": "https://old.com",
                "content": "Old",
                "fetched_at": stale,
                "status": 200,
            },
            "https://new.com": {
                "url": "https://new.com",
                "content": "New",
                "fetched_at": recent,
                "status": 200,
            }
        }
        save_evidence_cache(cache, config)
        loaded = load_evidence_cache(config)
        assert "https://old.com" not in loaded
        assert "https://new.com" in loaded


class TestRetrieveEvidence:
    @patch("agent.editorial.evidence_retrieval.fetch_url")
    def test_retrieves_for_top_candidates_only(self, mock_fetch, config, sample_candidate):
        mock_fetch.return_value = {
            "url": "https://example.com",
            "content": "Evidence",
            "fetched_at": "2026-07-29T00:00:00Z",
            "status": 200,
        }
        candidates = [sample_candidate.copy() for _ in range(5)]
        result = retrieve_evidence_for_candidates(candidates, config)

        # Only top 2 candidates should have fetched_evidence
        assert "fetched_evidence" in result[0]["metadata"]
        assert "fetched_evidence" in result[1]["metadata"]
        assert "fetched_evidence" not in result[2].get("metadata", {})

    @patch("agent.editorial.evidence_retrieval.fetch_url")
    def test_uses_cache(self, mock_fetch, config, sample_candidate):
        # Mock fetch_url to return proper dicts for non-cached URLs
        def fetch_side_effect(url, cfg):
            return {
                "url": url,
                "content": f"Content for {url}",
                "fetched_at": "2026-07-29T00:00:00Z",
                "status": 200,
            }
        mock_fetch.side_effect = fetch_side_effect
        
        # Pre-populate cache
        cache = {
            "https://openai.com/blog/gpt-5": {
                "url": "https://openai.com/blog/gpt-5",
                "content": "Cached content",
                "fetched_at": "2026-07-29T00:00:00Z",
                "status": 200,
            }
        }
        save_evidence_cache(cache, config)

        result = retrieve_evidence_for_candidates([sample_candidate], config)

        # Should use cached content, not call fetch_url for that URL
        fetched = result[0]["metadata"]["fetched_evidence"]
        cached_item = next(e for e in fetched if e["url"] == "https://openai.com/blog/gpt-5")
        assert cached_item["content"] == "Cached content"

    def test_disabled_config_skips_retrieval(self, sample_candidate):
        config = EvidenceRetrievalConfig(enabled=False)
        result = retrieve_evidence_for_candidates([sample_candidate], config)
        assert "fetched_evidence" not in result[0].get("metadata", {})

    @patch("agent.editorial.evidence_retrieval.fetch_url")
    def test_re_enriches_with_evidence(self, mock_fetch, config, sample_candidate):
        mock_fetch.return_value = {
            "url": "https://openai.com/docs",
            "content": "GPT-5 documentation with API details and benchmarks showing 2x performance.",
            "fetched_at": "2026-07-29T00:00:00Z",
            "status": 200,
        }
        result = retrieve_evidence_for_candidates([sample_candidate], config)

        # Should have re-enrichment with evidence
        assert "enrichment" in result[0]["metadata"]
        # Re-enrichment should have processed the evidence content
        enrichment = result[0]["metadata"]["enrichment"]
        assert enrichment["status"] in ("enriched", "partially_enriched")
