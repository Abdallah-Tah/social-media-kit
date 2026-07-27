"""Tests for read-only analytics engine."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent.analytics import (
    AnalyticsSnapshot,
    compute_analytics,
    export_csv,
    export_json,
    save_analytics,
)


def test_empty_dataset_returns_clean_metrics(tmp_path):
    from agent import analytics
    original_intel = analytics.INTEL_DIR
    original_drafts = analytics.DRAFTS_DIR
    original_social = analytics.SOCIAL_DIR
    analytics.INTEL_DIR = tmp_path / "intel"
    analytics.DRAFTS_DIR = tmp_path / "drafts"
    analytics.SOCIAL_DIR = tmp_path / "social"
    try:
        snapshot = compute_analytics()
        assert snapshot.intelligence["opportunities_processed"] == 0
        assert snapshot.editorial_funnel["drafts_created"] == 0
        assert snapshot.social["total_social_drafts"] == 0
        assert snapshot.performance["status"] == "not_connected"
    finally:
        analytics.INTEL_DIR = original_intel
        analytics.DRAFTS_DIR = original_drafts
        analytics.SOCIAL_DIR = original_social


def test_filters_by_days(tmp_path):
    from agent import analytics
    original_drafts = analytics.DRAFTS_DIR
    analytics.DRAFTS_DIR = tmp_path
    try:
        tmp_path.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        new = datetime.now(timezone.utc).isoformat()
        tmp_path.joinpath("old.json").write_text(f'{{"created_at": "{old}", "status": "draft"}}')
        tmp_path.joinpath("new.json").write_text(f'{{"created_at": "{new}", "status": "draft"}}')
        snapshot = compute_analytics(days=30)
        assert snapshot.editorial_funnel["drafts_created"] == 1
    finally:
        analytics.DRAFTS_DIR = original_drafts


def test_editorial_funnel_conversion(tmp_path):
    from agent import analytics
    original_drafts = analytics.DRAFTS_DIR
    analytics.DRAFTS_DIR = tmp_path
    try:
        tmp_path.mkdir(parents=True, exist_ok=True)
        drafts = [
            {"created_at": "2026-07-09T00:00:00+00:00", "updated_at": "2026-07-09T01:00:00+00:00", "status": "published", "published_at": "2026-07-09T02:00:00+00:00"},
            {"created_at": "2026-07-09T00:00:00+00:00", "updated_at": "2026-07-09T01:00:00+00:00", "status": "draft"},
            {"created_at": "2026-07-09T00:00:00+00:00", "updated_at": "2026-07-09T01:00:00+00:00", "status": "approved"},
        ]
        for i, d in enumerate(drafts):
            tmp_path.joinpath(f"{i}.json").write_text(str(d).replace("'", '"'))
        snapshot = compute_analytics()
        funnel = snapshot.editorial_funnel
        assert funnel["drafts_created"] == 3
        assert funnel["drafts_approved"] == 2
        assert funnel["blogs_published"] == 1
        assert funnel["overall_conversion_rate"] == pytest.approx(33.3, 0.1)
    finally:
        analytics.DRAFTS_DIR = original_drafts


def test_social_metrics_by_platform(tmp_path):
    from agent import analytics
    original_social = analytics.SOCIAL_DIR
    analytics.SOCIAL_DIR = tmp_path
    try:
        tmp_path.mkdir(parents=True, exist_ok=True)
        socials = [
            {"created_at": "2026-07-09T00:00:00+00:00", "platform": "linkedin", "status": "published"},
            {"created_at": "2026-07-09T00:00:00+00:00", "platform": "linkedin", "status": "failed"},
            {"created_at": "2026-07-09T00:00:00+00:00", "platform": "x", "status": "draft"},
        ]
        for i, s in enumerate(socials):
            tmp_path.joinpath(f"{i}.json").write_text(str(s).replace("'", '"'))
        snapshot = compute_analytics()
        linkedin = snapshot.social["by_platform"]["linkedin"]
        assert linkedin["created"] == 2
        assert linkedin["published"] == 1
        assert linkedin["failed"] == 1
        assert snapshot.social["success_rate"] == 50.0
    finally:
        analytics.SOCIAL_DIR = original_social


def test_export_csv(tmp_path):
    from agent import analytics
    original_social = analytics.SOCIAL_DIR
    analytics.SOCIAL_DIR = tmp_path
    try:
        tmp_path.mkdir(parents=True, exist_ok=True)
        tmp_path.joinpath("0.json").write_text('{"created_at": "2026-07-09T00:00:00+00:00", "platform": "linkedin", "status": "published"}')
        snapshot = compute_analytics()
        csv_text = export_csv(snapshot)
        assert "platform,created,approved,scheduled,published,failed" in csv_text
        assert "linkedin,1,0,0,1,0" in csv_text
    finally:
        analytics.SOCIAL_DIR = original_social


def test_export_json(tmp_path):
    from agent import analytics
    original_social = analytics.SOCIAL_DIR
    analytics.SOCIAL_DIR = tmp_path
    try:
        tmp_path.mkdir(parents=True, exist_ok=True)
        snapshot = compute_analytics()
        json_text = export_json(snapshot)
        assert '"generated_at"' in json_text
        assert '"not_connected"' in json_text
    finally:
        analytics.SOCIAL_DIR = original_social


def test_save_analytics(tmp_path):
    from agent import analytics
    original_dir = analytics.ANALYTICS_DIR
    analytics.ANALYTICS_DIR = tmp_path
    try:
        snapshot = AnalyticsSnapshot(
            generated_at="2026-07-09T00:00:00+00:00",
            start_date="2026-07-01T00:00:00+00:00",
            end_date="2026-07-09T00:00:00+00:00",
            platform_filter=None,
        )
        path = save_analytics(snapshot, tmp_path / "test.json")
        assert path.exists()
        assert '"generated_at"' in path.read_text()
    finally:
        analytics.ANALYTICS_DIR = original_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── Regression: /api/analytics 500'd whenever a draft awaited review ────────

def _write_social(dirpath, platform, status, idx=0):
    import json
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / f"{platform}-{status}-{idx}.json").write_text(json.dumps({
        "draft_id": f"{platform}{status}{idx}",
        "platform": platform,
        "status": status,
        "title": "A sufficiently specific title",
        "text": "Body text.",
        "created_at": "2026-07-27T00:00:00+00:00",
        "updated_at": "2026-07-27T00:00:00+00:00",
    }), encoding="utf-8")


@pytest.fixture
def social_dir(tmp_path, monkeypatch):
    from agent import analytics
    monkeypatch.setattr(analytics, "INTEL_DIR", tmp_path / "intel")
    monkeypatch.setattr(analytics, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(analytics, "SOCIAL_DIR", tmp_path / "social")
    return tmp_path / "social"


def test_needs_review_status_does_not_crash_analytics(social_dir):
    """The live defect: `needs_review` is a VALID_STATUS but was never seeded."""
    _write_social(social_dir, "linkedin", "needs_review")

    snapshot = compute_analytics(days=30)

    counts = snapshot.social["by_platform"]["linkedin"]
    assert counts["needs_review"] == 1
    assert counts["created"] == 1


def test_every_valid_status_is_present_in_the_response(social_dir):
    """Response shape must be stable regardless of which statuses occur."""
    from agent.social_drafts import VALID_STATUSES

    _write_social(social_dir, "linkedin", "published")
    counts = compute_analytics(days=30).social["by_platform"]["linkedin"]

    for status in VALID_STATUSES:
        assert status in counts, f"{status} missing from analytics response"
        # Unused statuses must report an explicit zero, not be absent — the
        # dashboard renders these keys directly and a missing key reads as a
        # gap in the data rather than a genuine count of none.
        if status != "published":
            assert counts[status] == 0, f"{status} should be 0 when unused"
    assert counts["published"] == 1
    # Backward compatibility: the original keys must all survive.
    for legacy in ("created", "approved", "scheduled", "published", "failed", "draft"):
        assert legacy in counts


def test_unknown_status_is_counted_not_fatal(social_dir):
    """A legacy or hand-edited status must not take the endpoint down."""
    _write_social(social_dir, "linkedin", "some_future_status")

    counts = compute_analytics(days=30).social["by_platform"]["linkedin"]

    assert counts["some_future_status"] == 1
    assert counts["created"] == 1


def test_all_real_statuses_together_compute_cleanly(social_dir):
    """Mirrors the production mix that was crashing the live dashboard."""
    for i, status in enumerate(
        ["published", "approved", "failed", "draft", "needs_review", "scheduled", "idea"]
    ):
        _write_social(social_dir, "linkedin", status, i)

    social = compute_analytics(days=30).social

    assert social["total_social_drafts"] == 7
    assert social["by_platform"]["linkedin"]["created"] == 7
    assert social["by_platform"]["linkedin"]["needs_review"] == 1
    assert 0 <= social["success_rate"] <= 100
