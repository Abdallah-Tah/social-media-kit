"""Deterministic topic-saturation prevention (Phase 1, Stage 3).

Source confidence asks whether a candidate is well evidenced. Saturation asks a
different question: has SMKit already said this? A perfectly evidenced story can
still be the fifth OpenAI post this week.

Design commitments:

  * There is no second topic store. History is derived from the append-only
    ContentDecision log and confirmed publication history. The on-disk index is
    a cache carrying a fingerprint of its inputs; on mismatch it is discarded
    and rebuilt, and deleting it loses nothing.

  * Rules are explicit and individually reported. A single opaque saturation
    score would tell an editor that "saturation = 0.62" instead of which rule
    fired, on what counts, against which threshold.

  * A material development prevents rejection based SOLELY on entity or theme
    recency. It never bypasses exact-topic duplication and never publishes
    anything — every later gate still applies.

  * Only successful publications count. Rejected, shadow, simulated, failed,
    and draft decisions are tallied separately for diagnostics so the numbers
    stay visible without inflating saturation.

Purity: no LLM, no network, no writes to any production history.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .models import DEVELOPMENT_TYPES, Candidate, digest, normalize_title

KIT = Path(__file__).resolve().parents[2]
CONFIG_PATH = KIT / "config" / "saturation.yaml"
INDEX_PATH = KIT / "content" / "feed" / ".saturation_index.json"

SUPPORTED_VERSIONS = (1,)
RESULT_VERSION = 1
INDEX_VERSION = 1

STATUS_CLEAR = "clear"
STATUS_WARNING = "warning"
STATUS_REJECT = "reject"

THEME_UNKNOWN = "theme_unknown"

RULE_IDS = ("R1", "R2", "R3", "R4", "R5", "R6", "R7")

WARN_THEME_UNKNOWN = "theme_unknown"
WARN_LEGACY_RECORDS = "legacy_records_without_topic_id"
WARN_NO_HISTORY = "no_publication_history"
WARN_SMALL_SAMPLE = "sample_below_minimum_for_share_rules"


class SaturationConfigError(ValueError):
    """Reports every problem in config/saturation.yaml at once."""

    def __init__(self, problems: list[str], path: Path | None = None):
        self.problems = list(problems)
        self.path = path
        joined = "\n  - ".join(self.problems)
        super().__init__(
            f"{len(self.problems)} problem(s)"
            f"{f' in {path}' if path else ''}:\n  - {joined}")


# ── Configuration ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SaturationConfig:
    version: int
    timezone: str
    rolling_days: int
    recent_items: int
    rules: dict[str, dict[str, Any]]
    material_types: frozenset[str]
    theme_map: dict[str, str]
    history: dict[str, Any]
    path: Path | None = None

    def rule(self, key: str) -> dict[str, Any]:
        return self.rules.get(key, {})

    def enabled(self, key: str) -> bool:
        return bool(self.rules.get(key, {}).get("enabled"))


_RULE_KEYS = {
    "R1": "R1_exact_topic", "R2": "R2_same_day_reuse", "R3": "R3_entity_share",
    "R4": "R4_entity_development", "R5": "R5_theme_share",
    "R6": "R6_artifact_repetition", "R7": "R7_evidence_update",
}


def _check_share(value: Any, label: str, problems: list[str]) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        problems.append(f"{label} must be a number")
    elif not 0 < value < 1:
        # 1.0 can never be exceeded, which disables the rule while appearing to
        # configure it. 0 rejects everything.
        problems.append(
            f"{label}={value} must be strictly between 0 and 1; "
            f"1.0 silently disables the rule and 0 rejects everything")


def _check_positive_int(value: Any, label: str, problems: list[str],
                        allow_zero: bool = False) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        problems.append(f"{label} must be an integer")
    elif value < 0 or (value == 0 and not allow_zero):
        problems.append(f"{label}={value} must be positive")


def load_saturation_config(path: Path | str | None = None,
                           slot_timezone: str | None = None) -> SaturationConfig:
    """Parse and fully validate. Fails closed; never partially loads."""
    from agent.config import _read_yaml

    from .flags import editorial_timezone

    target = Path(path) if path else CONFIG_PATH
    problems: list[str] = []

    if not target.exists():
        raise SaturationConfigError([f"config file not found: {target}"], target)
    data = _read_yaml(target)
    if not isinstance(data, dict) or not data:
        raise SaturationConfigError(["file is empty or not a YAML mapping"], target)

    if data.get("version") not in SUPPORTED_VERSIONS:
        problems.append(f"unsupported version {data.get('version')!r}")

    # Inheriting the slot timezone keeps editorial days from disagreeing.
    tz_name = data.get("timezone") or slot_timezone or editorial_timezone()
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — any failure is a config error
        problems.append(f"unknown timezone {tz_name!r}")

    windows = data.get("windows") or {}
    if not isinstance(windows, dict):
        problems.append("windows must be a mapping")
        windows = {}
    _check_positive_int(windows.get("rolling_days"), "windows.rolling_days", problems)
    _check_positive_int(windows.get("recent_items"), "windows.recent_items", problems)

    raw_rules = data.get("rules") or {}
    if not isinstance(raw_rules, dict):
        problems.append("rules must be a mapping")
        raw_rules = {}
    unknown = sorted(set(raw_rules) - set(_RULE_KEYS.values()))
    if unknown:
        problems.append(f"unknown rule(s): {', '.join(unknown)}")
    missing = sorted(set(_RULE_KEYS.values()) - set(raw_rules))
    if missing:
        problems.append(f"missing rule(s): {', '.join(missing)}")

    rules = {k: dict(v) for k, v in raw_rules.items() if isinstance(v, dict)}

    r1 = rules.get("R1_exact_topic", {})
    if r1.get("enabled") is not True:
        problems.append(
            "rules.R1_exact_topic.enabled must be true; without exact-topic "
            "duplication the engine permits republishing one development forever")
    _check_positive_int(r1.get("cooldown_days"), "R1_exact_topic.cooldown_days", problems)

    r3 = rules.get("R3_entity_share", {})
    if r3.get("enabled"):
        _check_share(r3.get("last_12_ceiling"), "R3_entity_share.last_12_ceiling", problems)
        _check_share(r3.get("rolling_14d_ceiling"),
                     "R3_entity_share.rolling_14d_ceiling", problems)
        _check_positive_int(r3.get("min_items_before_applying"),
                            "R3_entity_share.min_items_before_applying", problems,
                            allow_zero=True)

    r4 = rules.get("R4_entity_development", {})
    if r4.get("enabled"):
        _check_positive_int(r4.get("count_ceiling_14d"),
                            "R4_entity_development.count_ceiling_14d", problems)
        _check_share(r4.get("share_ceiling_last_12"),
                     "R4_entity_development.share_ceiling_last_12", problems)

    r5 = rules.get("R5_theme_share", {})
    if r5.get("enabled"):
        _check_share(r5.get("ceiling_14d"), "R5_theme_share.ceiling_14d", problems)
        _check_positive_int(r5.get("min_items_before_applying"),
                            "R5_theme_share.min_items_before_applying", problems,
                            allow_zero=True)

    r6 = rules.get("R6_artifact_repetition", {})
    if r6.get("enabled"):
        _check_positive_int(r6.get("window_days"),
                            "R6_artifact_repetition.window_days", problems)
        _check_positive_int(r6.get("max_artifacts_per_entity"),
                            "R6_artifact_repetition.max_artifacts_per_entity", problems)

    r2 = rules.get("R2_same_day_reuse", {})
    if r2.get("enabled"):
        if not r2.get("require_all_of"):
            problems.append(
                "R2_same_day_reuse.require_all_of must list at least one "
                "condition, or every same-day continuation passes unconditionally")
        try:
            from .slots import load_slots

            known_slots = set(load_slots().slots)
        except Exception:  # noqa: BLE001 — slot config validated on its own
            known_slots = set()
        if known_slots:
            bad = sorted(set(r2.get("allow_continuation_slots") or ()) - known_slots)
            if bad:
                problems.append(
                    f"R2_same_day_reuse.allow_continuation_slots: unknown slot(s): "
                    f"{', '.join(bad)}")

    material = data.get("material_development_types") or []
    if not isinstance(material, list):
        problems.append("material_development_types must be a list")
        material = []
    bad_types = sorted(set(material) - set(DEVELOPMENT_TYPES))
    if bad_types:
        problems.append(
            f"material_development_types: unknown development type(s): "
            f"{', '.join(bad_types)}")
    if set(material) >= set(DEVELOPMENT_TYPES):
        problems.append(
            "material_development_types covers every development type, which "
            "exempts every candidate and disables saturation entirely")

    theme_map = data.get("theme_map") or {}
    if not isinstance(theme_map, dict):
        problems.append("theme_map must be a mapping")
        theme_map = {}

    history = data.get("history") or {}
    if not isinstance(history, dict):
        problems.append("history must be a mapping")
        history = {}
    if not history.get("deduplication_keys"):
        problems.append(
            "history.deduplication_keys must list at least one key, or a retried "
            "publication is counted twice")

    if not any(r.get("enabled") for r in rules.values()):
        problems.append("every rule is disabled; saturation would never reject anything")

    if problems:
        raise SaturationConfigError(problems, target)

    return SaturationConfig(
        version=int(data["version"]),
        timezone=str(tz_name),
        rolling_days=int(windows["rolling_days"]),
        recent_items=int(windows["recent_items"]),
        rules=rules,
        material_types=frozenset(material),
        theme_map={str(k).lower(): str(v) for k, v in theme_map.items()},
        history=history,
        path=target,
    )


# ── Publication history ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class PublicationRecord:
    """One confirmed successful publication, as saturation sees it."""
    publication_id: str
    published_at: dt.datetime
    editorial_day: str
    canonical_topic_id: str = ""
    entity: str = ""
    development_type: str = ""
    artifact_type: str = ""
    theme: str = THEME_UNKNOWN
    slot: str = ""
    title: str = ""
    legacy: bool = False
    # Stage 3.5 contract fields. `identity_*` are carried for observability and
    # deliberately NOT acted on: every entity is still treated as equally
    # certain. Acting on confidence is an editorial choice to make against a
    # measured distribution from replay, not to guess at now.
    source_fingerprint: str = ""
    primary_source_url: str = ""
    corroborating_domains: tuple[str, ...] = ()
    identity_source: str = ""
    identity_confidence: float | None = None
    schema_version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "publication_id": self.publication_id,
            "published_at": self.published_at.isoformat(),
            "editorial_day": self.editorial_day,
            "canonical_topic_id": self.canonical_topic_id,
            "entity": self.entity,
            "development_type": self.development_type,
            "artifact_type": self.artifact_type,
            "theme": self.theme,
            "slot": self.slot,
            "title": self.title,
            "legacy": self.legacy,
            "source_fingerprint": self.source_fingerprint,
            "primary_source_url": self.primary_source_url,
            "corroborating_domains": list(self.corroborating_domains),
            "identity_source": self.identity_source,
            "identity_confidence": self.identity_confidence,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PublicationRecord":
        stamp = dt.datetime.fromisoformat(data["published_at"])
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        return cls(
            publication_id=data["publication_id"],
            published_at=stamp.astimezone(dt.timezone.utc),
            editorial_day=data["editorial_day"],
            canonical_topic_id=data.get("canonical_topic_id", ""),
            entity=data.get("entity", ""),
            development_type=data.get("development_type", ""),
            artifact_type=data.get("artifact_type", ""),
            theme=data.get("theme", THEME_UNKNOWN),
            slot=data.get("slot", ""),
            title=data.get("title", ""),
            legacy=bool(data.get("legacy", False)),
            source_fingerprint=data.get("source_fingerprint", ""),
            primary_source_url=data.get("primary_source_url", ""),
            corroborating_domains=tuple(data.get("corroborating_domains") or ()),
            identity_source=data.get("identity_source", ""),
            identity_confidence=data.get("identity_confidence"),
            schema_version=int(data.get("schema_version") or 0),
        )


@dataclass(frozen=True)
class HistoryView:
    records: tuple[PublicationRecord, ...] = ()
    fingerprint: str = ""
    diagnostics: dict[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def recent(self, n: int) -> tuple[PublicationRecord, ...]:
        return self.records[-n:] if n else ()

    def within(self, now: dt.datetime, days: int) -> tuple[PublicationRecord, ...]:
        cutoff = now - dt.timedelta(days=days)
        return tuple(r for r in self.records if r.published_at >= cutoff)


def _editorial_day(stamp: dt.datetime, tz_name: str) -> str:
    """Calendar day in the editorial zone, not UTC.

    A post at 02:00 UTC belongs to the previous New York editorial day, which is
    the whole reason this is not `stamp.date()`.
    """
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — validated at load; degrade to UTC
        zone = dt.timezone.utc
    return stamp.astimezone(zone).strftime("%Y-%m-%d")


def _parse(raw: Any) -> dt.datetime | None:
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def build_history(rows: Iterable[dict[str, Any]],
                  config: SaturationConfig) -> HistoryView:
    """Turn raw decision rows into confirmed publications.

    Counted only when the stage, decision, mode, and status all say the post
    really went out. Everything else is tallied in `diagnostics` so the volume
    stays visible without inflating saturation.
    """
    hist = config.history
    counted_stages = set(hist.get("counted_stages") or ("publish",))
    counted_decisions = set(hist.get("counted_decisions") or ("accepted",))
    excluded_modes = {str(m).lower() for m in (hist.get("excluded_modes") or ())}
    excluded_statuses = {str(s).lower() for s in (hist.get("excluded_statuses") or ())}
    dedupe_keys = list(hist.get("deduplication_keys") or ("slug",))

    diagnostics: Counter = Counter()
    warnings: list[str] = []
    seen: dict[str, PublicationRecord] = {}
    legacy_seen = False

    for row in rows:
        if not isinstance(row, dict):
            diagnostics["malformed"] += 1
            continue
        meta = row.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}

        stage = str(row.get("stage") or "")
        decision = str(row.get("decision") or "")
        mode = str(meta.get("mode") or "").lower()
        status = str(meta.get("status") or "").lower()

        if mode in excluded_modes:
            diagnostics[f"excluded_mode_{mode}"] += 1
            continue
        if status in excluded_statuses:
            diagnostics[f"excluded_status_{status}"] += 1
            continue
        if stage not in counted_stages:
            diagnostics["not_publish_stage"] += 1
            continue
        if decision not in counted_decisions:
            diagnostics["rejected_decision"] += 1
            continue
        if row.get("reason_code") == "publish_failed":
            diagnostics["publish_failed"] += 1
            continue

        stamp = _parse(meta.get("published_at") or row.get("ts"))
        if stamp is None:
            diagnostics["unparseable_timestamp"] += 1
            continue

        identity = ""
        for key in dedupe_keys:
            value = meta.get(key) or row.get(key)
            if value:
                identity = f"{key}:{value}"
                break
        if not identity:
            # No stable key: fall back to topic + editorial day, which still
            # collapses a retry of the same post on the same day.
            identity = "fallback:" + digest(
                str(meta.get("canonical_topic_id") or row.get("title") or ""),
                _editorial_day(stamp, config.timezone))

        topic = str(meta.get("canonical_topic_id") or "")
        entity = str(meta.get("entity") or meta.get("subject_org") or "")
        development = str(meta.get("development_type") or "")
        if not topic or not entity or not development:
            legacy_seen = True
        if topic and (not entity or not development):
            # Recover what the topic id already encodes rather than dropping it.
            parts = topic.split(":")
            if len(parts) == 3:
                entity = entity or parts[0]
                development = development or parts[1]

        # Stored values win. `theme` and `editorial_day` are frozen at
        # publication by the Stage 3.5 contract precisely so that editing
        # theme_map or the editorial timezone cannot retroactively rewrite what
        # a past publication was. Read-time derivation is the legacy fallback.
        record = PublicationRecord(
            publication_id=identity,
            published_at=stamp,
            editorial_day=(str(meta.get("editorial_day") or "")
                           or _editorial_day(stamp, config.timezone)),
            canonical_topic_id=topic,
            entity=entity.lower(),
            development_type=development,
            artifact_type=str(meta.get("artifact_type") or ""),
            theme=str(meta.get("theme") or "") or resolve_theme(entity, config),
            slot=str(meta.get("slot") or ""),
            title=str(row.get("title") or ""),
            legacy=not (topic and entity and development),
            source_fingerprint=str(meta.get("source_fingerprint") or ""),
            primary_source_url=str(meta.get("primary_source_url") or ""),
            corroborating_domains=tuple(meta.get("corroborating_domains") or ()),
            identity_source=str(meta.get("identity_source") or ""),
            identity_confidence=meta.get("identity_confidence"),
            schema_version=int(meta.get("schema_version") or 0),
        )
        if identity in seen:
            diagnostics["duplicate_publication_record"] += 1
            continue
        seen[identity] = record

    records = tuple(sorted(seen.values(), key=lambda r: (r.published_at,
                                                         r.publication_id)))
    if legacy_seen:
        warnings.append(WARN_LEGACY_RECORDS)
    if not records:
        warnings.append(WARN_NO_HISTORY)

    fingerprint = digest(
        str(len(records)),
        records[-1].published_at.isoformat() if records else "",
        records[-1].publication_id if records else "",
        length=24,
    )
    return HistoryView(records, fingerprint, dict(diagnostics), tuple(warnings))


def load_history(config: SaturationConfig,
                 rows: Iterable[dict[str, Any]] | None = None) -> HistoryView:
    """Read the append-only decision log. Never writes."""
    if rows is None:
        from agent.content_decisions import read

        rows = read()
    return build_history(rows, config)


def resolve_theme(entity: str, config: SaturationConfig) -> str:
    """Only an explicit mapping is trusted; never inferred from title text."""
    return config.theme_map.get((entity or "").lower(), THEME_UNKNOWN)


# ── Rebuildable index (cache only) ──────────────────────────────────────────

def save_index(history: HistoryView, path: Path | None = None) -> Path:
    """Persist the derived view. Purely a cache — losing it loses nothing."""
    target = Path(path) if path else INDEX_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "index_version": INDEX_VERSION,
        "source_fingerprint": history.fingerprint,
        "records": [r.to_dict() for r in history.records],
        "diagnostics": history.diagnostics,
    }, indent=2), encoding="utf-8")
    return target


def load_index(expected_fingerprint: str,
               path: Path | None = None) -> HistoryView | None:
    """Return the cache only when it still matches its inputs.

    Any mismatch, corruption, or version change discards it. The cache can never
    drift from the decision records because a stale one is never used.
    """
    target = Path(path) if path else INDEX_PATH
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("index_version") != INDEX_VERSION:
        return None
    if data.get("source_fingerprint") != expected_fingerprint:
        return None
    try:
        records = tuple(PublicationRecord.from_dict(r) for r in data.get("records", []))
    except (KeyError, TypeError, ValueError):
        return None
    return HistoryView(records, data["source_fingerprint"],
                       dict(data.get("diagnostics") or {}))


# ── Result model ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    status: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "status": self.status,
                "reason": self.reason, **self.detail}


@dataclass(frozen=True)
class MaterialException:
    applied: bool = False
    type: str = ""
    reason: str = ""
    evidence_references: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"applied": self.applied, "type": self.type, "reason": self.reason,
                "evidence_references": list(self.evidence_references)}


@dataclass(frozen=True)
class SaturationResult:
    status: str
    rules: tuple[RuleOutcome, ...] = ()
    exact_topic_count: int = 0
    entity_count_14d: int = 0
    entity_count_last_12: int = 0
    development_type_count_14d: int = 0
    theme_count_14d: int = 0
    material_exception: MaterialException = field(default_factory=MaterialException)
    history_fingerprint: str = ""
    warnings: tuple[str, ...] = ()
    observability: dict[str, Any] = field(default_factory=dict)
    version: int = RESULT_VERSION

    @property
    def rejected(self) -> bool:
        return self.status == STATUS_REJECT

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "rules": [r.to_dict() for r in self.rules],
            "exact_topic_count": self.exact_topic_count,
            "entity_count_14d": self.entity_count_14d,
            "entity_count_last_12": self.entity_count_last_12,
            "development_type_count_14d": self.development_type_count_14d,
            "theme_count_14d": self.theme_count_14d,
            "material_exception": self.material_exception.to_dict(),
            "history_fingerprint": self.history_fingerprint,
            "warnings": list(self.warnings),
            "observability": dict(self.observability),
            "version": self.version,
        }


# ── Evaluation ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContinuationClaim:
    """What a slot asserts when it wants a same-day follow-up (R2)."""
    links_to_earlier_item: bool = False
    materially_distinct_objective: bool = False
    new_evidence: bool = False

    def satisfies(self, required: Sequence[str]) -> bool:
        return all(bool(getattr(self, name, False)) for name in required)


def evaluate_saturation(candidate: Candidate, *,
                        history: HistoryView,
                        config: SaturationConfig,
                        now: dt.datetime,
                        slot: str = "",
                        evidence_update_types: Sequence[str] = (),
                        evidence_references: Sequence[str] = (),
                        continuation: ContinuationClaim | None = None,
                        observability: dict[str, Any] | None = None,
                        ) -> SaturationResult:
    """Apply R1-R7 to one candidate against confirmed publication history."""
    now = now.astimezone(dt.timezone.utc)
    warnings: list[str] = list(history.warnings)

    entity = (candidate.subject_org or "").lower()
    development = candidate.development_type
    topic = candidate.canonical_topic_id
    artifact = candidate.artifact_type
    theme = (candidate.metadata or {}).get("theme") or resolve_theme(entity, config)
    if theme == THEME_UNKNOWN:
        warnings.append(WARN_THEME_UNKNOWN)

    today = _editorial_day(now, config.timezone)
    rolling = history.within(now, config.rolling_days)
    recent = history.recent(config.recent_items)

    exact_topic_records = [r for r in rolling if topic and r.canonical_topic_id == topic]
    entity_14d = [r for r in rolling if entity and r.entity == entity]
    entity_recent = [r for r in recent if entity and r.entity == entity]
    dev_14d = [r for r in rolling if development and r.development_type == development]
    entity_dev_14d = [r for r in entity_14d if r.development_type == development]
    entity_dev_recent = [r for r in entity_recent if r.development_type == development]
    theme_14d = ([r for r in rolling if r.theme == theme]
                 if theme != THEME_UNKNOWN else [])

    # ── Material development / evidence exception ──
    allowed_evidence = set(config.rule("R7_evidence_update").get("evidence_types") or ())
    supplied_evidence = [e for e in evidence_update_types if e in allowed_evidence]
    material = MaterialException()
    if config.enabled("R7_evidence_update") and supplied_evidence:
        material = MaterialException(
            True, supplied_evidence[0],
            f"evidence update: {', '.join(sorted(supplied_evidence))}",
            tuple(evidence_references))
    elif development in config.material_types:
        material = MaterialException(
            True, development,
            f"{development} is a material development type",
            tuple(evidence_references))

    outcomes: list[RuleOutcome] = []

    # ── R1: exact-topic duplicate. Material exceptions never bypass this. ──
    cooldown = int(config.rule("R1_exact_topic").get("cooldown_days", 14))
    within_cooldown = [r for r in history.within(now, cooldown)
                       if topic and r.canonical_topic_id == topic]
    if within_cooldown and not supplied_evidence:
        outcomes.append(RuleOutcome(
            "R1", STATUS_REJECT, "exact_topic_republished_within_cooldown",
            {"canonical_topic_id": topic, "recent_count": len(within_cooldown),
             "cooldown_days": cooldown, "window": f"last_{cooldown}d",
             "last_published_at": within_cooldown[-1].published_at.isoformat()}))
    elif within_cooldown and supplied_evidence:
        outcomes.append(RuleOutcome(
            "R1", STATUS_WARNING, "exact_topic_reconsidered_on_new_evidence",
            {"canonical_topic_id": topic, "recent_count": len(within_cooldown),
             "evidence": sorted(supplied_evidence)}))
    else:
        outcomes.append(RuleOutcome("R1", STATUS_CLEAR, "no_exact_topic_in_cooldown",
                                    {"canonical_topic_id": topic}))

    # ── R2: same editorial day reuse of one topic ──
    if config.enabled("R2_same_day_reuse"):
        same_day = [r for r in exact_topic_records if r.editorial_day == today]
        if same_day:
            rule = config.rule("R2_same_day_reuse")
            allowed_slots = set(rule.get("allow_continuation_slots") or ())
            required = list(rule.get("require_all_of") or ())
            claim = continuation or ContinuationClaim()
            if slot in allowed_slots and (claim.satisfies(required) or claim.new_evidence):
                outcomes.append(RuleOutcome(
                    "R2", STATUS_WARNING, "same_day_continuation_permitted",
                    {"slot": slot, "editorial_day": today,
                     "earlier_count": len(same_day),
                     "conditions_met": required}))
            else:
                outcomes.append(RuleOutcome(
                    "R2", STATUS_REJECT, "same_day_topic_reuse",
                    {"slot": slot, "editorial_day": today,
                     "earlier_count": len(same_day),
                     "allow_continuation_slots": sorted(allowed_slots),
                     "required_conditions": required}))
        else:
            outcomes.append(RuleOutcome("R2", STATUS_CLEAR, "no_same_day_reuse",
                                        {"editorial_day": today}))

    # ── R3: entity share ──
    if config.enabled("R3_entity_share") and entity:
        rule = config.rule("R3_entity_share")
        minimum = int(rule.get("min_items_before_applying", 0))
        outcome = _share_rule(
            "R3", "entity_share_exceeded", entity,
            len(entity_recent), len(recent), float(rule["last_12_ceiling"]),
            f"last_{config.recent_items}", minimum, material)
        if outcome is None:
            outcome = _share_rule(
                "R3", "entity_share_exceeded", entity,
                len(entity_14d), len(rolling), float(rule["rolling_14d_ceiling"]),
                f"last_{config.rolling_days}d", minimum, material)
        outcomes.append(outcome or RuleOutcome(
            "R3", STATUS_CLEAR, "entity_within_share",
            {"entity": entity, "recent_count": len(entity_recent),
             "recent_total": len(recent)}))
        if len(recent) < minimum and WARN_SMALL_SAMPLE not in warnings:
            warnings.append(WARN_SMALL_SAMPLE)

    # ── R4: entity + development type ──
    if config.enabled("R4_entity_development") and entity and development:
        rule = config.rule("R4_entity_development")
        ceiling = int(rule["count_ceiling_14d"])
        share_ceiling = float(rule["share_ceiling_last_12"])
        share = len(entity_dev_recent) / len(recent) if recent else 0.0
        if len(entity_dev_14d) >= ceiling and not material.applied:
            outcomes.append(RuleOutcome(
                "R4", STATUS_REJECT, "entity_development_count_exceeded",
                {"entity": entity, "development_type": development,
                 "recent_count": len(entity_dev_14d), "threshold": ceiling,
                 "window": f"last_{config.rolling_days}d"}))
        elif share > share_ceiling and not material.applied:
            outcomes.append(RuleOutcome(
                "R4", STATUS_REJECT, "entity_development_share_exceeded",
                {"entity": entity, "development_type": development,
                 "recent_count": len(entity_dev_recent), "recent_total": len(recent),
                 "share": round(share, 4), "threshold": share_ceiling,
                 "window": f"last_{config.recent_items}"}))
        elif len(entity_dev_14d) >= ceiling or share > share_ceiling:
            outcomes.append(RuleOutcome(
                "R4", STATUS_WARNING, "entity_development_saturated_but_material",
                {"entity": entity, "development_type": development,
                 "recent_count": len(entity_dev_14d),
                 "material_exception": material.type}))
        else:
            outcomes.append(RuleOutcome(
                "R4", STATUS_CLEAR, "entity_development_within_limits",
                {"entity": entity, "development_type": development,
                 "recent_count": len(entity_dev_14d)}))

    # ── R5: theme share. Skipped entirely when the theme is unknown. ──
    if config.enabled("R5_theme_share"):
        if theme == THEME_UNKNOWN:
            outcomes.append(RuleOutcome(
                "R5", STATUS_CLEAR, "theme_unknown_rule_skipped",
                {"theme": THEME_UNKNOWN}))
        else:
            rule = config.rule("R5_theme_share")
            outcome = _share_rule(
                "R5", "theme_share_exceeded", theme, len(theme_14d), len(rolling),
                float(rule["ceiling_14d"]), f"last_{config.rolling_days}d",
                int(rule.get("min_items_before_applying", 0)), material,
                key="theme")
            outcomes.append(outcome or RuleOutcome(
                "R5", STATUS_CLEAR, "theme_within_share",
                {"theme": theme, "recent_count": len(theme_14d),
                 "recent_total": len(rolling)}))

    # ── R6: same entity re-run through different formats ──
    if config.enabled("R6_artifact_repetition") and entity:
        rule = config.rule("R6_artifact_repetition")
        window = int(rule["window_days"])
        maximum = int(rule["max_artifacts_per_entity"])
        in_window = [r for r in history.within(now, window) if r.entity == entity]
        artifacts = {r.artifact_type for r in in_window if r.artifact_type}
        if len(in_window) >= maximum and not material.applied:
            outcomes.append(RuleOutcome(
                "R6", STATUS_REJECT, "artifact_repetition_for_entity",
                {"entity": entity, "recent_count": len(in_window),
                 "threshold": maximum, "window": f"last_{window}d",
                 "artifact_types": sorted(artifacts),
                 "candidate_artifact_type": artifact,
                 "note": "changing format does not by itself add informational value"}))
        elif len(in_window) >= maximum:
            outcomes.append(RuleOutcome(
                "R6", STATUS_WARNING, "artifact_repetition_but_material",
                {"entity": entity, "recent_count": len(in_window),
                 "material_exception": material.type}))
        else:
            outcomes.append(RuleOutcome(
                "R6", STATUS_CLEAR, "artifact_repetition_within_limits",
                {"entity": entity, "recent_count": len(in_window)}))

    # ── R7: reported as its own outcome so the exception is auditable ──
    if config.enabled("R7_evidence_update"):
        if supplied_evidence:
            outcomes.append(RuleOutcome(
                "R7", STATUS_WARNING, "evidence_update_exception_applied",
                {"evidence_types": sorted(supplied_evidence),
                 "evidence_references": list(evidence_references)}))
        else:
            outcomes.append(RuleOutcome("R7", STATUS_CLEAR, "no_evidence_update", {}))

    if any(o.status == STATUS_REJECT for o in outcomes):
        status = STATUS_REJECT
    elif any(o.status == STATUS_WARNING for o in outcomes):
        status = STATUS_WARNING
    else:
        status = STATUS_CLEAR

    seen: set[str] = set()
    ordered_warnings = tuple(w for w in warnings if not (w in seen or seen.add(w)))

    return SaturationResult(
        status=status,
        rules=tuple(outcomes),
        exact_topic_count=len(exact_topic_records),
        entity_count_14d=len(entity_14d),
        entity_count_last_12=len(entity_recent),
        development_type_count_14d=len(dev_14d),
        theme_count_14d=len(theme_14d),
        material_exception=material,
        history_fingerprint=history.fingerprint,
        warnings=ordered_warnings,
        observability=_observability(
            candidate, entity, theme, development, artifact, slot, outcomes,
            material, history, observability),
    )


def _share_rule(rule_id: str, reason: str, subject: str, count: int, total: int,
                ceiling: float, window: str, minimum: int,
                material: MaterialException, key: str = "entity",
                ) -> RuleOutcome | None:
    """Shared share-ceiling check. Returns None when the rule does not fire."""
    if total < max(minimum, 1):
        return None
    share = count / total
    if share <= ceiling:
        return None
    detail = {key: subject, "recent_count": count, "recent_total": total,
              "share": round(share, 4), "threshold": ceiling, "window": window}
    if material.applied:
        # A material development prevents rejection on recency ALONE. The
        # saturation is still real and still reported.
        return RuleOutcome(rule_id, STATUS_WARNING, f"{reason}_but_material",
                           {**detail, "material_exception": material.type})
    return RuleOutcome(rule_id, STATUS_REJECT, reason, detail)


def _observability(candidate: Candidate, entity: str, theme: str, development: str,
                   artifact: str, slot: str, outcomes: Sequence[RuleOutcome],
                   material: MaterialException, history: HistoryView,
                   extra: dict[str, Any] | None) -> dict[str, Any]:
    """Fields replay and shadow runs need to derive the agreed metrics later.

    Deliberately raw counts rather than computed rates: the rate is a property
    of a run, not of one candidate, and computing it here would produce a
    denominator of 1.
    """
    return {
        "canonical_topic_id": candidate.canonical_topic_id,
        "entity": entity,
        "theme": theme,
        "development_type": development,
        "artifact_type": artifact,
        "slot": slot,
        "rule_statuses": {o.rule_id: o.status for o in outcomes},
        "rejecting_rules": [o.rule_id for o in outcomes if o.status == STATUS_REJECT],
        "material_exception_applied": material.applied,
        "material_exception_type": material.type,
        "exact_topic_repeat": any(o.rule_id == "R1" and o.status != STATUS_CLEAR
                                  for o in outcomes),
        "history_size": len(history.records),
        "history_diagnostics": dict(history.diagnostics),
        # Stage 2.6 carry-through, so relationship_unknown_rate and its effect
        # on source confidence stay derivable from replay records.
        **(extra or {}),
    }


def relationship_observability(candidate: Candidate,
                               relationships: Sequence[Any] = (),
                               source_confidence: Any = None) -> dict[str, Any]:
    """Per-candidate counters for the Stage 2.6 limitation we agreed to measure.

    Raw counts only. Rates are computed over a run, not over one candidate.
    """
    sources = list(candidate.sources)
    excerpt_lengths = [len(s.excerpt or "") for s in sources]
    buckets = Counter()
    for length in excerpt_lengths:
        if length == 0:
            buckets["0"] += 1
        elif length < 100:
            buckets["1-99"] += 1
        elif length < 300:
            buckets["100-299"] += 1
        elif length < 1000:
            buckets["300-999"] += 1
        else:
            buckets["1000+"] += 1

    by_relationship = Counter(getattr(r, "relationship", "") for r in relationships)
    unknown_ids = {getattr(r, "source_id", "") for r in relationships
                   if getattr(r, "relationship", "") == "relationship_unknown"}

    return {
        "source_count": len(sources),
        "relationship_counts": dict(by_relationship),
        "relationship_unknown_count": by_relationship.get("relationship_unknown", 0),
        "relationship_unknown_by_domain": dict(Counter(
            s.registrable_domain for s in sources if s.source_id in unknown_ids)),
        "relationship_unknown_by_source_kind": dict(Counter(
            s.kind for s in sources if s.source_id in unknown_ids)),
        "excerpt_present_count": sum(1 for n in excerpt_lengths if n > 0),
        "excerpt_length_buckets": dict(buckets),
        "source_confidence_score": getattr(source_confidence, "score", None),
        "corroboration_score": (
            source_confidence.components["corroboration"].score
            if source_confidence is not None
            and "corroboration" in getattr(source_confidence, "components", {})
            else None),
    }
