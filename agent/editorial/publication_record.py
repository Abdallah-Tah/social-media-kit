"""Publication metadata contract (Phase 1, Stage 3.5).

Saturation reads a publication's editorial identity from the ContentDecision
`metadata` dict. Nothing wrote those fields, so real history read as entirely
legacy records and saturation could only be exercised against synthetic data.
This is the contract and its writer.

Two fields are frozen at publication on purpose:

    theme         — derived from config at publish time
    editorial_day — derived from the timezone at publish time

Deriving them at read time meant editing `theme_map` or the editorial timezone
retroactively rewrote history: a post published in July could change theme in
September because a config line moved. Storing them makes past decisions
immutable. Read-time derivation survives only as a fallback for records written
before this contract existed.

`identity_source` and `identity_confidence` are recorded but deliberately NOT
acted on. Saturation still treats every `entity` as equally certain. Acting on
confidence is a real editorial choice with a cost either way — ignoring it risks
saturating on a misattributed entity, honouring it risks a saturation bypass
through deliberately vague attribution — and it should be made against a
measured confidence distribution from replay, not guessed at now.

Purity: building metadata is pure. Only `record_publication` writes, and nothing
in production calls it while EDITORIAL_SLOTS_ENABLED is false.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Iterable, Sequence

from .models import DEVELOPMENT_TYPES, Candidate

# Version of THIS contract, independent of models.NORMALIZATION_VERSION (how a
# candidate was built) and SaturationResult.version (how it was judged). A
# reader must be able to tell which shape of metadata it is looking at.
PUBLICATION_METADATA_VERSION = 1

# Editorial identity. Everything saturation and the observability metrics need.
IDENTITY_FIELDS = (
    "canonical_topic_id",
    "entity",
    "development_type",
    "artifact_type",
    "theme",
    "slot",
    "editorial_day",
    "source_fingerprint",
    "primary_source_url",
    "corroborating_domains",
    "identity_source",
    "identity_confidence",
    "schema_version",
)

# Publication identity. Separate because these answer "which post" rather than
# "what was it about": `publication_id` is the dedup key that distinguishes a
# retry of one post from two genuinely different posts on the same topic and
# day, and `published_at` is what every window is measured from.
PUBLICATION_FIELDS = ("publication_id", "published_at")

REQUIRED_FIELDS = IDENTITY_FIELDS + PUBLICATION_FIELDS

# Diagnostic-only markers that keep a record out of saturation history.
MODE_LIVE = "live"
MODE_SHADOW = "shadow"
MODE_SIMULATED = "simulated"
MODE_REPLAY = "replay"


class PublicationMetadataError(ValueError):
    """Reports every problem in a metadata block at once."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        joined = "\n  - ".join(self.problems)
        super().__init__(f"{len(self.problems)} problem(s):\n  - {joined}")


def editorial_day_for(stamp: dt.datetime, timezone: str) -> str:
    """Calendar day in the editorial zone, not UTC.

    A 02:00 UTC publication belongs to the previous New York editorial day.
    """
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(timezone)
    except Exception:  # noqa: BLE001 — degrade rather than fail a publish
        zone = dt.timezone.utc
    return stamp.astimezone(zone).strftime("%Y-%m-%d")


def build_publication_metadata(
    candidate: Candidate, *,
    slot: str,
    published_at: dt.datetime,
    publication_id: str,
    source_confidence: Any = None,
    theme: str | None = None,
    timezone: str | None = None,
    mode: str = MODE_LIVE,
    status: str = "published",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the metadata block for one publication. Pure; writes nothing.

    `theme` and `editorial_day` are resolved here and stored, so later config
    edits cannot rewrite what this publication was.
    """
    from .flags import editorial_timezone
    from .saturation import THEME_UNKNOWN, load_saturation_config, resolve_theme

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=dt.timezone.utc)
    published_at = published_at.astimezone(dt.timezone.utc)

    zone = timezone or editorial_timezone()
    entity = (candidate.subject_org or "").lower()

    if theme is None:
        theme = (candidate.metadata or {}).get("theme") or ""
    if not theme:
        try:
            theme = resolve_theme(entity, load_saturation_config())
        except Exception:  # noqa: BLE001 — a bad config must not block a publish
            theme = THEME_UNKNOWN

    primary = candidate.primary_source
    corroborating: list[str] = []
    if source_confidence is not None:
        component = getattr(source_confidence, "components", {}).get("corroboration")
        if component is not None:
            corroborating = list(component.extra.get("counted_domains") or ())

    metadata = {
        "schema_version": PUBLICATION_METADATA_VERSION,
        "canonical_topic_id": candidate.canonical_topic_id,
        "entity": entity,
        "development_type": candidate.development_type,
        "artifact_type": candidate.artifact_type,
        "theme": theme,
        "slot": slot,
        "editorial_day": editorial_day_for(published_at, zone),
        "source_fingerprint": candidate.source_fingerprint,
        "primary_source_url": primary.url if primary else "",
        "corroborating_domains": sorted(corroborating),
        # Recorded, not acted on. See the module docstring.
        "identity_source": candidate.subject_org_resolution_reason,
        "identity_confidence": round(float(candidate.subject_org_confidence), 2),
        "publication_id": str(publication_id),
        "published_at": published_at.isoformat(),
        "mode": mode,
        "status": status,
        "editorial_timezone": zone,
    }
    metadata.update(extra or {})
    return metadata


def validate_publication_metadata(metadata: dict[str, Any]) -> list[str]:
    """Return every problem with a metadata block. Empty list means valid."""
    problems: list[str] = []
    if not isinstance(metadata, dict):
        return ["metadata must be a mapping"]

    for name in REQUIRED_FIELDS:
        if name not in metadata:
            problems.append(f"missing required field: {name}")

    version = metadata.get("schema_version")
    if version is not None and (not isinstance(version, int) or isinstance(version, bool)):
        problems.append("schema_version must be an integer")
    elif isinstance(version, int) and version > PUBLICATION_METADATA_VERSION:
        problems.append(
            f"schema_version {version} is newer than this reader "
            f"({PUBLICATION_METADATA_VERSION})")

    development = metadata.get("development_type")
    if development is not None and development not in DEVELOPMENT_TYPES:
        problems.append(f"unknown development_type: {development!r}")

    confidence = metadata.get("identity_confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            problems.append("identity_confidence must be a number")
        elif not 0 <= confidence <= 1:
            problems.append(f"identity_confidence {confidence} outside 0-1")

    domains = metadata.get("corroborating_domains")
    if domains is not None and not isinstance(domains, list):
        problems.append("corroborating_domains must be a list")

    stamp = metadata.get("published_at")
    if stamp:
        try:
            parsed = dt.datetime.fromisoformat(str(stamp))
        except (TypeError, ValueError):
            problems.append(f"published_at is not an ISO timestamp: {stamp!r}")
        else:
            if parsed.tzinfo is None:
                problems.append("published_at must be timezone-aware")

    day = metadata.get("editorial_day")
    if day:
        try:
            dt.date.fromisoformat(str(day))
        except (TypeError, ValueError):
            problems.append(f"editorial_day is not YYYY-MM-DD: {day!r}")

    topic = metadata.get("canonical_topic_id")
    if topic and str(topic).count(":") != 2:
        problems.append(
            f"canonical_topic_id must be entity:development_type:release, "
            f"got {topic!r}")

    return problems


def assert_valid(metadata: dict[str, Any]) -> dict[str, Any]:
    problems = validate_publication_metadata(metadata)
    if problems:
        raise PublicationMetadataError(problems)
    return metadata


def record_publication(candidate: Candidate, *, job_id: str, slot: str,
                       published_at: dt.datetime, publication_id: str,
                       title: str = "", slug: str = "",
                       source_confidence: Any = None,
                       editorial_quality: int | None = None,
                       mode: str = MODE_LIVE, status: str = "published",
                       decision_log: Any = None,
                       **kwargs: Any) -> dict[str, Any]:
    """Append one publish-stage ContentDecision carrying the contract.

    The only writing function here. Nothing in production calls it while
    EDITORIAL_SLOTS_ENABLED is false; shadow and replay runs pass
    mode=MODE_SHADOW / MODE_REPLAY so their records are visible in diagnostics
    but never counted as saturation history.
    """
    from agent import content_decisions

    log = decision_log or content_decisions
    metadata = assert_valid(build_publication_metadata(
        candidate, slot=slot, published_at=published_at,
        publication_id=publication_id, source_confidence=source_confidence,
        mode=mode, status=status, **kwargs))

    log.accept(
        "publish", job_id,
        title=title or candidate.title,
        slug=slug,
        source_confidence=getattr(source_confidence, "score", None),
        editorial_quality=editorial_quality,
        publication_readiness="passed",
        sources=[s.url for s in candidate.sources],
        metadata=metadata,
    )
    return metadata


def backfill_metadata(row: dict[str, Any], timezone: str) -> dict[str, Any]:
    """Best-effort identity for a record written before this contract.

    Never invents an entity or a development type. What the canonical topic id
    already encodes is recovered; everything else stays empty and the record
    keeps reading as legacy.
    """
    metadata = dict(row.get("metadata") or {})
    topic = str(metadata.get("canonical_topic_id") or "")
    if topic.count(":") == 2:
        entity, development, _ = topic.split(":")
        metadata.setdefault("entity", entity)
        metadata.setdefault("development_type", development)

    stamp = metadata.get("published_at") or row.get("ts")
    if stamp and "editorial_day" not in metadata:
        try:
            parsed = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            metadata["editorial_day"] = editorial_day_for(parsed, timezone)
        except (TypeError, ValueError):
            pass

    metadata.setdefault("schema_version", 0)  # 0 = predates the contract
    return metadata
