"""Tests for connection secrets saving and LinkedIn policy in publisher."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))


def _patch_secrets(tmp_path, monkeypatch):
    from agent import connections
    secrets = tmp_path / "secrets.env"
    monkeypatch.setattr(connections, "SECRETS_FILE", secrets)
    return connections, secrets


def test_save_valid_key_writes_file(tmp_path, monkeypatch):
    conn, secrets = _patch_secrets(tmp_path, monkeypatch)
    result = conn.save_platform_secrets({"LINKEDIN_ACCESS_TOKEN": "tok123"})
    assert result["ok"] is True
    assert "LINKEDIN_ACCESS_TOKEN" in result["saved"]
    assert "LINKEDIN_ACCESS_TOKEN=tok123" in secrets.read_text()


def test_save_updates_existing_line(tmp_path, monkeypatch):
    conn, secrets = _patch_secrets(tmp_path, monkeypatch)
    secrets.write_text("# comment\nLINKEDIN_ACCESS_TOKEN=oldtok\nOTHER=keep\n")
    conn.save_platform_secrets({"LINKEDIN_ACCESS_TOKEN": "newtok"})
    content = secrets.read_text()
    assert "LINKEDIN_ACCESS_TOKEN=newtok" in content
    assert "oldtok" not in content
    assert "OTHER=keep" in content
    assert "# comment" in content


def test_save_rejects_unknown_keys(tmp_path, monkeypatch):
    conn, secrets = _patch_secrets(tmp_path, monkeypatch)
    result = conn.save_platform_secrets({"EVIL_KEY": "x", "PATH": "/tmp"})
    assert result["ok"] is False
    assert "EVIL_KEY" in result["rejected"]
    assert not secrets.exists()


def test_save_ignores_empty_values(tmp_path, monkeypatch):
    conn, secrets = _patch_secrets(tmp_path, monkeypatch)
    secrets.write_text("FB_PAGE_TOKEN=real\n")
    result = conn.save_platform_secrets({"FB_PAGE_TOKEN": "  "})
    assert result["ok"] is False
    assert "FB_PAGE_TOKEN=real" in secrets.read_text()


def test_save_sets_process_env(tmp_path, monkeypatch):
    import os
    conn, _ = _patch_secrets(tmp_path, monkeypatch)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    conn.save_platform_secrets({"THREADS_ACCESS_TOKEN": "envtok"})
    assert os.environ.get("THREADS_ACCESS_TOKEN") == "envtok"


def test_linkedin_publisher_surfaces_policy_block(tmp_path):
    from agent.social_publishers import _publish_linkedin
    with patch("linkedin_policy.allowed", return_value=(False, "LinkedIn skipped: daily news limit reached (3/3).")):
        result = _publish_linkedin({"text": "hello"}, dry_run=False)
    assert result["ok"] is False
    assert "daily news limit" in result["error"]


def test_linkedin_publisher_passes_news_kind(tmp_path):
    from agent.social_publishers import _publish_linkedin
    with patch("linkedin_policy.allowed", return_value=(True, "ok")), \
         patch("linkedin_poster.post_text", return_value={"id": "urn:li:share:1"}) as mock_post:
        result = _publish_linkedin({"text": "hello **world**"}, dry_run=False)
    assert result["ok"] is True
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs.get("post_kind") == "news"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
