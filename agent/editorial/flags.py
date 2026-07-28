"""Feature flag and timezone resolution for the editorial layer.

Kept in its own module so anything can ask "is this on?" without importing the
YAML loader, and so the flag has exactly one definition.

Precedence everywhere, matching the FEED_LLM_* convention established in
Phase 0.5:

    environment  >  config/publishing_slots.yaml  >  default

Environment wins so a runaway can be stopped without a commit.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

KIT = Path(__file__).resolve().parents[2]
SLOTS_PATH = KIT / "config" / "publishing_slots.yaml"

# Phase 1 stays off until the approved cadence cutover. This default is the
# safety property the whole phase rests on: partial work cannot change what
# production publishes.
DEFAULT_ENABLED = False
DEFAULT_SHADOW = False

# Slots, budget windows, and display all convert to this zone. Internal
# timestamps stay timezone-aware UTC and are converted only at the boundary.
DEFAULT_TIMEZONE = "America/New_York"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    text = raw.strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


def _raw_slot_settings() -> dict[str, Any]:
    """Read the YAML without validating it.

    Deliberately tolerant: a malformed slots file must not make the kill switch
    unreadable. `load_slots()` is where a bad file is rejected loudly.
    """
    try:
        from agent.config import _read_yaml

        data = _read_yaml(SLOTS_PATH)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — the flag must always resolve
        return {}


def editorial_slots_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Master switch for the Phase 1 publishing slots."""
    env = _env_bool("EDITORIAL_SLOTS_ENABLED")
    if env is not None:
        return env
    data = _raw_slot_settings() if settings is None else settings
    value = data.get("enabled")
    return bool(value) if isinstance(value, bool) else DEFAULT_ENABLED


def editorial_shadow_mode(settings: dict[str, Any] | None = None) -> bool:
    """Run the full decision pipeline but publish nothing.

    Independent of `editorial_slots_enabled`: shadow evaluation is meant to run
    for at least 24 hours while the slots themselves are still off.
    """
    env = _env_bool("EDITORIAL_SHADOW_MODE")
    if env is not None:
        return env
    data = _raw_slot_settings() if settings is None else settings
    value = data.get("shadow_mode")
    return bool(value) if isinstance(value, bool) else DEFAULT_SHADOW


def editorial_timezone(settings: dict[str, Any] | None = None) -> str:
    """The configured editorial zone name.

    Never the host's local zone by default. A budget or schedule window built
    from naive local time silently changes meaning when the host moves or when
    DST shifts, which is exactly the class of defect that made the feed budget
    stop binding for four hours a day.
    """
    env = os.environ.get("EDITORIAL_TIMEZONE")
    if env:
        return env.strip()
    data = _raw_slot_settings() if settings is None else settings
    value = data.get("timezone")
    return str(value).strip() if value else DEFAULT_TIMEZONE


def editorial_zoneinfo(settings: dict[str, Any] | None = None):
    """Resolved tzinfo, falling back to the default zone then UTC.

    Falling back rather than raising is deliberate: a missing tzdata entry must
    degrade scheduling, not crash a publish run. The fallback is logged by the
    caller when it matters.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    name = editorial_timezone(settings)
    for candidate in (name, DEFAULT_TIMEZONE):
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            continue
    import datetime as dt

    return dt.timezone.utc
