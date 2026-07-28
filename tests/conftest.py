"""Shared test fixtures and environment isolation.

Sets SMKIT_TESTING=1 so the notification guard in agent.notify blocks
all outbound Telegram messages during the entire test session.  Individual
tests may still override SMKIT_ENV / SMKIT_NOTIFICATIONS_ENABLED to verify
the production path through a mock.
"""
from __future__ import annotations

import os


def pytest_configure(config):
    os.environ.setdefault("SMKIT_TESTING", "1")
