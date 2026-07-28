"""Load and validate config/publishing_slots.yaml.

This module holds no editable policy. Thresholds, schedules, and format pools
live in the YAML so they can change without a deploy; everything here is
structure and validation.

Validation is strict and happens at load, not at publish time. A slot that
names a format id which does not exist should fail on a Sunday afternoon when
someone edits the file — not at 08:00 on a Tuesday when the slot fires and
`content_formats.get()` quietly falls back to the registry's first entry.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KIT = Path(__file__).resolve().parents[2]
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from .flags import SLOTS_PATH  # noqa: E402

SUPPORTED_VERSIONS = (1,)

WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# How many distinct shapes a content type needs, given how often it runs. A
# type used once a week can be a single artifact; one used most days needs
# enough variation that a reader cannot predict the shape.
MIN_VARIATION_BY_FREQUENCY = {1: 1, 2: 2}
MAX_REQUIRED_VARIATION = 3


class SlotConfigError(ValueError):
    """Raised for any structural or referential problem in the slots file.

    Carries every problem found, not just the first, so one edit-and-reload
    cycle surfaces the whole list.
    """

    def __init__(self, problems: list[str], path: Path | None = None):
        self.problems = list(problems)
        self.path = path
        location = f" in {path}" if path else ""
        joined = "\n  - ".join(self.problems)
        super().__init__(f"{len(self.problems)} problem(s){location}:\n  - {joined}")


@dataclass(frozen=True)
class ContentType:
    """One publishable shape for a slot: a rotating pool, or a single artifact."""
    name: str
    formats: tuple[str, ...] = ()
    artifact: str | None = None

    @property
    def is_artifact(self) -> bool:
        return self.artifact is not None


@dataclass(frozen=True)
class Slot:
    slot_id: str
    order: int
    publish_at: str
    label: str
    purpose: str = ""
    lookback_hours: int | None = None
    weekly_schedule: dict[str, str] = field(default_factory=dict)
    content_types: dict[str, ContentType] = field(default_factory=dict)
    required_sections: tuple[str, ...] = ()
    required_value_any_of: tuple[str, ...] = ()
    admission: dict[str, Any] = field(default_factory=dict)

    @property
    def hour(self) -> int:
        return int(self.publish_at.split(":")[0])

    @property
    def minute(self) -> int:
        return int(self.publish_at.split(":")[1])

    def content_type_for(self, weekday: str) -> ContentType:
        """Which shape this slot publishes on a given weekday.

        A slot with no weekly_schedule publishes the same type every day.
        """
        key = weekday.strip().lower()
        if key not in WEEKDAYS:
            raise KeyError(f"not a weekday: {weekday!r}")
        if self.weekly_schedule:
            return self.content_types[self.weekly_schedule[key]]
        return next(iter(self.content_types.values()))

    def source_confidence_min(self) -> int:
        return int(self.admission.get("source_confidence_min", 0))

    def editorial_quality_min(self) -> int:
        return int(self.admission.get("editorial_quality_min", 0))


@dataclass(frozen=True)
class SlotConfig:
    version: int
    enabled: bool
    shadow_mode: bool
    timezone: str
    defaults: dict[str, Any]
    slots: dict[str, Slot]
    path: Path | None = None

    def ordered(self) -> list[Slot]:
        return sorted(self.slots.values(), key=lambda s: s.order)

    def slots_for(self, weekday: str) -> list[tuple[Slot, ContentType]]:
        return [(s, s.content_type_for(weekday)) for s in self.ordered()]


# ── validation helpers ──────────────────────────────────────────────────────

def _known_formats() -> tuple[set[str], set[str]]:
    import content_formats as CF

    return set(CF.EDITORIAL_FORMATS), set(CF.EDITORIAL_ARTIFACTS)


def _live_format_ids() -> set[str]:
    import content_formats as CF

    return set(CF.NEWS_FORMATS) | set(CF.TUTORIAL_FORMATS) | set(CF.SOCIAL_SHAPES)


def _validate_content_types(slot_id: str, raw: Any, problems: list[str]) -> dict[str, ContentType]:
    editorial, artifacts = _known_formats()
    live = _live_format_ids()
    out: dict[str, ContentType] = {}

    if not isinstance(raw, dict) or not raw:
        problems.append(f"slot {slot_id!r}: content_types must be a non-empty mapping")
        return out

    for name, spec in raw.items():
        if not isinstance(spec, dict):
            problems.append(f"slot {slot_id!r}: content type {name!r} must be a mapping")
            continue
        formats, artifact = spec.get("formats"), spec.get("artifact")

        if formats is not None and artifact is not None:
            problems.append(
                f"slot {slot_id!r}: content type {name!r} declares both formats and artifact")
            continue
        if formats is None and artifact is None:
            problems.append(
                f"slot {slot_id!r}: content type {name!r} declares neither formats nor artifact")
            continue

        if artifact is not None:
            if artifact not in artifacts:
                problems.append(
                    f"slot {slot_id!r}: unknown artifact {artifact!r} "
                    f"(known: {', '.join(sorted(artifacts))})")
                continue
            out[name] = ContentType(name=name, artifact=str(artifact))
            continue

        if not isinstance(formats, list) or not formats:
            problems.append(
                f"slot {slot_id!r}: content type {name!r} formats must be a non-empty list")
            continue
        for fid in formats:
            if fid in live:
                # The whole dormancy guarantee is that editorial pools never
                # reference a production format.
                problems.append(
                    f"slot {slot_id!r}: format {fid!r} belongs to a live production "
                    f"registry and must not be used by an editorial slot")
            elif fid not in editorial:
                problems.append(
                    f"slot {slot_id!r}: unknown editorial format {fid!r}")
        if len(set(formats)) != len(formats):
            problems.append(f"slot {slot_id!r}: content type {name!r} repeats a format id")
        out[name] = ContentType(name=name, formats=tuple(formats))
    return out


def _validate_schedule(slot_id: str, raw: Any, types: dict[str, ContentType],
                       problems: list[str]) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        problems.append(f"slot {slot_id!r}: weekly_schedule must be a mapping")
        return {}
    schedule = {str(k).strip().lower(): str(v) for k, v in raw.items()}

    missing = [d for d in WEEKDAYS if d not in schedule]
    if missing:
        problems.append(
            f"slot {slot_id!r}: weekly_schedule missing {', '.join(missing)}")
    unknown_days = [d for d in schedule if d not in WEEKDAYS]
    if unknown_days:
        problems.append(f"slot {slot_id!r}: not weekdays: {', '.join(sorted(unknown_days))}")
    for day, type_name in schedule.items():
        if day in WEEKDAYS and type_name not in types:
            problems.append(
                f"slot {slot_id!r}: {day} refers to undefined content type {type_name!r}")
    return schedule


def _validate_variation(slot_id: str, schedule: dict[str, str],
                        types: dict[str, ContentType], problems: list[str]) -> None:
    """Enough shapes that a reader cannot predict the week."""
    for name, ctype in types.items():
        if ctype.is_artifact:
            continue
        if schedule:
            uses = sum(1 for d in WEEKDAYS if schedule.get(d) == name)
        else:
            uses = len(WEEKDAYS)  # no schedule = published every day
        if uses == 0:
            problems.append(
                f"slot {slot_id!r}: content type {name!r} is defined but never scheduled")
            continue
        required = MIN_VARIATION_BY_FREQUENCY.get(uses, MAX_REQUIRED_VARIATION)
        if len(ctype.formats) < required:
            problems.append(
                f"slot {slot_id!r}: content type {name!r} runs {uses}x/week but has "
                f"{len(ctype.formats)} format(s); needs at least {required}")


def _validate_admission(slot_id: str, raw: Any, problems: list[str]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        problems.append(f"slot {slot_id!r}: admission must be a non-empty mapping")
        return {}
    for key in ("source_confidence_min", "editorial_quality_min"):
        if key not in raw:
            problems.append(f"slot {slot_id!r}: admission missing {key}")
            continue
        value = raw[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            problems.append(f"slot {slot_id!r}: admission.{key} must be a number")
        elif not 0 <= value <= 100:
            problems.append(f"slot {slot_id!r}: admission.{key}={value} is outside 0-100")
    return dict(raw)


# ── entry point ─────────────────────────────────────────────────────────────

def load_slots(path: Path | str | None = None) -> SlotConfig:
    """Parse and fully validate the slots file.

    Raises SlotConfigError listing every problem found. Never returns a
    partially-valid config: a slot layer that half-loads is worse than one that
    refuses to start, because the failure surfaces at publish time instead.
    """
    from agent.config import _read_yaml

    from .flags import (
        editorial_shadow_mode, editorial_slots_enabled, editorial_timezone,
    )

    target = Path(path) if path else SLOTS_PATH
    problems: list[str] = []

    if not target.exists():
        raise SlotConfigError([f"slots file not found: {target}"], target)

    data = _read_yaml(target)
    if not isinstance(data, dict) or not data:
        raise SlotConfigError(["file is empty or not a YAML mapping"], target)

    version = data.get("version")
    if version not in SUPPORTED_VERSIONS:
        problems.append(
            f"unsupported version {version!r}; supported: "
            f"{', '.join(map(str, SUPPORTED_VERSIONS))}")

    tz_name = editorial_timezone(data)
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — any resolution failure is a config error
        problems.append(f"unknown timezone {tz_name!r}")

    raw_slots = data.get("slots")
    slots: dict[str, Slot] = {}
    if not isinstance(raw_slots, dict) or not raw_slots:
        problems.append("no slots defined")
        raw_slots = {}

    seen_times: dict[str, str] = {}
    seen_orders: dict[int, str] = {}

    for slot_id, raw in raw_slots.items():
        if not isinstance(raw, dict):
            problems.append(f"slot {slot_id!r}: must be a mapping")
            continue

        publish_at = str(raw.get("publish_at", ""))
        if not _TIME_RE.match(publish_at):
            problems.append(f"slot {slot_id!r}: publish_at {publish_at!r} is not HH:MM")
        elif publish_at in seen_times:
            problems.append(
                f"slot {slot_id!r}: publish_at {publish_at} collides with "
                f"{seen_times[publish_at]!r}")
        else:
            seen_times[publish_at] = slot_id

        order = raw.get("order")
        if not isinstance(order, int) or isinstance(order, bool):
            problems.append(f"slot {slot_id!r}: order must be an integer")
            order = 0
        elif order in seen_orders:
            problems.append(
                f"slot {slot_id!r}: order {order} collides with {seen_orders[order]!r}")
        else:
            seen_orders[order] = slot_id

        types = _validate_content_types(slot_id, raw.get("content_types"), problems)
        schedule = _validate_schedule(slot_id, raw.get("weekly_schedule"), types, problems)
        _validate_variation(slot_id, schedule, types, problems)
        admission = _validate_admission(slot_id, raw.get("admission"), problems)

        slots[slot_id] = Slot(
            slot_id=slot_id,
            order=order,
            publish_at=publish_at,
            label=str(raw.get("label", slot_id)),
            purpose=str(raw.get("purpose", "")).strip(),
            lookback_hours=raw.get("lookback_hours"),
            weekly_schedule=schedule,
            content_types=types,
            required_sections=tuple(raw.get("required_sections") or ()),
            required_value_any_of=tuple(raw.get("required_value_any_of") or ()),
            admission=admission,
        )

    # Publishing order must match clock order, or "order" means nothing.
    ordered = sorted((s for s in slots.values() if _TIME_RE.match(s.publish_at)),
                     key=lambda s: s.order)
    times = [s.publish_at for s in ordered]
    if times != sorted(times):
        problems.append(
            f"slot order does not match clock order: "
            f"{', '.join(f'{s.slot_id}@{s.publish_at}' for s in ordered)}")

    if problems:
        raise SlotConfigError(problems, target)

    return SlotConfig(
        version=int(version),
        # Both already implement env > yaml > default; passing the parsed data
        # avoids re-reading the file we are holding.
        enabled=editorial_slots_enabled(data),
        shadow_mode=editorial_shadow_mode(data),
        timezone=tz_name,
        defaults=dict(data.get("defaults") or {}),
        slots=slots,
        path=target,
    )
