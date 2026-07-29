"""Tests for Stage 7C.8 — Structured Evidence Extraction."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agent.editorial.evidence_extraction import (
    ExtractionConfig,
    build_extraction_prompt,
    validate_extraction,
    extract_structured_evidence,
    candidate_fingerprint,
    evidence_fingerprint,
)
from agent.editorial.models import Candidate
from agent import llm_ops


@pytest.fixture
def config(tmp_path):
    """Test config with temporary cache path."""
    return ExtractionConfig(
        enabled=True,
        max_candidates_per_run=2,
        max_input_chars=10000,
        daily_budget_usd=5.0,
        model="gpt-4o-mini",
        cache_path=tmp_path / "extraction_cache.json",
    )


@pytest.fixture
def sample_candidate():
    """Sample candidate with fetched evidence."""
    return {
        "title": "OpenAI releases GPT-5",
        "url": "https://openai.com/blog/gpt-5",
        "source": "hackernews",
        "summary": "OpenAI announced GPT-5 today.",
        "metadata": {
            "fetched_evidence": [
                {
                    "url": "https://openai.com/blog/gpt-5",
                    "content": "OpenAI announced GPT-5 today with 2x performance improvements. Available now.",
                    "status": 200,
                },
                {
                    "url": "https://techcrunch.com/gpt-5-review",
                    "content": "We benchmarked GPT-5 and confirmed 2x speedup in our tests.",
                    "status": 200,
                }
            ]
        }
    }


@pytest.fixture
def valid_extraction():
    """Valid grounded extraction."""
    return {
        "event": {
            "development_type": "model_release",
            "subject_org": "openai",
            "subject_name": "GPT-5",
            "release_or_event_id": "",
            "event_time": "2026-07-29",
            "availability_status": "available"
        },
        "claims": [
            {
                "text": "GPT-5 has 2x performance improvements",
                "claim_type": "performance",
                "material": True,
                "vendor_provided": True,
                "verification": "vendor_claim",
                "source_urls": ["https://openai.com/blog/gpt-5"],
                "evidence_quotes": ["2x performance improvements"]
            },
            {
                "text": "Independent benchmark confirms 2x speedup",
                "claim_type": "benchmark",
                "material": True,
                "vendor_provided": False,
                "verification": "independently_supported",
                "source_urls": ["https://techcrunch.com/gpt-5-review"],
                "evidence_quotes": ["We benchmarked GPT-5 and confirmed 2x speedup"]
            }
        ],
        "practical_signals": {
            "has_api_change": True,
            "has_deployment_impact": True,
        },
        "recommended_artifact_types": ["technical_analysis", "intelligence_brief"],
        "warnings": []
    }


class TestBuildPrompt:
    def test_builds_prompt_with_evidence(self, config, sample_candidate):
        messages = build_extraction_prompt(sample_candidate, config)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "GROUNDING RULES" in messages[0]["content"]
        assert "OpenAI releases GPT-5" in messages[1]["content"]
        assert "https://openai.com/blog/gpt-5" in messages[1]["content"]

    def test_includes_source_urls(self, config, sample_candidate):
        messages = build_extraction_prompt(sample_candidate, config)
        assert "https://openai.com/blog/gpt-5" in messages[1]["content"]
        assert "https://techcrunch.com/gpt-5-review" in messages[1]["content"]


class TestValidateExtraction:
    def test_valid_grounded_extraction(self, valid_extraction, sample_candidate):
        fetched_evidence = sample_candidate["metadata"]["fetched_evidence"]
        source_urls = [e["url"] for e in fetched_evidence]
        
        validated, rejections = validate_extraction(valid_extraction, fetched_evidence, source_urls)
        
        assert len(rejections) == 0
        assert len(validated["claims"]) == 2

    def test_unsupported_claim_rejected(self, sample_candidate):
        fetched_evidence = sample_candidate["metadata"]["fetched_evidence"]
        source_urls = [e["url"] for e in fetched_evidence]
        
        extraction = {
            "claims": [
                {
                    "text": "Unsupported claim",
                    "source_urls": ["https://unsupplied.com"],
                    "evidence_quotes": ["some quote"]
                }
            ]
        }
        
        validated, rejections = validate_extraction(extraction, fetched_evidence, source_urls)
        
        assert len(rejections) == 1
        assert "unsupplied URL" in rejections[0]
        assert len(validated["claims"]) == 0

    def test_fabricated_excerpt_rejected(self, sample_candidate):
        fetched_evidence = sample_candidate["metadata"]["fetched_evidence"]
        source_urls = [e["url"] for e in fetched_evidence]
        
        extraction = {
            "claims": [
                {
                    "text": "Claim with fabricated excerpt",
                    "source_urls": ["https://openai.com/blog/gpt-5"],
                    "evidence_quotes": ["This text does not exist in fetched content"]
                }
            ]
        }
        
        validated, rejections = validate_extraction(extraction, fetched_evidence, source_urls)
        
        assert len(rejections) == 1
        assert "not found in fetched text" in rejections[0]
        assert len(validated["claims"]) == 0

    def test_vendor_benchmark_remains_vendor_claim(self, sample_candidate):
        fetched_evidence = sample_candidate["metadata"]["fetched_evidence"]
        source_urls = [e["url"] for e in fetched_evidence]
        
        extraction = {
            "claims": [
                {
                    "text": "Vendor benchmark claim",
                    "claim_type": "benchmark",
                    "vendor_provided": True,
                    "verification": "vendor_claim",
                    "source_urls": ["https://openai.com/blog/gpt-5"],
                    "evidence_quotes": ["2x performance improvements"]
                }
            ]
        }
        
        validated, rejections = validate_extraction(extraction, fetched_evidence, source_urls)
        
        assert len(rejections) == 0
        assert validated["claims"][0]["verification"] == "vendor_claim"

    def test_independent_benchmark_becomes_independently_supported(self, sample_candidate):
        fetched_evidence = sample_candidate["metadata"]["fetched_evidence"]
        source_urls = [e["url"] for e in fetched_evidence]
        
        extraction = {
            "claims": [
                {
                    "text": "Independent benchmark",
                    "claim_type": "benchmark",
                    "vendor_provided": False,
                    "verification": "independently_supported",
                    "source_urls": ["https://techcrunch.com/gpt-5-review"],
                    "evidence_quotes": ["We benchmarked GPT-5 and confirmed 2x speedup"]
                }
            ]
        }
        
        validated, rejections = validate_extraction(extraction, fetched_evidence, source_urls)
        
        assert len(rejections) == 0
        assert validated["claims"][0]["verification"] == "independently_supported"

    def test_practical_signal_requires_evidence(self, sample_candidate):
        fetched_evidence = sample_candidate["metadata"]["fetched_evidence"]
        source_urls = [e["url"] for e in fetched_evidence]
        
        extraction = {
            "claims": [],  # No claims
            "practical_signals": {
                "has_api_change": True,  # Signal without evidence
            }
        }
        
        validated, rejections = validate_extraction(extraction, fetched_evidence, source_urls)
        
        # No claims = all signals should be False
        assert validated["practical_signals"]["has_api_change"] is False


class TestExtractStructuredEvidence:
    @patch("agent.editorial.evidence_extraction.llm_ops.chat")
    def test_valid_extraction(self, mock_chat, config, sample_candidate, valid_extraction):
        mock_result = Mock()
        mock_result.ok = True
        mock_result.json.return_value = valid_extraction
        mock_result.input_tokens = 1000
        mock_result.output_tokens = 500
        mock_result.cost_usd = 0.01
        mock_result.duration_ms = 2000
        mock_chat.return_value = mock_result
        
        candidates, metrics = extract_structured_evidence([sample_candidate], config)
        
        assert metrics["candidates_extracted"] == 1
        assert metrics["claims_accepted"] == 2
        assert metrics["llm_calls"] == 1
        assert metrics["candidates_merged"] == 1
        # Verify the Candidate object has merged claims
        assert len(candidates[0].claims) >= 2
        # Verify sources were merged
        assert len(candidates[0].sources) >= 2

    @patch("agent.editorial.evidence_extraction.llm_ops.chat")
    def test_malformed_json_fails_safely(self, mock_chat, config, sample_candidate):
        mock_result = Mock()
        mock_result.ok = True
        mock_result.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_result.input_tokens = 1000
        mock_result.output_tokens = 500
        mock_result.cost_usd = 0.01
        mock_result.duration_ms = 2000
        mock_chat.return_value = mock_result
        
        candidates, metrics = extract_structured_evidence([sample_candidate], config)
        
        assert metrics["candidates_extracted"] == 0
        assert "Malformed JSON" in metrics["validation_failures"][0]
        # Verify the Candidate object was still created (without extraction)
        assert len(candidates) == 1
        assert isinstance(candidates[0], Candidate)

    @patch("agent.editorial.evidence_extraction.llm_ops.chat")
    def test_cache_hit_avoids_llm_call(self, mock_chat, config, sample_candidate, valid_extraction):
        # First call: LLM
        mock_result = Mock()
        mock_result.ok = True
        mock_result.json.return_value = valid_extraction
        mock_result.input_tokens = 1000
        mock_result.output_tokens = 500
        mock_result.cost_usd = 0.01
        mock_result.duration_ms = 2000
        mock_chat.return_value = mock_result
        
        candidates1, metrics1 = extract_structured_evidence([sample_candidate], config)
        assert metrics1["llm_calls"] == 1
        assert metrics1["cache_hits"] == 0
        
        # Second call: cache hit
        candidates2, metrics2 = extract_structured_evidence([sample_candidate], config)
        assert metrics2["llm_calls"] == 0
        assert metrics2["cache_hits"] == 1

    def test_candidate_limit_enforced(self, config, sample_candidate):
        config = ExtractionConfig(enabled=True, max_candidates_per_run=1, cache_path=config.cache_path)
        candidates = [sample_candidate.copy() for _ in range(5)]
        
        with patch("agent.editorial.evidence_extraction.llm_ops.chat") as mock_chat:
            mock_result = Mock()
            mock_result.ok = False
            mock_result.error = "Test"
            mock_result.input_tokens = 0
            mock_result.output_tokens = 0
            mock_result.cost_usd = 0.0
            mock_result.duration_ms = 0
            mock_chat.return_value = mock_result
            
            result, metrics = extract_structured_evidence(candidates, config)
            
            # Only 1 candidate should be processed
            assert mock_chat.call_count == 1

    def test_failed_extraction_preserves_original(self, config, sample_candidate):
        original_metadata = sample_candidate["metadata"].copy()
        
        with patch("agent.editorial.evidence_extraction.llm_ops.chat") as mock_chat:
            mock_result = Mock()
            mock_result.ok = False
            mock_result.error = "LLM failed"
            mock_result.input_tokens = 0
            mock_result.output_tokens = 0
            mock_result.cost_usd = 0.0
            mock_result.duration_ms = 0
            mock_chat.return_value = mock_result
            
            candidates, metrics = extract_structured_evidence([sample_candidate], config)
            
            # Original candidate should be preserved (as a Candidate object)
            assert len(candidates) == 1
            assert isinstance(candidates[0], Candidate)
            # Verify metadata was preserved
            assert candidates[0].metadata.get("fetched_evidence") == original_metadata["fetched_evidence"]


class TestFingerprints:
    def test_candidate_fingerprint_stable(self, sample_candidate):
        fp1 = candidate_fingerprint(sample_candidate)
        fp2 = candidate_fingerprint(sample_candidate)
        assert fp1 == fp2

    def test_evidence_fingerprint_stable(self, sample_candidate):
        evidence = sample_candidate["metadata"]["fetched_evidence"]
        fp1 = evidence_fingerprint(evidence)
        fp2 = evidence_fingerprint(evidence)
        assert fp1 == fp2

    def test_different_evidence_different_fingerprint(self, sample_candidate):
        evidence1 = sample_candidate["metadata"]["fetched_evidence"]
        evidence2 = [{"url": "https://different.com", "content": "Different content"}]
        
        fp1 = evidence_fingerprint(evidence1)
        fp2 = evidence_fingerprint(evidence2)
        assert fp1 != fp2
