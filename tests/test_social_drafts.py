"""Tests for social draft generation from published blog posts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent.social_drafts import (
    SUPPORTED_PLATFORMS,
    SocialDraft,
    create_social_drafts_from_blog,
    delete_social_draft,
    generate_social_drafts,
    list_social_drafts,
    load_social_draft,
    update_social_draft,
)


SUBSTANTIVE_BODY = (
    "This guide walks through a concrete API integration, including the error handling "
    "and request boundaries that keep a production service from silently returning bad data. "
    "It also explains how to test failures locally before the code reaches a shared environment. "
    "The examples focus on a small, repeatable workflow rather than a generic overview."
)


def test_cannot_generate_without_blog_url(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        drafts = generate_social_drafts("abc", "", "Title", "Body", ["linkedin"])
        assert drafts == []
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_generates_selected_platforms_only(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        drafts = create_social_drafts_from_blog(
            "abc", "https://buildwithabdallah.com/tutorials/test", "A practical API integration guide", SUBSTANTIVE_BODY,
            ["linkedin", "x"],
        )
        assert len(drafts) == 2
        platforms = {d.platform for d in drafts}
        assert platforms == {"linkedin", "x"}
        assert all(d.blog_url == "https://buildwithabdallah.com/tutorials/test" for d in drafts)
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_blog_url_included_in_text(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        url = "https://buildwithabdallah.com/tutorials/ai-guide"
        drafts = create_social_drafts_from_blog("abc", url, "A practical AI integration guide", SUBSTANTIVE_BODY, ["facebook"])
        assert drafts[0].blog_url == url
        assert url in drafts[0].text
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_social_drafts_are_editable(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        drafts = create_social_drafts_from_blog(
            "abc", "https://example.com/blog", "A practical API integration guide", SUBSTANTIVE_BODY, ["linkedin"],
        )
        sd = drafts[0]
        updated = update_social_draft(sd.draft_id, {"text": "Updated text", "status": "approved"})
        assert updated is not None
        assert updated.text == "Updated text"
        assert updated.status == "approved"
        assert updated.updated_at != updated.created_at
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_no_live_publishing_happens(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        drafts = create_social_drafts_from_blog(
            "abc", "https://example.com/blog", "A practical API integration guide", SUBSTANTIVE_BODY, list(SUPPORTED_PLATFORMS),
        )
        assert len(drafts) == len(SUPPORTED_PLATFORMS)
        assert all(d.status == "draft" for d in drafts)
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_list_social_drafts_by_source_and_status(tmp_path):
    from agent import social_drafts
    original_dir = social_drafts.SOCIAL_DRAFTS_DIR
    social_drafts.SOCIAL_DRAFTS_DIR = tmp_path
    try:
        create_social_drafts_from_blog(
            "s1", "https://example.com/1", "A practical integration guide", SUBSTANTIVE_BODY, ["linkedin"],
        )
        s2 = create_social_drafts_from_blog(
            "s2", "https://example.com/2", "Another practical integration guide", SUBSTANTIVE_BODY, ["linkedin"],
        )[0]
        update_social_draft(s2.draft_id, {"status": "approved"})
        assert len(list_social_drafts(source_draft_id="s1")) == 1
        assert len(list_social_drafts(source_draft_id="s2")) == 1
        assert len(list_social_drafts(status="approved")) == 1
    finally:
        social_drafts.SOCIAL_DRAFTS_DIR = original_dir


def test_placeholder_content_cannot_create_social_drafts():
    drafts = generate_social_drafts(
        "abc",
        "https://example.com/article",
        "Apple targets dozens of OpenAI employees with legal letters",
        "# Apple targets dozens of OpenAI employees with legal letters\n\n## Angle\nDeep technical analysis of the news and what it means for openai.\n\n## Builder takeaway\nExplain why this matters and what the reader should do next.",
        ["linkedin", "x"],
    )
    assert drafts == []


def test_title_echo_cannot_be_published_as_a_social_draft():
    from agent.social_drafts import _social_post_quality_error

    error = _social_post_quality_error(
        "Claude Code uses Bun written in Rust now",
        "Claude Code uses Bun written in Rust now. Claude Code uses Bun written in Rust now. "
        "Claude Code uses Bun written in Rust now. Claude Code uses Bun written in Rust now.",
    )
    assert error == "social draft mostly repeats its headline and cannot be published"


# ── Content-quality guard (short title / short body / placeholder) ──────────

_GOOD_TITLE = "Rate limiting Laravel queues without losing jobs"
_GOOD_BODY = (
    "Laravel queue workers will happily run the same job twice when a worker is "
    "restarted mid-execution, because the reserved_at timestamp is cleared before "
    "the handler finishes. That double execution stays invisible until it charges "
    "a customer twice.\n\n"
    "Wrap the handler in an atomic Redis lock keyed on the job payload hash and "
    "release it only after the database transaction commits.\n"
)


def _gen(title=_GOOD_TITLE, body=_GOOD_BODY, platforms=("linkedin",)):
    from agent.social_drafts import generate_social_drafts
    return generate_social_drafts("src", "https://example.com/p", title, body, list(platforms))


def test_guard_allows_substantive_content():
    drafts = _gen(platforms=("linkedin", "x", "reddit"))
    assert {d.platform for d in drafts} == {"linkedin", "x", "reddit"}
    assert all(d.text.strip() for d in drafts)


def test_guard_rejects_a_short_title():
    from agent.social_drafts import _quality_error
    assert "title" in (_quality_error("Short", _GOOD_BODY, "a summary") or "")
    assert _gen(title="Short") == []


def test_guard_rejects_a_short_body():
    from agent.social_drafts import _quality_error
    assert "too short" in (_quality_error(_GOOD_TITLE, "Body", "") or "")
    assert _gen(body="Body") == []


def test_guard_rejects_placeholder_copy():
    """create_draft() emits this skeleton text; it must never reach a platform."""
    from agent.social_drafts import _quality_error, _contains_placeholder

    skeleton = (
        "## Builder takeaway\n\n"
        "Explain why this matters and what the reader should do next.\n\n"
        "## Call to action\n\nRead.\n" + "padding text " * 30
    )
    assert _contains_placeholder(skeleton)
    assert "placeholder" in (_quality_error(_GOOD_TITLE, skeleton, "s") or "")
    assert _gen(body=skeleton) == []


def test_platform_copy_has_no_per_article_special_cases():
    """Regression: hardcoded narratives were dispatched on loose substring match,
    so an unrelated article containing 'code review' published wrong copy."""
    from agent.social_drafts import _platform_copy

    linkedin, _fb, _x = _platform_copy(
        "A database migration that needed a code review",
        "We changed how the schema migration batches rows to avoid a long lock.",
        "https://example.com/p",
        ["BuildWithAbdallah"],
    )
    assert "Claude Code" not in linkedin
    assert "Most AI code reviews fail" not in linkedin
    assert "schema migration batches rows" in linkedin
