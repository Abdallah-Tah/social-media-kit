"""Tests for Phase 2: campaigns, status vocabulary extension, and history."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))


# ── Status vocabulary ────────────────────────────────────────────────────────

def test_draft_new_statuses_accepted(tmp_path, monkeypatch):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    d = drafts.ContentDraft(title="T", status="idea")
    drafts.save_draft(d)
    loaded = drafts.load_draft(d.draft_id)
    assert loaded.status == "idea"


def test_draft_needs_review_accepted(tmp_path, monkeypatch):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    d = drafts.ContentDraft(title="T", status="needs_review")
    drafts.save_draft(d)
    loaded = drafts.load_draft(d.draft_id)
    assert loaded.status == "needs_review"


def test_draft_reviewed_migrated_to_needs_review(tmp_path, monkeypatch):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    d = drafts.ContentDraft(title="T")
    # Simulate old file with "reviewed" status
    data = d.to_dict()
    data["status"] = "reviewed"
    path = tmp_path / f"{d.draft_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = drafts.load_draft(d.draft_id)
    assert loaded.status == "needs_review"


def test_draft_history_records_status_transition(tmp_path, monkeypatch):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    d = drafts.ContentDraft(title="T", status="draft")
    drafts.save_draft(d)
    drafts.update_draft(d.draft_id, {"status": "needs_review"})
    loaded = drafts.load_draft(d.draft_id)
    assert len(loaded.history) == 1
    assert loaded.history[0]["from"] == "draft"
    assert loaded.history[0]["to"] == "needs_review"
    assert "ts" in loaded.history[0]


def test_draft_history_accumulates(tmp_path, monkeypatch):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    d = drafts.ContentDraft(title="T", status="draft")
    drafts.save_draft(d)
    drafts.update_draft(d.draft_id, {"status": "needs_review"})
    drafts.update_draft(d.draft_id, {"status": "approved"})
    loaded = drafts.load_draft(d.draft_id)
    assert len(loaded.history) == 2
    assert loaded.history[1]["from"] == "needs_review"
    assert loaded.history[1]["to"] == "approved"


def test_draft_history_not_added_when_status_unchanged(tmp_path, monkeypatch):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    d = drafts.ContentDraft(title="T", status="draft")
    drafts.save_draft(d)
    drafts.update_draft(d.draft_id, {"title": "New Title"})
    loaded = drafts.load_draft(d.draft_id)
    assert loaded.history == []


def test_draft_seo_fields_saved(tmp_path, monkeypatch):
    from agent import drafts
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path)
    d = drafts.ContentDraft(title="T")
    drafts.save_draft(d)
    drafts.update_draft(d.draft_id, {"seo_title": "SEO T", "seo_description": "desc"})
    loaded = drafts.load_draft(d.draft_id)
    assert loaded.seo_title == "SEO T"
    assert loaded.seo_description == "desc"


def test_social_draft_reviewed_migrated(tmp_path, monkeypatch):
    from agent import social_drafts
    monkeypatch.setattr(social_drafts, "SOCIAL_DRAFTS_DIR", tmp_path)
    sd = social_drafts.SocialDraft(platform="linkedin", title="T")
    data = sd.to_dict()
    data["status"] = "reviewed"
    path = tmp_path / f"{sd.draft_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = social_drafts.load_social_draft(sd.draft_id)
    assert loaded.status == "needs_review"


def test_social_draft_history_on_status_change(tmp_path, monkeypatch):
    from agent import social_drafts
    monkeypatch.setattr(social_drafts, "SOCIAL_DRAFTS_DIR", tmp_path)
    sd = social_drafts.SocialDraft(platform="linkedin", title="T", status="draft")
    social_drafts.save_social_draft(sd)
    social_drafts.update_social_draft(sd.draft_id, {"status": "approved"})
    loaded = social_drafts.load_social_draft(sd.draft_id)
    assert len(loaded.history) == 1
    assert loaded.history[0]["from"] == "draft"
    assert loaded.history[0]["to"] == "approved"


# ── Campaign creation ────────────────────────────────────────────────────────

SAMPLE_CARD = {
    "rank": 1,
    "previously_seen": False,
    "cluster": {
        "headline": "AI rewrites how we build APIs",
        "summary": "New patterns emerging.",
        "sources": ["TechCrunch"],
        "urls": ["https://example.com/article"],
        "latest": "2026-07-11T00:00:00Z",
    },
    "recommendation": {
        "recommendation": "blog",
        "confidence_score": 0.85,
        "suggested_angle": "Practical builder angle",
        "suggested_hook": "Here is what changed",
        "reason": "High signal.",
    },
    "opportunity": {"opportunity_score": 75},
    "trend": {"direction": "growing"},
    "authority": {"final_score": 0.8},
}

SAMPLE_BRIEF = {
    "content_type": "blog",
    "title": "AI and APIs: A Builder's Guide",
    "hook": "Here is what changed for API builders.",
    "angle": "Practical builder angle",
    "key_points": ["Point 1", "Point 2"],
    "call_to_action": "Read more.",
}


def _patch_campaign_dirs(tmp_path, monkeypatch):
    from agent import drafts, social_drafts, campaigns
    monkeypatch.setattr(drafts, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(social_drafts, "SOCIAL_DRAFTS_DIR", tmp_path / "social_drafts")
    monkeypatch.setattr(campaigns, "CAMPAIGNS_DIR", tmp_path / "campaigns")
    (tmp_path / "drafts").mkdir()
    (tmp_path / "social_drafts").mkdir()
    (tmp_path / "campaigns").mkdir()
    return campaigns


def test_create_campaign_returns_campaign(tmp_path, monkeypatch):
    campaigns = _patch_campaign_dirs(tmp_path, monkeypatch)
    c = campaigns.create_campaign(SAMPLE_CARD, SAMPLE_BRIEF, platforms=["linkedin", "facebook"])
    assert c.campaign_id
    assert c.headline == "AI rewrites how we build APIs"
    assert c.content_draft_id
    assert "linkedin" in c.social_draft_ids
    assert "facebook" in c.social_draft_ids


def test_create_campaign_persists_json(tmp_path, monkeypatch):
    campaigns = _patch_campaign_dirs(tmp_path, monkeypatch)
    c = campaigns.create_campaign(SAMPLE_CARD, SAMPLE_BRIEF, platforms=["x"])
    loaded = campaigns.load_campaign(c.campaign_id)
    assert loaded is not None
    assert loaded.campaign_id == c.campaign_id


def test_create_campaign_backlinks_content_draft(tmp_path, monkeypatch):
    campaigns = _patch_campaign_dirs(tmp_path, monkeypatch)
    from agent import drafts
    c = campaigns.create_campaign(SAMPLE_CARD, SAMPLE_BRIEF, platforms=["linkedin"])
    content = drafts.load_draft(c.content_draft_id)
    assert content.campaign_id == c.campaign_id


def test_create_campaign_backlinks_social_drafts(tmp_path, monkeypatch):
    campaigns = _patch_campaign_dirs(tmp_path, monkeypatch)
    from agent import social_drafts
    c = campaigns.create_campaign(SAMPLE_CARD, SAMPLE_BRIEF, platforms=["reddit"])
    sd = social_drafts.load_social_draft(c.social_draft_ids["reddit"])
    assert sd.campaign_id == c.campaign_id


def test_create_campaign_without_brief_uses_card_data(tmp_path, monkeypatch):
    campaigns = _patch_campaign_dirs(tmp_path, monkeypatch)
    c = campaigns.create_campaign(SAMPLE_CARD, brief=None, platforms=["newsletter"])
    assert c.content_draft_id
    assert "newsletter" in c.social_draft_ids


def test_create_campaign_filters_invalid_platforms(tmp_path, monkeypatch):
    campaigns = _patch_campaign_dirs(tmp_path, monkeypatch)
    c = campaigns.create_campaign(SAMPLE_CARD, SAMPLE_BRIEF, platforms=["linkedin", "tiktok", "pinterest"])
    assert "linkedin" in c.social_draft_ids
    assert "tiktok" not in c.social_draft_ids
    assert "pinterest" not in c.social_draft_ids


def test_get_campaign_pipeline_all_draft(tmp_path, monkeypatch):
    campaigns = _patch_campaign_dirs(tmp_path, monkeypatch)
    c = campaigns.create_campaign(SAMPLE_CARD, SAMPLE_BRIEF, platforms=["linkedin"])
    pipeline = campaigns.get_campaign_pipeline(c)
    assert pipeline["content"]["status"] == "draft"
    assert pipeline["social"]["linkedin"]["status"] == "draft"
    assert pipeline["overall"] == "draft"


def test_list_campaigns(tmp_path, monkeypatch):
    campaigns = _patch_campaign_dirs(tmp_path, monkeypatch)
    campaigns.create_campaign(SAMPLE_CARD, SAMPLE_BRIEF, platforms=["x"])
    campaigns.create_campaign(SAMPLE_CARD, SAMPLE_BRIEF, platforms=["reddit"])
    listed = campaigns.list_campaigns()
    assert len(listed) == 2


def test_load_campaign_unknown_returns_none(tmp_path, monkeypatch):
    campaigns = _patch_campaign_dirs(tmp_path, monkeypatch)
    assert campaigns.load_campaign("nonexistent") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
