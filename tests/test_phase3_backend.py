"""Tests for Phase 3 backend: cover API, rewrite endpoint, draft SEO fields."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))


def _make_draft(tmp_path, monkeypatch, body="# Hello\n\nThis is draft body content.", title="Test Draft"):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    d = drafts.ContentDraft(title=title, body=body)
    drafts.save_draft(d)
    return d


# ── Cover API ────────────────────────────────────────────────────────────────

def test_get_cover_info_no_cover(tmp_path, monkeypatch):
    from agent import drafts
    d = _make_draft(tmp_path, monkeypatch)
    result = drafts.get_cover_info(d.draft_id)
    assert result["ok"] is True
    assert result["exists"] is False
    assert result["cover_image_url"] == ""
    assert "styles" in result
    assert "clean_tech" in result["styles"]


def test_get_cover_info_with_existing_cover(tmp_path, monkeypatch):
    from agent import drafts
    d = _make_draft(tmp_path, monkeypatch)
    d.cover_image_url = "https://example.com/cover.png"
    drafts.save_draft(d)
    result = drafts.get_cover_info(d.draft_id)
    assert result["exists"] is True
    assert result["cover_image_url"] == "https://example.com/cover.png"


def test_get_cover_info_unknown_draft(tmp_path, monkeypatch):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    result = drafts.get_cover_info("nonexistent")
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_generate_cover_for_draft_calls_image_generator(tmp_path, monkeypatch):
    from agent import drafts
    d = _make_draft(tmp_path, monkeypatch)
    fake_result = {"url": "https://cdn.example.com/cover.png", "path": "/tmp/cover.png", "provider": "card"}
    with patch("agent.drafts._generate_cover_for_draft", return_value=fake_result) as mock_gen:
        result = drafts.generate_cover_for_draft(d.draft_id, style="editorial")
    assert result["ok"] is True
    assert result["cover_image_url"] == "https://cdn.example.com/cover.png"
    assert result["style"] == "editorial"
    mock_gen.assert_called_once()


def test_generate_cover_for_draft_persists_url(tmp_path, monkeypatch):
    from agent import drafts
    d = _make_draft(tmp_path, monkeypatch)
    fake_result = {"url": "https://cdn.example.com/cover2.png"}
    with patch("agent.drafts._generate_cover_for_draft", return_value=fake_result):
        drafts.generate_cover_for_draft(d.draft_id, style="clean_tech")
    loaded = drafts.load_draft(d.draft_id)
    assert loaded.cover_image_url == "https://cdn.example.com/cover2.png"


def test_generate_cover_for_draft_failure(tmp_path, monkeypatch):
    from agent import drafts
    d = _make_draft(tmp_path, monkeypatch)
    with patch("agent.drafts._generate_cover_for_draft", return_value={}):
        result = drafts.generate_cover_for_draft(d.draft_id)
    assert result["ok"] is False


def test_cover_style_prompts_all_defined(tmp_path, monkeypatch):
    from agent.drafts import COVER_STYLE_PROMPTS
    for style in ("clean_tech", "editorial", "diagram", "thumbnail", "social_card"):
        assert style in COVER_STYLE_PROMPTS
        assert len(COVER_STYLE_PROMPTS[style]) > 10


# ── Rewriter ─────────────────────────────────────────────────────────────────

def test_rewrite_unknown_mode(tmp_path, monkeypatch):
    from agent import drafts
    d = _make_draft(tmp_path, monkeypatch)
    from agent.rewriter import rewrite_draft
    result = rewrite_draft(d.draft_id, "invalidmode")
    assert result["ok"] is False
    assert "unknown mode" in result["error"]


def test_rewrite_unknown_draft(tmp_path, monkeypatch):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    from agent.rewriter import rewrite_draft
    result = rewrite_draft("doesnotexist", "shorter")
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_rewrite_empty_body(tmp_path, monkeypatch):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    d = drafts.ContentDraft(title="T", body="   ")
    drafts.save_draft(d)
    from agent.rewriter import rewrite_draft
    result = rewrite_draft(d.draft_id, "shorter")
    assert result["ok"] is False
    assert "no body" in result["error"]


def test_rewrite_calls_llm_and_returns_body(tmp_path, monkeypatch):
    from agent import drafts
    d = _make_draft(tmp_path, monkeypatch, body="# Hello\n\nThis is body content.")

    mock_response = MagicMock()
    mock_response.text = "# Hello\n\nShorter version."

    mock_client = MagicMock()
    mock_client.complete.return_value = mock_response

    with patch("agent.rewriter.AgentConfig") as mock_cfg_cls, \
         patch("agent.rewriter.LLMClient", return_value=mock_client) as mock_llm_cls:
        mock_cfg = MagicMock()
        mock_cfg.provider = "anthropic"
        mock_cfg.model = "claude-sonnet-4-6"
        mock_cfg.api_key = "sk-test"
        mock_cfg_cls.load.return_value = mock_cfg

        from agent.rewriter import rewrite_draft
        result = rewrite_draft(d.draft_id, "shorter")

    assert result["ok"] is True
    assert result["body"] == "# Hello\n\nShorter version."
    assert result["mode"] == "shorter"
    mock_client.complete.assert_called_once()


def test_rewrite_modes_all_valid():
    from agent.rewriter import REWRITE_MODES
    for mode in ("shorter", "hook", "technical", "casual"):
        assert mode in REWRITE_MODES
        assert len(REWRITE_MODES[mode]) > 20


def test_rewrite_llm_error_returns_ok_false(tmp_path, monkeypatch):
    from agent import drafts
    d = _make_draft(tmp_path, monkeypatch)

    with patch("agent.rewriter.AgentConfig") as mock_cfg_cls, \
         patch("agent.rewriter.LLMClient") as mock_llm_cls:
        mock_cfg_cls.load.return_value = MagicMock(provider="anthropic", model="x", api_key="k")
        mock_llm_cls.return_value.complete.side_effect = RuntimeError("API key invalid")

        from agent.rewriter import rewrite_draft
        result = rewrite_draft(d.draft_id, "hook")

    assert result["ok"] is False
    assert "Rewrite failed" in result["error"]


# ── SEO fields end-to-end ─────────────────────────────────────────────────────

def test_seo_fields_persisted_via_update_draft(tmp_path, monkeypatch):
    from agent import drafts
    d = _make_draft(tmp_path, monkeypatch)
    drafts.update_draft(d.draft_id, {"seo_title": "SEO Title Here", "seo_description": "Meta desc."})
    loaded = drafts.load_draft(d.draft_id)
    assert loaded.seo_title == "SEO Title Here"
    assert loaded.seo_description == "Meta desc."


def test_seo_fields_in_to_dict(tmp_path, monkeypatch):
    from agent import drafts
    d = _make_draft(tmp_path, monkeypatch)
    drafts.update_draft(d.draft_id, {"seo_title": "SEO T", "seo_description": "D"})
    loaded = drafts.load_draft(d.draft_id)
    d_dict = loaded.to_dict()
    assert d_dict["seo_title"] == "SEO T"
    assert d_dict["seo_description"] == "D"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
