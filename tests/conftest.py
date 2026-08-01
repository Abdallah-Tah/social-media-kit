"""Shared test fixtures and environment isolation.

Sets SMKIT_TESTING=1 so the notification guard in agent.notify blocks
all outbound Telegram messages during the entire test session.  Individual
tests may still override SMKIT_ENV / SMKIT_NOTIFICATIONS_ENABLED to verify
the production path through a mock.
"""
from __future__ import annotations

import os

import pytest


def pytest_configure(config):
    os.environ.setdefault("SMKIT_TESTING", "1")


@pytest.fixture(autouse=True)
def isolate_linkedin_ledger(tmp_path_factory, monkeypatch):
    """Point the LinkedIn daily-post ledger at a throwaway file.

    ``_publish_linkedin`` consults ``linkedin_policy.allowed()`` before it
    posts, and the policy counts entries in the *live* ledger. Left alone, any
    test that publishes to LinkedIn passes in the morning and fails once the
    real cron lane has used the day's quota.
    """
    try:
        import linkedin_policy
    except ImportError:
        return
    ledger = tmp_path_factory.mktemp("linkedin_ledger") / "linkedin_daily_posts.json"
    monkeypatch.setattr(linkedin_policy, "LEDGER", ledger)
