"""A rejected X post must never be reported as live.

`x_poster.post_tweet` returns a TRUTHY {"error": ..., "status_code": ...} dict
when the API rejects a post. Every caller that used `if result:` reported those
failures as successes. These tests pin the contract at each call site.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

FAILURE = {"error": "403 Forbidden: not permitted", "status_code": 403}
SUCCESS = {"id": "123", "url": "https://x.com/user/status/123", "raw": {}}


def test_toolbox_capture_treats_an_error_dict_as_failure():
    from agent.tools import ToolBox

    assert "failed" in ToolBox._capture("X", lambda: FAILURE)
    assert "success" in ToolBox._capture("X", lambda: SUCCESS)


def test_toolbox_capture_still_accepts_non_dict_truthy_results():
    """Other posters return ids or True — those must stay successes."""
    from agent.tools import ToolBox

    assert "success" in ToolBox._capture("LinkedIn", lambda: "urn:li:share:1")
    assert "success" in ToolBox._capture("Facebook", lambda: True)
    assert "failed" in ToolBox._capture("Facebook", lambda: None)


def test_publish_all_marks_a_rejected_tweet_failed():
    from publish_all import x_posted_ok

    assert x_posted_ok(SUCCESS) is True
    assert x_posted_ok(FAILURE) is False
    assert x_posted_ok(None) is False
    assert x_posted_ok({"id": ""}) is False


def test_social_publishers_adapter_reports_the_error(monkeypatch):
    from agent.social_publishers import publish

    monkeypatch.setattr("x_poster.post_tweet", lambda _text: FAILURE)
    result = publish("x", {"text": "A substantive social post with enough words to pass."},
                     dry_run=False)
    assert result["ok"] is False
    assert "403" in result["error"]


def test_post_tweet_documents_the_truthy_failure_contract():
    """The docstring is the only warning a future caller gets."""
    import x_poster

    doc = (x_poster.post_tweet.__doc__ or "").lower()
    assert "truthy" in doc and "id" in doc


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
