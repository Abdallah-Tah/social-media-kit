"""Deterministic, explainable source-confidence scoring (Phase 1, Stage 2).

Scores the EVIDENCE behind a candidate on 0-100. Deliberately separate from the
opportunity score, the editorial-quality score, and the publication-readiness
decision — they answer different questions and fail for different reasons, and
blending them makes a weak-evidence story indistinguishable from a badly
written one.

Guarantees this module is built to keep:
  * pure and deterministic — same input, same output, always
  * no network calls, no LLM calls, no writes to any history file
  * `now` is injectable, so time-dependent scores are reproducible in tests
  * no admission decision — thresholds belong to Stage 4

The arithmetic encodes one editorial rule structurally rather than by
convention: authority can never rescue missing evidence. Domain authority (20)
+ recency (15) + traceability (10) = 45, which is below every slot's threshold,
so a famous outlet with no primary source and no corroboration cannot clear
admission no matter how well known it is.
"""
from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

KIT = Path(__file__).resolve().parents[2]
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

CONFIG_PATH = KIT / "config" / "source_confidence.yaml"

SCHEMA_VERSION = 1
SUPPORTED_VERSIONS = (1,)

COMPONENTS = (
    "primary_source",
    "corroboration",
    "domain_authority",
    "recency",
    "claim_traceability",
)
TOTAL_POINTS = 100

# The model is shared with the adapter and lives in models.py. It is imported
# rather than redefined so the scorer and candidate_adapter cannot drift apart.
# The dependency is one-way: this module never imports the adapter.
from .models import (  # noqa: E402
    FIRST_PARTY_KINDS,
    PRIMARY_KINDS,
    Candidate,
    Claim,
    SourceRef,
    canonical as _canonical_url,
    parse_timestamp,
    registrable_domain,
)

WARN_MISSING_EVENT_TIME = "missing_event_time"
WARN_FUTURE_TIMESTAMP = "future_timestamp"
WARN_CONFLICTING_TIMESTAMPS = "conflicting_source_timestamps"
WARN_UNPARSEABLE_TIMESTAMP = "unparseable_timestamp"
WARN_UNVERIFIED_VENDOR_CLAIM = "unverified_vendor_claim"
WARN_NO_MATERIAL_CLAIMS = "no_material_claims"

# Why a source was not counted toward independent corroboration.
EXCLUSION_SYNDICATED = "syndicated_copy"
EXCLUSION_PRESS_MIRROR = "press_release_mirror"
EXCLUSION_SAME_ORG = "same_organization"
EXCLUSION_DUPLICATE_URL = "duplicate_canonical_url"
EXCLUSION_FIRST_PARTY = "first_party_subject"
EXCLUSION_NO_EVIDENCE = "repeats_vendor_statement_without_evidence"


class ScoringConfigError(ValueError):
    """Raised for any problem in config/source_confidence.yaml.

    Reports every problem found, not just the first.
    """

    def __init__(self, problems: list[str], path: Path | None = None):
        self.problems = list(problems)
        self.path = path
        location = f" in {path}" if path else ""
        joined = "\n  - ".join(self.problems)
        super().__init__(f"{len(self.problems)} problem(s){location}:\n  - {joined}")


# ── Output model ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Component:
    score: int
    max: int
    reason: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "max": self.max, "reason": self.reason, **self.extra}


@dataclass(frozen=True)
class SourceConfidence:
    score: int
    components: dict[str, Component]
    warnings: tuple[str, ...] = ()
    version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "components": {k: v.to_dict() for k, v in self.components.items()},
            "warnings": list(self.warnings),
            "version": self.version,
        }


# ── Configuration ───────────────────────────────────────────────────────────

def _validate_recency_profile(name: str, bands: Any, maximum: int,
                              problems: list[str]) -> tuple[tuple[float | None, int], ...]:
    if not isinstance(bands, list) or not bands:
        problems.append(f"recency profile {name!r}: must be a non-empty list of bands")
        return ()

    parsed: list[tuple[float | None, int]] = []
    for index, band in enumerate(bands):
        if not isinstance(band, dict):
            problems.append(f"recency profile {name!r}: band {index} must be a mapping")
            continue
        bound, score = band.get("max_age_hours"), band.get("score")
        if bound is not None and (not isinstance(bound, (int, float))
                                  or isinstance(bound, bool) or bound <= 0):
            problems.append(
                f"recency profile {name!r}: band {index} max_age_hours must be "
                f"a positive number or null")
            continue
        if not isinstance(score, int) or isinstance(score, bool):
            problems.append(f"recency profile {name!r}: band {index} score must be an integer")
            continue
        if not 0 <= score <= maximum:
            problems.append(
                f"recency profile {name!r}: band {index} score {score} outside 0-{maximum}")
            continue
        parsed.append((None if bound is None else float(bound), score))

    if not parsed:
        return ()
    if sum(1 for bound, _ in parsed if bound is None) != 1 or parsed[-1][0] is not None:
        problems.append(
            f"recency profile {name!r}: needs exactly one catch-all band "
            f"(max_age_hours: null) and it must be last")
        return tuple(parsed)

    bounds = [bound for bound, _ in parsed[:-1]]
    if len(set(bounds)) != len(bounds):
        problems.append(f"recency profile {name!r}: duplicate max_age_hours boundary")
    if bounds != sorted(bounds):
        problems.append(f"recency profile {name!r}: bands must increase in max_age_hours")
    scores = [score for _, score in parsed]
    if scores != sorted(scores, reverse=True):
        problems.append(f"recency profile {name!r}: scores must be non-increasing with age")
    return tuple(parsed)


@dataclass(frozen=True)
class ScoringConfig:
    version: int
    weights: dict[str, int]
    primary_source: dict[str, int]
    corroboration: dict[str, int]
    recency_profiles: dict[str, tuple[tuple[float | None, int], ...]]
    recency_default_profile: str
    artifact_profiles: dict[str, str]
    claim_traceability: dict[str, Any]
    timestamps: dict[str, float]
    path: Path | None = None

    def profile_for(self, candidate: Candidate) -> tuple[str, tuple[tuple[float | None, int], ...]]:
        if candidate.artifact and candidate.artifact in self.artifact_profiles:
            name = self.artifact_profiles[candidate.artifact]
        elif candidate.content_kind in self.recency_profiles:
            name = candidate.content_kind
        else:
            name = self.recency_default_profile
        return name, self.recency_profiles[name]


def load_scoring_config(path: Path | str | None = None) -> ScoringConfig:
    """Parse and fully validate the scoring policy. Never partially loads."""
    from agent.config import _read_yaml

    target = Path(path) if path else CONFIG_PATH
    problems: list[str] = []

    if not target.exists():
        raise ScoringConfigError([f"config file not found: {target}"], target)
    data = _read_yaml(target)
    if not isinstance(data, dict) or not data:
        raise ScoringConfigError(["file is empty or not a YAML mapping"], target)

    if data.get("version") not in SUPPORTED_VERSIONS:
        problems.append(f"unsupported version {data.get('version')!r}")

    raw_weights = data.get("weights")
    weights: dict[str, int] = {}
    if not isinstance(raw_weights, dict) or not raw_weights:
        problems.append("weights must be a non-empty mapping")
    else:
        unknown = sorted(set(raw_weights) - set(COMPONENTS))
        if unknown:
            problems.append(f"unknown component name(s): {', '.join(unknown)}")
        missing = sorted(set(COMPONENTS) - set(raw_weights))
        if missing:
            problems.append(f"missing component weight(s): {', '.join(missing)}")
        for name, value in raw_weights.items():
            if not isinstance(value, int) or isinstance(value, bool):
                problems.append(f"weight {name!r} must be an integer")
            elif value < 0:
                problems.append(f"weight {name!r} is negative ({value})")
            else:
                weights[name] = value
        total = sum(weights.get(c, 0) for c in COMPONENTS)
        if not missing and not unknown and total != TOTAL_POINTS:
            problems.append(f"component maximums sum to {total}, must be {TOTAL_POINTS}")

    def _bands(section: str, keys: Iterable[str], maximum: int) -> dict[str, int]:
        raw = data.get(section)
        out: dict[str, int] = {}
        if not isinstance(raw, dict):
            problems.append(f"{section} must be a mapping")
            return out
        for key in keys:
            value = raw.get(key)
            if not isinstance(value, int) or isinstance(value, bool):
                problems.append(f"{section}.{key} must be an integer")
            elif not 0 <= value <= maximum:
                problems.append(f"{section}.{key}={value} outside 0-{maximum}")
            else:
                out[key] = value
        return out

    primary = _bands("primary_source",
                     ("direct", "first_party_indirect", "secondary_linking", "none"),
                     weights.get("primary_source", 30))
    corrob = _bands("corroboration", ("two_or_more", "one", "same_org_only", "none"),
                    weights.get("corroboration", 25))
    trace = _bands("claim_traceability", ("all_traceable", "most_traceable", "basic_only", "none"),
                   weights.get("claim_traceability", 10))

    threshold = (data.get("claim_traceability") or {}).get("most_threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) \
            or not 0 < threshold <= 1:
        problems.append("claim_traceability.most_threshold must be a number in (0, 1]")
        threshold = 0.6

    raw_profiles = data.get("recency_profiles")
    profiles: dict[str, tuple[tuple[float | None, int], ...]] = {}
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        problems.append("recency_profiles must be a non-empty mapping")
    else:
        for name, bands in raw_profiles.items():
            profiles[name] = _validate_recency_profile(
                name, bands, weights.get("recency", 15), problems)

    default_profile = data.get("recency_default_profile")
    if default_profile not in profiles:
        problems.append(f"recency_default_profile {default_profile!r} is not a defined profile")

    artifact_profiles = data.get("artifact_profiles") or {}
    if not isinstance(artifact_profiles, dict):
        problems.append("artifact_profiles must be a mapping")
        artifact_profiles = {}
    else:
        try:
            import content_formats as CF

            known_artifacts = set(CF.EDITORIAL_ARTIFACTS)
        except Exception:  # noqa: BLE001 — validated below as unknown
            known_artifacts = set()
        for artifact, profile_name in artifact_profiles.items():
            if artifact not in known_artifacts:
                problems.append(f"artifact_profiles: unknown artifact {artifact!r}")
            if profile_name not in profiles:
                problems.append(
                    f"artifact_profiles[{artifact!r}]: unknown profile {profile_name!r}")

    raw_ts = data.get("timestamps") or {}
    if not isinstance(raw_ts, dict):
        problems.append("timestamps must be a mapping")
        raw_ts = {}
    timestamps = {
        "future_tolerance_minutes": float(raw_ts.get("future_tolerance_minutes", 5) or 0),
        "conflict_tolerance_hours": float(raw_ts.get("conflict_tolerance_hours", 24) or 0),
    }

    if problems:
        raise ScoringConfigError(problems, target)

    return ScoringConfig(
        version=int(data["version"]),
        weights=weights,
        primary_source=primary,
        corroboration=corrob,
        recency_profiles=profiles,
        recency_default_profile=str(default_profile),
        artifact_profiles=dict(artifact_profiles),
        claim_traceability={**trace, "most_threshold": float(threshold)},
        timestamps=timestamps,
        path=target,
    )


# ── Domain identity ─────────────────────────────────────────────────────────

def _org_identity(ref: SourceRef) -> str:
    """Explicit organization_id, then publisher, then registrable domain."""
    return ref.organization()


def _canonical(url: str) -> str:
    return _canonical_url(url)


# ── Components ──────────────────────────────────────────────────────────────

def _score_primary_source(candidate: Candidate, config: ScoringConfig,
                          warnings: list[str]) -> Component:
    maximum = config.weights["primary_source"]
    primaries = [s for s in candidate.sources if s.is_primary]
    exact = [s for s in primaries if s.covers_exact_development]

    if exact:
        urls = sorted({s.url for s in exact})
        kinds = sorted({s.kind for s in exact})
        return Component(
            config.primary_source["direct"], maximum,
            f"primary source tied to the exact development ({', '.join(kinds)})",
            {"source_urls": urls},
        )
    if primaries:
        urls = sorted({s.url for s in primaries})
        kinds = sorted({s.kind for s in primaries})
        return Component(
            config.primary_source["first_party_indirect"], maximum,
            f"first-party source present but indirect or incomplete ({', '.join(kinds)})",
            {"source_urls": urls},
        )

    linking = [s for s in candidate.sources if s.links_to_primary]
    if linking:
        urls = sorted({s.url for s in linking})
        return Component(
            config.primary_source["secondary_linking"], maximum,
            "credible secondary source citing a primary source that is not available",
            {"source_urls": urls},
        )
    return Component(config.primary_source["none"], maximum,
                     "no primary-source evidence", {"source_urls": []})


def _score_corroboration(candidate: Candidate, config: ScoringConfig,
                         warnings: list[str]) -> Component:
    """Count distinct independent organizations, not distinct URLs or titles.

    Matching titles never establish corroboration: two outlets running the same
    wire copy agree about nothing beyond having received the same email.
    """
    maximum = config.weights["corroboration"]
    subject = (candidate.subject_org or "").strip().lower()

    counted: dict[str, str] = {}       # org -> representative url
    excluded: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    suppressed_orgs: set[str] = set()  # orgs present but not independent

    for ref in candidate.sources:
        org = _org_identity(ref)
        canon = _canonical(ref.url)

        if canon and canon in seen_urls:
            excluded.append({"domain": org, "reason": EXCLUSION_DUPLICATE_URL})
            suppressed_orgs.add(org)
            continue
        if canon:
            seen_urls.add(canon)

        if ref.syndicated_from:
            excluded.append({"domain": org, "reason": EXCLUSION_SYNDICATED})
            suppressed_orgs.add(org)
            continue
        if ref.is_press_release:
            excluded.append({"domain": org, "reason": EXCLUSION_PRESS_MIRROR})
            suppressed_orgs.add(org)
            continue
        # First-party material is evidence, not corroboration. Detected two
        # ways: an explicit subject_org match, or a source kind that is by
        # definition the subject's own (docs, changelog, its own repo). The
        # second check matters because subject_org is often unknown, and
        # without it a vendor's docs would silently read as an independent
        # organization agreeing with the vendor.
        if (subject and org == subject) or ref.kind in FIRST_PARTY_KINDS:
            excluded.append({"domain": org, "reason": EXCLUSION_FIRST_PARTY})
            suppressed_orgs.add(org)
            continue
        if not ref.adds_independent_evidence:
            excluded.append({"domain": org, "reason": EXCLUSION_NO_EVIDENCE})
            suppressed_orgs.add(org)
            continue
        if org in counted:
            excluded.append({"domain": org, "reason": EXCLUSION_SAME_ORG})
            continue
        if org:
            counted[org] = ref.url

    independent = sorted(counted)
    extra = {
        "counted_domains": independent,
        "excluded_domains": sorted(excluded, key=lambda e: (e["domain"], e["reason"])),
    }

    if len(independent) >= 2:
        return Component(config.corroboration["two_or_more"], maximum,
                         f"{len(independent)} independent organizations: "
                         f"{', '.join(independent)}", extra)
    if len(independent) == 1:
        return Component(config.corroboration["one"], maximum,
                         f"one independent organization: {independent[0]}", extra)
    if excluded:
        return Component(config.corroboration["same_org_only"], maximum,
                         "multiple pages but none independent "
                         f"({len(excluded)} excluded)", extra)
    return Component(config.corroboration["none"], maximum,
                     "no independent corroboration", extra)


def _score_domain_authority(candidate: Candidate, config: ScoringConfig,
                            warnings: list[str]) -> Component:
    """Normalize the existing authority scorer; never re-implement its tables."""
    from agent.feed_authority import item_authority

    maximum = config.weights["domain_authority"]
    breakdown = item_authority(candidate.url, candidate.source,
                               metadata=candidate.metadata or {})
    score = int(round(max(0.0, min(1.0, breakdown.final_score)) * maximum))
    return Component(
        score, maximum,
        f"authority {breakdown.final_score:.2f} normalized to {score}/{maximum}"
        + (f"; {', '.join(breakdown.signals)}" if breakdown.signals else ""),
        {"existing_authority_breakdown": breakdown.to_dict()},
    )


def _resolve_event_time(candidate: Candidate, config: ScoringConfig,
                        warnings: list[str]) -> dt.datetime | None:
    """Earliest credible source/event time. Ingestion time is never used."""
    stamps: list[dt.datetime] = []
    for raw in [candidate.event_time] + [s.published_at for s in candidate.sources]:
        if not raw:
            continue
        parsed = parse_timestamp(raw)
        if parsed is None:
            if WARN_UNPARSEABLE_TIMESTAMP not in warnings:
                warnings.append(WARN_UNPARSEABLE_TIMESTAMP)
            continue
        stamps.append(parsed)

    if not stamps:
        return None
    spread_hours = (max(stamps) - min(stamps)).total_seconds() / 3600
    if spread_hours > config.timestamps["conflict_tolerance_hours"]:
        warnings.append(WARN_CONFLICTING_TIMESTAMPS)
    # Earliest wins: the event happened when it first appeared, not when the
    # slowest aggregator noticed it.
    return min(stamps)


def _score_recency(candidate: Candidate, config: ScoringConfig,
                   now: dt.datetime, warnings: list[str]) -> Component:
    maximum = config.weights["recency"]
    profile_name, bands = config.profile_for(candidate)
    event = _resolve_event_time(candidate, config, warnings)

    if event is None:
        warnings.append(WARN_MISSING_EVENT_TIME)
        return Component(0, maximum, "no usable event or publication time",
                         {"event_time": None, "age_hours": None,
                          "profile": profile_name})

    age_hours = (now - event).total_seconds() / 3600
    tolerance = config.timestamps["future_tolerance_minutes"] / 60

    if age_hours < -tolerance:
        warnings.append(WARN_FUTURE_TIMESTAMP)
        # A future timestamp must never buy maximum recency. Cap at the band
        # below the top so an incorrect (or optimistic) date cannot outrank a
        # correctly-dated story.
        capped = bands[1][1] if len(bands) > 1 else 0
        return Component(
            capped, maximum,
            f"event time is {abs(age_hours):.1f}h in the future; "
            f"flagged and capped below maximum",
            {"event_time": event.isoformat(), "age_hours": round(age_hours, 2),
             "profile": profile_name},
        )

    effective = max(0.0, age_hours)
    for bound, score in bands:
        if bound is None or effective <= bound:
            label = "within catch-all band" if bound is None else f"within {bound:g}h"
            return Component(
                score, maximum,
                f"{effective:.1f}h old, {label} of the {profile_name!r} profile",
                {"event_time": event.isoformat(), "age_hours": round(effective, 2),
                 "profile": profile_name},
            )
    return Component(0, maximum, "older than every band",
                     {"event_time": event.isoformat(),
                      "age_hours": round(effective, 2), "profile": profile_name})


def _score_claim_traceability(candidate: Candidate, config: ScoringConfig,
                              independent_orgs: int, warnings: list[str]) -> Component:
    """Can the material claims be mapped to specific evidence?

    A vendor's own benchmark is traceable to the vendor and nothing else. It
    only counts once an independent organization has produced evidence, which
    is why this needs the corroboration result.
    """
    maximum = config.weights["claim_traceability"]
    known_urls = {_canonical(s.url) for s in candidate.sources if s.url}
    material = [c for c in candidate.claims if c.material]

    if not material:
        warnings.append(WARN_NO_MATERIAL_CLAIMS)
        has_excerpt = any(s.excerpt for s in candidate.sources)
        return Component(
            config.claim_traceability["basic_only"] if has_excerpt
            else config.claim_traceability["none"],
            maximum,
            "no material claims declared; "
            + ("basic event facts are sourced" if has_excerpt else "no source excerpts"),
            {"traceable_claims": 0, "material_claims": 0},
        )

    traceable = 0
    for claim in material:
        mapped = bool(claim.source_url) and _canonical(claim.source_url) in known_urls
        if not mapped and claim.excerpt:
            mapped = True  # an excerpt is a specific enough mapping
        if mapped and claim.vendor_claim and independent_orgs < 1:
            warnings.append(WARN_UNVERIFIED_VENDOR_CLAIM)
            mapped = False
        if mapped:
            traceable += 1

    ratio = traceable / len(material)
    if ratio >= 1.0:
        score, reason = config.claim_traceability["all_traceable"], "every material claim maps to a source"
    elif ratio >= config.claim_traceability["most_threshold"]:
        score, reason = config.claim_traceability["most_traceable"], "most material claims are traceable"
    elif ratio > 0:
        score, reason = config.claim_traceability["basic_only"], "only basic facts are traceable"
    else:
        score, reason = config.claim_traceability["none"], "key claims have no evidence mapping"

    return Component(score, maximum, f"{reason} ({traceable}/{len(material)})",
                     {"traceable_claims": traceable, "material_claims": len(material)})


# ── Entry point ─────────────────────────────────────────────────────────────

def score_source_confidence(candidate: Candidate,
                            config: ScoringConfig | None = None,
                            now: dt.datetime | None = None) -> SourceConfidence:
    """Score the evidence behind one candidate on 0-100.

    Pure: no network, no LLM, no writes. `now` is injectable so a time-dependent
    score is reproducible; it defaults to the current UTC instant.
    """
    config = config or load_scoring_config()
    now = (now or dt.datetime.now(dt.timezone.utc))
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now = now.astimezone(dt.timezone.utc)

    warnings: list[str] = []
    primary = _score_primary_source(candidate, config, warnings)
    corroboration = _score_corroboration(candidate, config, warnings)
    authority = _score_domain_authority(candidate, config, warnings)
    recency = _score_recency(candidate, config, now, warnings)
    traceability = _score_claim_traceability(
        candidate, config, len(corroboration.extra["counted_domains"]), warnings)

    components = {
        "primary_source": primary,
        "corroboration": corroboration,
        "domain_authority": authority,
        "recency": recency,
        "claim_traceability": traceability,
    }
    total = sum(c.score for c in components.values())

    # Deduplicated but order-stable, so the same input yields the same list.
    seen: set[str] = set()
    ordered_warnings = tuple(
        w for w in warnings if not (w in seen or seen.add(w))
    )
    return SourceConfidence(
        score=max(0, min(TOTAL_POINTS, total)),
        components=components,
        warnings=ordered_warnings,
    )
