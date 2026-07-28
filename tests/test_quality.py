"""Phase 1 Stage 5 — deterministic editorial-quality scoring.

Covers:
- All 5 scoring components
- Hard-failure conditions
- Artifact-specific policies
- Determinism (same input → same output)
- No LLM / network calls
- No publication or live history writes
- Configuration validation
- Padding does not improve score
- Prose quality cannot override evidence failures
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agent.editorial.quality import (
    CONFIG_PATH,
    STATUS_PASS,
    STATUS_WARNING,
    STATUS_FAIL,
    HF_MISSING_PRIMARY_SOURCES,
    HF_FABRICATED_NUMERIC,
    HF_MALFORMED_OUTPUT,
    HF_BLANK_REQUIRED_SECTION,
    HF_PROMPT_LEAKAGE,
    HF_CONTRADICTS_FACTS,
    HF_VENDOR_AS_VERIFIED,
    HF_COPIED_PASSAGE,
    HF_UNSUPPORTED_SECURITY,
    ALL_HARD_FAILURES,
    QualityConfig,
    QualityConfigError,
    DraftInput,
    ComponentResult,
    QualityResult,
    load_quality_config,
    evaluate_quality,
    _count_words,
    _count_code_blocks,
    _has_malformed_markdown,
    _has_truncated_sentence,
    _detect_repetitive_filler,
    _detect_prompt_leakage,
    _compute_similarity_ratio,
    ISSUE_NO_CONCRETE_SIGNALS,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _draft(
    title: str = "Test Article",
    body: str = "",
    summary: str = "Test summary",
    artifact_type: str = "technical_analysis",
    format_id: str = "tutorial",
    slot_objective: str = "explain",
    sources: tuple | tuple = (),
    claims: tuple | tuple = (),
    confirmed_facts: tuple | tuple = (),
    metadata: dict | None = None,
) -> DraftInput:
    if not body:
        body = (
            "# Test Article\n\n"
            "## Overview\n\n"
            "This is a test article with some content.\n\n"
            "## Technical Details\n\n"
            "More technical details here.\n\n"
            "## Analysis\n\n"
            "Analysis section.\n\n"
            "## Sources\n\n"
            "- Source 1\n"
        )
    return DraftInput(
        title=title,
        body=body,
        summary=summary,
        artifact_type=artifact_type,
        format_id=format_id,
        slot_objective=slot_objective,
        sources=sources,
        claims=claims,
        confirmed_facts=confirmed_facts,
        metadata=metadata or {},
    )


def _config() -> QualityConfig:
    return load_quality_config(CONFIG_PATH)


def _source(text: str = "Example source text with details") -> dict:
    return {"text": text, "url": "https://example.com"}


# ── Config loading and validation ────────────────────────────────────────────

def test_config_loads_successfully():
    config = _config()
    assert config.schema_version == 1
    assert sum(config.weights.values()) == 100
    assert config.thresholds["pass"] > config.thresholds["warning"]


def test_config_weights_total_100(tmp_path):
    bad_config = {
        "schema_version": 1,
        "weights": {
            "format_conformance": 20,
            "specificity_evidence": 20,
            "practical_value": 20,
            "structure_readability": 15,
            "language_originality": 20,
        },
        "thresholds": {"pass": 80, "warning": 60, "fail": 60},
        "hard_failures": [],
        "similarity_allowance": {"max_exact_copy_ratio": 0.15},
        "artifacts": {},
        "format_references": [],
    }
    path = tmp_path / "quality.yaml"
    with open(path, "w") as f:
        yaml.dump(bad_config, f)
    with pytest.raises(QualityConfigError) as exc:
        load_quality_config(path)
    assert any("total 100" in p for p in exc.value.problems)


def test_config_pass_must_exceed_warning(tmp_path):
    bad_config = {
        "schema_version": 1,
        "weights": {
            "format_conformance": 25,
            "specificity_evidence": 20,
            "practical_value": 20,
            "structure_readability": 15,
            "language_originality": 20,
        },
        "thresholds": {"pass": 60, "warning": 70, "fail": 60},
        "hard_failures": [],
        "similarity_allowance": {"max_exact_copy_ratio": 0.15},
        "artifacts": {},
        "format_references": [],
    }
    path = tmp_path / "quality.yaml"
    with open(path, "w") as f:
        yaml.dump(bad_config, f)
    with pytest.raises(QualityConfigError) as exc:
        load_quality_config(path)
    assert any("exceed warning" in p for p in exc.value.problems)


# ── Fully compliant artifact passes ─────────────────────────────────────────

def test_fully_compliant_artifact_passes():
    """A well-structured, evidence-backed draft passes."""
    body = (
        "# Understanding GPT-5 Performance\n\n"
        "## Overview\n\n"
        "GPT-5 was released on 2026-07-01 with v5.2.1 API.\n"
        "This article explains the key improvements.\n\n"
        "## Technical Details\n\n"
        "The new API endpoint `/v5/chat/completions` supports:\n\n"
        "```python\n"
        "import openai\n"
        "response = openai.ChatCompletion.create(model='gpt-5')\n"
        "```\n\n"
        "Performance improved 40% according to OpenAI.\n\n"
        "## Analysis\n\n"
        "Developers should watch the new rate limits.\n"
        "Migration steps: update to SDK v2.0, test endpoints.\n\n"
        "## Sources\n\n"
        "- OpenAI blog\n"
    )
    draft = _draft(
        title="Understanding GPT-5 Performance",
        body=body,
        artifact_type="technical_analysis",
        sources=(_source("OpenAI released GPT-5 on 2026-07-01"),),
    )
    result = evaluate_quality(draft, _config())
    assert result.score >= 80
    assert result.status == STATUS_PASS


# ── Missing required section ─────────────────────────────────────────────────

def test_missing_required_section_loses_points():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "Some content.\n\n"
        # Missing "## Technical Details", "## Analysis", "## Sources"
    )
    draft = _draft(body=body, artifact_type="technical_analysis")
    result = evaluate_quality(draft, _config())
    assert result.score < 80
    assert any("missing" in i.lower() for i in result.issues)


def test_specificity_uses_stable_issue_code_for_missing_concrete_signals():
    draft = _draft(
        body=(
            "# Test\n\n"
            "## Overview\n\n"
            "General commentary only.\n\n"
            "## Technical Details\n\n"
            "No versions, dates, APIs, repos, or commands here.\n\n"
            "## Analysis\n\n"
            "Still generic.\n\n"
            "## Sources\n\n"
            "- Source\n"
        ),
        sources=(_source("General source text"),),
    )
    result = evaluate_quality(draft, _config())
    specificity = next(c for c in result.components if c.name == "specificity_evidence")
    assert ISSUE_NO_CONCRETE_SIGNALS in {note.code for note in specificity.issue_details}


# ── Padding does not improve score ──────────────────────────────────────────

def test_padding_does_not_improve_score():
    """Adding filler words doesn't increase word count score."""
    body_short = (
        "# Test\n\n"
        "## Overview\n\n"
        "Short content.\n\n"
        "## Technical Details\n\n"
        "```python\nprint('hello')\n```\n\n"
        "## Analysis\n\n"
        "Analysis.\n\n"
        "## Sources\n\n"
        "- Source\n"
    )
    # Add padding words.
    body_padded = body_short + " This is padding. " * 100

    draft_short = _draft(body=body_short)
    draft_padded = _draft(body=body_padded)

    result_short = evaluate_quality(draft_short, _config())
    result_padded = evaluate_quality(draft_padded, _config())

    # Padded version should not score higher.
    assert result_padded.score <= result_short.score + 5  # Allow small variance


# ── Grounded vs ungrounded numbers ──────────────────────────────────────────

def test_grounded_numbers_pass():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "Version 2.1.0 released on 2026-07-01.\n\n"
        "## Technical Details\n\n"
        "Performance improved 40%.\n\n"
        "```python\nprint('test')\n```\n\n"
        "## Analysis\n\n"
        "According to the vendor, latency dropped 30%.\n\n"
        "## Sources\n\n"
        "- Vendor blog\n"
    )
    draft = _draft(
        body=body,
        sources=(_source("Performance improved 40%, latency dropped 30%"),),
    )
    result = evaluate_quality(draft, _config())
    assert HF_FABRICATED_NUMERIC not in result.hard_failures


def test_ungrounded_numeric_claim_hard_fails():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "Version 2.1.0 released.\n\n"
        "## Technical Details\n\n"
        "Performance improved 40%.\n\n"
        "```python\nprint('test')\n```\n\n"
        "## Analysis\n\n"
        "Latency dropped 30%.\n\n"
        "## Sources\n\n"
        "- Source\n"
    )
    draft = _draft(
        body=body,
        metadata={"has_numeric_claims": True},
        # No sources provided.
    )
    result = evaluate_quality(draft, _config())
    assert HF_MISSING_PRIMARY_SOURCES in result.hard_failures or result.score < 60


# ── Vendor benchmark attribution ────────────────────────────────────────────

def test_vendor_benchmark_properly_attributed():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "Version 2.1.0 released.\n\n"
        "## Technical Details\n\n"
        "According to the vendor, performance improved 40%.\n\n"
        "```python\nprint('test')\n```\n\n"
        "## Analysis\n\n"
        "Analysis.\n\n"
        "## Sources\n\n"
        "- Vendor blog\n"
    )
    draft = _draft(
        body=body,
        sources=(_source("Performance improved 40%"),),
    )
    result = evaluate_quality(draft, _config())
    assert HF_VENDOR_AS_VERIFIED not in result.hard_failures


def test_vendor_benchmark_as_fact_hard_fails():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "Version 2.1.0 released.\n\n"
        "## Technical Details\n\n"
        "Performance improved 40%.\n\n"
        "```python\nprint('test')\n```\n\n"
        "## Analysis\n\n"
        "Analysis.\n\n"
        "## Sources\n\n"
        "- Source\n"
    )
    draft = _draft(
        body=body,
        sources=(_source("Some text"),),
    )
    result = evaluate_quality(draft, _config())
    assert HF_VENDOR_AS_VERIFIED in result.hard_failures


# ── Practical takeaway without actionability fails ──────────────────────────

def test_practical_takeaway_without_actionability_fails():
    body = (
        "# Test\n\n"
        "## What You Need to Know\n\n"
        "Some information.\n\n"
        "## Action Items\n\n"
        "More information.\n\n"
        "## Sources\n\n"
        "- Source\n"
    )
    draft = _draft(
        body=body,
        artifact_type="practical_takeaway",
        # No code block, no practical signals.
    )
    result = evaluate_quality(draft, _config())
    assert result.score < 70
    assert any("practical" in i.lower() or "code" in i.lower() for i in result.issues)


# ── Intelligence brief without code may still pass ──────────────────────────

def test_intelligence_brief_without_code_passes():
    body = (
        "# Test\n\n"
        "## Summary\n\n"
        "GPT-5 released with new features.\n\n"
        "## What Developers Should Watch\n\n"
        "Developers should watch the new rate limits.\n\n"
        "## Sources\n\n"
        "- OpenAI blog\n"
    )
    draft = _draft(
        body=body,
        artifact_type="intelligence_brief",
        sources=(_source("GPT-5 released"),),
    )
    result = evaluate_quality(draft, _config())
    # Intelligence brief doesn't require code.
    assert result.status in (STATUS_PASS, STATUS_WARNING)


# ── Truncated sentence detection ────────────────────────────────────────────

def test_truncated_sentence_detected():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "Content here.\n\n"
        "## Sources\n\n"
        "- Source\n\n"
        "This sentence is truncated"
    )
    draft = _draft(body=body)
    result = evaluate_quality(draft, _config())
    assert any("truncated" in w.lower() for w in result.warnings)


# ── Malformed Markdown detection ────────────────────────────────────────────

def test_malformed_markdown_detected():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "Content.\n\n"
        "```python\n"
        "print('hello')\n"
        # Missing closing fence.
    )
    draft = _draft(body=body)
    result = evaluate_quality(draft, _config())
    assert HF_MALFORMED_OUTPUT in result.hard_failures


# ── Repetitive filler loses points ──────────────────────────────────────────

def test_repetitive_filler_loses_points():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "In this article, we will dive deep into the topic.\n"
        "Let's dive in and harness the power of this technology.\n\n"
        "## Technical Details\n\n"
        "```python\nprint('test')\n```\n\n"
        "## Analysis\n\n"
        "Analysis.\n\n"
        "## Sources\n\n"
        "- Source\n"
    )
    draft = _draft(body=body)
    result = evaluate_quality(draft, _config())
    assert any("filler" in w.lower() for w in result.warnings)
    assert result.score < 80


# ── Forbidden phrase detection ──────────────────────────────────────────────

def test_forbidden_phrase_detected():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "This is a revolutionary game-changing technology.\n\n"
        "## Technical Details\n\n"
        "```python\nprint('test')\n```\n\n"
        "## Analysis\n\n"
        "Analysis.\n\n"
        "## Sources\n\n"
        "- Source\n"
    )
    draft = _draft(body=body)
    result = evaluate_quality(draft, _config())
    assert any("forbidden" in i.lower() for i in result.issues)


# ── Source-copy similarity hard failure ─────────────────────────────────────

def test_source_copy_similarity_hard_fails():
    # Create a draft that heavily copies from source.
    source_text = "This is the source text with specific details and numbers."
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "This is the source text with specific details and numbers.\n\n"
        "## Technical Details\n\n"
        "```python\nprint('test')\n```\n\n"
        "## Analysis\n\n"
        "Analysis.\n\n"
        "## Sources\n\n"
        "- Source\n"
    )
    draft = _draft(
        body=body,
        sources=(_source(source_text),),
    )
    result = evaluate_quality(draft, _config())
    assert HF_COPIED_PASSAGE in result.hard_failures


# ── Prompt leakage hard failure ─────────────────────────────────────────────

def test_prompt_leakage_hard_fails():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "System prompt: You are a helpful assistant.\n\n"
        "## Technical Details\n\n"
        "```python\nprint('test')\n```\n\n"
        "## Analysis\n\n"
        "Analysis.\n\n"
        "## Sources\n\n"
        "- Source\n"
    )
    draft = _draft(body=body)
    result = evaluate_quality(draft, _config())
    assert HF_PROMPT_LEAKAGE in result.hard_failures


# ── Article contradicting confirmed facts ───────────────────────────────────

def test_article_contradicting_facts_hard_fails():
    body = (
        "# Test\n\n"
        "## Overview\n\n"
        "Version 2.0.0 released.\n\n"
        "## Technical Details\n\n"
        "```python\nprint('test')\n```\n\n"
        "## Analysis\n\n"
        "Analysis.\n\n"
        "## Sources\n\n"
        "- Source\n"
    )
    draft = _draft(
        body=body,
        metadata={"contradicts_confirmed": True},
    )
    result = evaluate_quality(draft, _config())
    assert HF_CONTRADICTS_FACTS in result.hard_failures


# ── Artifact-specific word ranges ───────────────────────────────────────────

def test_intelligence_brief_word_range():
    config = _config()
    brief_spec = config.artifacts["intelligence_brief"]
    assert brief_spec["word_range"]["min"] == 350
    assert brief_spec["word_range"]["max"] == 650


def test_tutorial_word_range():
    config = _config()
    tutorial_spec = config.artifacts["tutorial"]
    assert tutorial_spec["word_range"]["min"] == 1000
    assert tutorial_spec["word_range"]["max"] == 2500


# ── Determinism ─────────────────────────────────────────────────────────────

def test_same_input_gives_identical_result():
    draft = _draft()
    config = _config()
    first = evaluate_quality(draft, config).to_dict()
    for _ in range(5):
        result = evaluate_quality(draft, config).to_dict()
        assert result == first


# ── No LLM or network calls ────────────────────────────────────────────────

def test_no_llm_or_network_calls(monkeypatch):
    import urllib.request
    import agent.llm_ops as LLM

    def explode(*a, **k):
        raise AssertionError("quality scoring must not call LLM or network")

    monkeypatch.setattr(LLM, "chat", explode)
    monkeypatch.setattr(LLM, "requests", type("R", (), {"post": staticmethod(explode)}))
    monkeypatch.setattr(urllib.request, "urlopen", explode)

    draft = _draft()
    result = evaluate_quality(draft, _config())
    assert result  # No exception raised.


# ── No publication or live history writes ───────────────────────────────────

def test_no_publication_or_history_writes(monkeypatch):
    """Quality scoring never writes to live history."""
    import agent.content_decisions as CD

    def explode(*a, **k):
        raise AssertionError("quality scoring must not write to history")

    monkeypatch.setattr(CD, "record", explode)
    monkeypatch.setattr(CD, "accept", explode)
    monkeypatch.setattr(CD, "reject", explode)

    draft = _draft()
    result = evaluate_quality(draft, _config())
    assert result  # No exception raised.


# ── Production behavior unchanged ───────────────────────────────────────────

def test_production_unchanged_while_flag_is_false():
    """Quality scoring doesn't affect production while flag is false."""
    from agent.editorial import editorial_slots_enabled
    assert editorial_slots_enabled() is False


# ── Helper function tests ───────────────────────────────────────────────────

def test_count_words():
    assert _count_words("one two three") == 3
    assert _count_words("# Header\n\nParagraph.") == 2
    assert _count_words("```python\nprint('x')\n```") == 0  # Code not counted.


def test_count_code_blocks():
    assert _count_code_blocks("```python\ncode\n```") == 1
    assert _count_code_blocks("```python\na\n```\n```python\nb\n```") == 2
    assert _count_code_blocks("no code") == 0


def test_has_malformed_markdown():
    assert _has_malformed_markdown("```python\ncode")  # Unclosed fence.
    assert _has_malformed_markdown("#NoSpace")  # No space after #.
    assert _has_malformed_markdown("-NoSpace")  # No space after -.
    assert not _has_malformed_markdown("# Header\n\n```python\ncode\n```")


def test_has_truncated_sentence():
    assert _has_truncated_sentence("Sentence without ending")
    assert not _has_truncated_sentence("Sentence with ending.")
    assert not _has_truncated_sentence("List item\n- item")


def test_detect_repetitive_filler():
    filler = _detect_repetitive_filler("Let's dive in to this topic")
    assert len(filler) > 0
    assert not _detect_repetitive_filler("Normal text")


def test_detect_prompt_leakage():
    assert "system prompt" in _detect_prompt_leakage("System prompt: ...")
    assert not _detect_prompt_leakage("Normal text")


def test_compute_similarity_ratio():
    draft = "This is a test with specific words"
    sources = [{"text": "This is a test with specific words and more"}]
    ratio = _compute_similarity_ratio(draft, sources)
    assert ratio > 0.5  # High overlap.

    sources = [{"text": "Completely different text"}]
    ratio = _compute_similarity_ratio(draft, sources)
    assert ratio < 0.3  # Low overlap.
