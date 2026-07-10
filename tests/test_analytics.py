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
