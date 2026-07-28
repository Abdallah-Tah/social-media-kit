"""Normalize existing SMKit intelligence records into editorial Candidates
(Phase 1, Stage 2.5).

Stage 2 produced a correct scorer that nothing could feed. This is the missing
production adapter: it converts the records SMKit already produces — feed items,
story clusters, GitHub repository records, paper records, vendor announcements,
opportunity-engine output, authority metadata — into the shared model in
models.py.

No parallel intelligence model is introduced. Existing structures are read by
duck typing and mapped onto the one Candidate model the scorer already uses.

Guarantees:
  * deterministic — same input, same output, including id and fingerprint
  * no LLM, no network, no publishing
  * no writes to live history, no mutation of the records passed in
  * normalization is separately testable; only `normalize_and_score` combines
    it with the scorer, and that is an orchestration convenience

Failure behaviour is deliberately lopsided. Missing optional metadata produces
warnings and an explicitly-marked-unknown field; only a structurally unusable
record (no title AND no URL) is rejected, and then with an exact reason. A
pipeline that silently drops candidates is one that silently stops publishing.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

KIT = Path(__file__).resolve().parents[2]
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from .models import (
    CLAIM_TYPES,
    DEVELOPMENT_TYPES,
    TRACE_UNASSESSED,
    TRACEABLE,
    UNTRACEABLE,
    VERIFIED_INDEPENDENT,
    VERIFIED_UNKNOWN,
    VERIFIED_VENDOR,
    WARN_CONFLICTING_TIMESTAMPS,
    WARN_DEVELOPMENT_TYPE_UNKNOWN,
    WARN_EVENT_TIME_FROM_DISCOVERY,
    WARN_MISSING_EVENT_TIME,
    WARN_NO_CLAIMS_EXTRACTED,
    WARN_NO_PRIMARY_SOURCE,
    WARN_SUBJECT_ORG_LOW_CONFIDENCE,
    WARN_SUBJECT_ORG_UNRESOLVED,
    WARN_TOPIC_KEY_FROM_TITLE,
    WARN_UNPARSEABLE_TIMESTAMP,
    Candidate,
    Claim,
    NormalizationError,
    SourceRef,
    canonical,
    digest,
    host_of,
    normalize_title,
    parse_timestamp,
    registrable_domain,
    slugify,
)

CONFIG_PATH = KIT / "config" / "editorial_normalization.yaml"
SUPPORTED_VERSIONS = (1,)

REJECT_NO_IDENTITY = "no_title_and_no_url"
REJECT_EMPTY_RECORD = "empty_record"

# Feed collectors whose items are aggregated links, not first-party reporting.
_AGGREGATOR_SOURCES = frozenset({"hackernews", "google_news"})

_GITHUB_RELEASE_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/releases", re.I)
_GITHUB_REPO_RE = re.compile(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)", re.I)


class NormalizationConfigError(ValueError):
    """Reports every problem in config/editorial_normalization.yaml at once."""

    def __init__(self, problems: list[str], path: Path | None = None):
        self.problems = list(problems)
        self.path = path
        joined = "\n  - ".join(self.problems)
        super().__init__(
            f"{len(self.problems)} problem(s)"
            f"{f' in {path}' if path else ''}:\n  - {joined}")


# ── Configuration ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TypeRule:
    development_type: str
    source_kinds: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    url_patterns: tuple[re.Pattern, ...] = ()
    title_patterns: tuple[re.Pattern, ...] = ()
    min_title_words: int = 0


@dataclass(frozen=True)
class NormalizationConfig:
    version: int
    rules: tuple[TypeRule, ...]
    default_development_type: str
    org_aliases: dict[str, dict[str, Any]]
    org_min_confidence: float
    org_confidence: dict[str, float]
    topic: dict[str, Any]
    timestamps: dict[str, Any]
    claims: dict[str, Any]
    path: Path | None = None


def _compile(patterns: Any, label: str, problems: list[str]) -> tuple[re.Pattern, ...]:
    out = []
    for raw in patterns or ():
        try:
            out.append(re.compile(raw, re.I))
        except re.error as exc:
            problems.append(f"{label}: invalid regex {raw!r} ({exc})")
    return tuple(out)


def load_normalization_config(path: Path | str | None = None) -> NormalizationConfig:
    """Parse and fully validate the normalization policy. Never partially loads."""
    from agent.config import _read_yaml

    target = Path(path) if path else CONFIG_PATH
    problems: list[str] = []

    if not target.exists():
        raise NormalizationConfigError([f"config file not found: {target}"], target)
    data = _read_yaml(target)
    if not isinstance(data, dict) or not data:
        raise NormalizationConfigError(["file is empty or not a YAML mapping"], target)

    if data.get("version") not in SUPPORTED_VERSIONS:
        problems.append(f"unsupported version {data.get('version')!r}")

    default_type = data.get("default_development_type", "unknown")
    if default_type not in DEVELOPMENT_TYPES:
        problems.append(f"default_development_type {default_type!r} is not a known type")

    rules: list[TypeRule] = []
    raw_rules = data.get("development_type_rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        problems.append("development_type_rules must be a non-empty list")
        raw_rules = []
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            problems.append(f"development_type_rules[{index}] must be a mapping")
            continue
        dtype = raw.get("type")
        if dtype not in DEVELOPMENT_TYPES:
            problems.append(
                f"development_type_rules[{index}]: unknown type {dtype!r}; "
                f"known: {', '.join(DEVELOPMENT_TYPES)}")
            continue
        rule = TypeRule(
            development_type=dtype,
            source_kinds=tuple(raw.get("source_kinds") or ()),
            domains=tuple(raw.get("domains") or ()),
            url_patterns=_compile(raw.get("url_patterns"),
                                  f"development_type_rules[{index}].url_patterns", problems),
            title_patterns=_compile(raw.get("title_patterns"),
                                    f"development_type_rules[{index}].title_patterns", problems),
            min_title_words=int(raw.get("min_title_words") or 0),
        )
        if not any([rule.source_kinds, rule.domains, rule.url_patterns,
                    rule.title_patterns, rule.min_title_words]):
            problems.append(f"development_type_rules[{index}]: rule has no conditions")
        rules.append(rule)

    aliases = data.get("organization_aliases") or {}
    if not isinstance(aliases, dict):
        problems.append("organization_aliases must be a mapping")
        aliases = {}
    for key, spec in aliases.items():
        if not isinstance(spec, dict):
            problems.append(f"organization_aliases[{key!r}] must be a mapping")
        elif not spec.get("domains") and not spec.get("names"):
            problems.append(
                f"organization_aliases[{key!r}] needs at least one domain or name")

    subject = data.get("subject_org") or {}
    min_conf = subject.get("min_confidence", 0.5)
    if not isinstance(min_conf, (int, float)) or isinstance(min_conf, bool) \
            or not 0 < min_conf <= 1:
        problems.append("subject_org.min_confidence must be a number in (0, 1]")
        min_conf = 0.5
    confidences = subject.get("confidence") or {}
    if not isinstance(confidences, dict):
        problems.append("subject_org.confidence must be a mapping")
        confidences = {}
    for name, value in confidences.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) \
                or not 0 <= value <= 1:
            problems.append(f"subject_org.confidence[{name!r}] must be within 0-1")

    topic = data.get("topic") or {}
    if not isinstance(topic, dict):
        problems.append("topic must be a mapping")
        topic = {}
    for key in ("model_name_pattern", "version_pattern"):
        if topic.get(key):
            _compile([topic[key]], f"topic.{key}", problems)
    for dtype in topic.get("month_bucket_types") or ():
        if dtype not in DEVELOPMENT_TYPES:
            problems.append(f"topic.month_bucket_types: unknown type {dtype!r}")

    claims = data.get("claims") or {}
    if not isinstance(claims, dict):
        problems.append("claims must be a mapping")
        claims = {}
    for key in ("benchmark_patterns", "pricing_patterns"):
        _compile(claims.get(key), f"claims.{key}", problems)
    for dtype, ctype in (claims.get("event_claim_types") or {}).items():
        if dtype not in DEVELOPMENT_TYPES:
            problems.append(f"claims.event_claim_types: unknown development type {dtype!r}")
        if ctype not in CLAIM_TYPES:
            problems.append(f"claims.event_claim_types[{dtype!r}]: unknown claim type {ctype!r}")

    if problems:
        raise NormalizationConfigError(problems, target)

    return NormalizationConfig(
        version=int(data["version"]),
        rules=tuple(rules),
        default_development_type=str(default_type),
        org_aliases=dict(aliases),
        org_min_confidence=float(min_conf),
        org_confidence={k: float(v) for k, v in confidences.items()},
        topic=dict(topic),
        timestamps=dict(data.get("timestamps") or {}),
        claims=dict(claims),
        path=target,
    )


_CACHED_CONFIG: NormalizationConfig | None = None


def _config(config: NormalizationConfig | None) -> NormalizationConfig:
    global _CACHED_CONFIG
    if config is not None:
        return config
    if _CACHED_CONFIG is None:
        _CACHED_CONFIG = load_normalization_config()
    return _CACHED_CONFIG


# ── Source extraction ───────────────────────────────────────────────────────

def _as_dict(record: Any) -> dict[str, Any]:
    """Read any record shape without mutating it."""
    if isinstance(record, dict):
        return dict(record)
    if hasattr(record, "to_dict"):
        try:
            return dict(record.to_dict())
        except Exception:  # noqa: BLE001 — fall through to attribute reads
            pass
    return {k: v for k, v in vars(record).items()} if hasattr(record, "__dict__") else {}


def _source_from_mapping(raw: dict[str, Any], default_discovered: str = "") -> SourceRef | None:
    url = str(raw.get("url") or raw.get("link") or "").strip()
    if not url:
        return None
    return SourceRef(
        url=url,
        kind=str(raw.get("kind") or raw.get("source_kind") or "secondary"),
        title=str(raw.get("title") or ""),
        published_at=str(raw.get("published_at") or raw.get("publication_time")
                         or raw.get("date") or ""),
        publisher=str(raw.get("publisher") or ""),
        covers_exact_development=bool(raw.get("covers_exact_development", False)),
        links_to_primary=bool(raw.get("links_to_primary", False)),
        syndicated_from=raw.get("syndicated_from") or None,
        is_press_release=bool(raw.get("is_press_release", False)),
        adds_independent_evidence=bool(raw.get("adds_independent_evidence", True)),
        excerpt=str(raw.get("excerpt") or raw.get("summary") or ""),
        discovered_at=str(raw.get("discovered_at") or default_discovered),
        organization_id=str(raw.get("organization_id") or ""),
        cluster_id=str(raw.get("cluster_id") or ""),
        cluster_member_count=int(raw.get("cluster_member_count") or 0),
        evidence_reference=str(raw.get("evidence_reference") or ""),
        feed_source=str(raw.get("feed_source") or raw.get("source") or ""),
    )


def dedupe_sources(refs: Iterable[SourceRef]) -> tuple[SourceRef, ...]:
    """One entry per canonical URL.

    The same story arriving from Google News, Hacker News, and an RSS feed is
    one source, not three. Merging keeps the richest view: a primary kind beats
    `secondary`, and any excerpt or timestamp found on a later copy is retained.
    """
    merged: dict[str, SourceRef] = {}
    order: list[str] = []
    for ref in refs:
        if not ref or not ref.url:
            continue
        key = ref.canonical_url or ref.url.lower()
        existing = merged.get(key)
        if existing is None:
            merged[key] = ref
            order.append(key)
            continue
        merged[key] = SourceRef(
            url=existing.url,
            kind=ref.kind if (ref.is_primary and not existing.is_primary) else existing.kind,
            title=existing.title or ref.title,
            published_at=existing.published_at or ref.published_at,
            publisher=existing.publisher or ref.publisher,
            covers_exact_development=(existing.covers_exact_development
                                      or ref.covers_exact_development),
            links_to_primary=existing.links_to_primary or ref.links_to_primary,
            syndicated_from=existing.syndicated_from or ref.syndicated_from,
            is_press_release=existing.is_press_release or ref.is_press_release,
            adds_independent_evidence=(existing.adds_independent_evidence
                                       and ref.adds_independent_evidence),
            excerpt=existing.excerpt or ref.excerpt,
            discovered_at=existing.discovered_at or ref.discovered_at,
            organization_id=existing.organization_id or ref.organization_id,
            cluster_id=existing.cluster_id or ref.cluster_id,
            cluster_member_count=max(existing.cluster_member_count,
                                     ref.cluster_member_count),
            evidence_reference=existing.evidence_reference or ref.evidence_reference,
            feed_source=existing.feed_source or ref.feed_source,
        )
    return tuple(merged[k] for k in order)


# ── Development type ────────────────────────────────────────────────────────

def resolve_development_type(title: str, url: str, sources: Iterable[SourceRef],
                             metadata: dict[str, Any],
                             config: NormalizationConfig) -> tuple[str, str]:
    """First matching rule wins. Returns (type, reason)."""
    explicit = metadata.get("development_type")
    if explicit in DEVELOPMENT_TYPES:
        return explicit, "explicit_metadata"

    kinds = {s.kind for s in sources}
    domains = {s.registrable_domain for s in sources} | {registrable_domain(url)}
    urls = [s.url for s in sources] + ([url] if url else [])
    words = len(normalize_title(title).split())

    for rule in config.rules:
        if rule.source_kinds and not (kinds & set(rule.source_kinds)):
            continue
        if rule.domains and not (domains & set(rule.domains)):
            continue
        if rule.url_patterns and not any(p.search(u) for p in rule.url_patterns
                                         for u in urls):
            continue
        if rule.title_patterns and not any(p.search(title or "")
                                           for p in rule.title_patterns):
            continue
        if rule.min_title_words and words < rule.min_title_words:
            continue
        return rule.development_type, f"rule:{rule.development_type}"
    return config.default_development_type, "no_rule_matched"


# ── Subject organization ────────────────────────────────────────────────────

@dataclass(frozen=True)
class OrgResolution:
    org: str = ""
    name: str = ""
    confidence: float = 0.0
    reason: str = "unresolved"


def resolve_subject_org(title: str, url: str, sources: Iterable[SourceRef],
                        metadata: dict[str, Any],
                        config: NormalizationConfig) -> OrgResolution:
    """Resolve the organization a development is about.

    A bare word match never resolves anything: only a CONFIGURED alias can
    resolve from title text, and it does so at medium confidence. Anything
    below `min_confidence` is reported unresolved rather than guessed.
    """
    conf = config.org_confidence
    sources = list(sources)

    explicit = (metadata.get("subject_org") or metadata.get("vendor")
                or metadata.get("organization") or "")
    if explicit:
        key = str(explicit).strip().lower()
        return OrgResolution(key, _display_for(key, config) or str(explicit),
                             conf.get("explicit_metadata", 1.0), "explicit_metadata")

    owner = metadata.get("repository_owner") or metadata.get("owner")
    if not owner:
        for candidate_url in [url] + [s.url for s in sources]:
            match = _GITHUB_REPO_RE.match(candidate_url or "")
            if match:
                owner = match.group(1)
                break
    if owner:
        key = str(owner).strip().lower()
        return OrgResolution(key, _display_for(key, config) or str(owner),
                             conf.get("repository_owner", 0.9), "repository_owner")

    # Sorted so the result cannot depend on the order sources arrived in.
    first_party = sorted({s.registrable_domain for s in sources
                          if s.is_first_party and s.registrable_domain})
    if first_party:
        domain = first_party[0]
        key = _alias_for_domain(domain, config) or domain
        return OrgResolution(key, _display_for(key, config) or domain,
                             conf.get("first_party_source_domain", 0.9),
                             "first_party_source_domain")

    all_domains = sorted({s.registrable_domain for s in sources if s.registrable_domain})
    for domain in all_domains:
        alias = _alias_for_domain(domain, config)
        if alias:
            return OrgResolution(alias, _display_for(alias, config) or alias,
                                 conf.get("configured_alias_domain", 0.8),
                                 "configured_alias_domain")

    normalized = normalize_title(title)
    for alias in sorted(config.org_aliases):
        spec = config.org_aliases[alias] or {}
        names = [alias] + list(spec.get("names") or ())
        for name in sorted(set(names)):
            token = normalize_title(name)
            if token and re.search(rf"(?:^| ){re.escape(token)}(?:$| )", normalized):
                confidence = conf.get("configured_alias_name", 0.6)
                if confidence < config.org_min_confidence:
                    return OrgResolution()
                return OrgResolution(alias, _display_for(alias, config) or alias,
                                     confidence, "configured_alias_name")

    cluster_domain = metadata.get("cluster_primary_domain")
    if cluster_domain:
        confidence = conf.get("cluster_metadata", 0.5)
        if confidence >= config.org_min_confidence:
            key = str(cluster_domain).strip().lower()
            return OrgResolution(key, key, confidence, "cluster_metadata")

    return OrgResolution()


def _alias_for_domain(domain: str, config: NormalizationConfig) -> str:
    for alias in sorted(config.org_aliases):
        spec = config.org_aliases[alias] or {}
        if domain in {str(d).lower() for d in (spec.get("domains") or ())}:
            return alias
    return ""


def _display_for(key: str, config: NormalizationConfig) -> str:
    spec = config.org_aliases.get(key) or {}
    return str(spec.get("display") or "")


# ── Canonical topic identity ────────────────────────────────────────────────

def _entity_slug(org: OrgResolution, title: str) -> str:
    if org.org:
        # postgresql.org -> postgresql, so the entity is the org not the domain.
        return slugify(org.org.split(".")[0], max_words=3) or "unknown"
    return "unknown"


def resolve_release_key(title: str, development_type: str, metadata: dict[str, Any],
                        event_time: dt.datetime | None,
                        config: NormalizationConfig) -> tuple[str, str, bool]:
    """Return (release_key, reason, from_title_fallback)."""
    topic = config.topic

    for key in ("version", "tag_name", "tag", "release"):
        raw = metadata.get(key)
        if raw:
            return str(raw).strip().lstrip("vV"), f"metadata:{key}", False

    model_pattern = topic.get("model_name_pattern")
    if model_pattern and development_type == "model_release":
        match = re.search(model_pattern, title or "", re.I)
        if match:
            return f"{match.group(1).lower()}-{match.group(2).lower()}", "model_name", False

    if development_type not in set(topic.get("month_bucket_types") or ()):
        version_pattern = topic.get("version_pattern")
        if version_pattern:
            match = re.search(version_pattern, title or "", re.I)
            if match:
                return match.group(1), "version_in_title", False

    if event_time is not None:
        return event_time.strftime("%Y-%m"), "month_bucket", False

    slug = slugify(title, max_words=int(topic.get("title_slug_max_words") or 6))
    return (slug or "untitled"), "title_slug", True


def build_canonical_topic_id(entity: str, development_type: str, release_key: str) -> str:
    return f"{entity}:{development_type}:{release_key}"


# ── Time resolution ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TimeResolution:
    selected: dt.datetime | None = None
    source: str = "none"
    reason: str = ""
    alternatives: tuple[dt.datetime, ...] = ()
    warnings: tuple[str, ...] = ()


def resolve_event_time(metadata: dict[str, Any], sources: Iterable[SourceRef],
                       discovered_at: str, config: NormalizationConfig,
                       record_event_time: str = "") -> TimeResolution:
    """Explicit release time > primary source > earliest credible > discovery."""
    sources = list(sources)
    warnings: list[str] = []
    seen: list[dt.datetime] = []

    def collect(raw: Any) -> dt.datetime | None:
        if not raw:
            return None
        parsed = parse_timestamp(raw)
        if parsed is None:
            if WARN_UNPARSEABLE_TIMESTAMP not in warnings:
                warnings.append(WARN_UNPARSEABLE_TIMESTAMP)
            return None
        seen.append(parsed)
        return parsed

    explicit = None
    for key in (config.timestamps.get("explicit_event_keys") or ()):
        explicit = collect(metadata.get(key))
        if explicit is not None:
            explicit_key = key
            break
    if explicit is None and record_event_time:
        explicit = collect(record_event_time)
        explicit_key = "record.event_time"

    primary_time = None
    for ref in sorted((s for s in sources if s.is_primary), key=lambda s: s.url):
        primary_time = collect(ref.published_at)
        if primary_time is not None:
            break

    for ref in sorted(sources, key=lambda s: s.url):
        collect(ref.published_at)
    discovery = collect(discovered_at)

    unique = sorted(set(seen))
    if len(unique) > 1:
        spread = (unique[-1] - unique[0]).total_seconds() / 3600
        tolerance = float(config.timestamps.get("conflict_tolerance_hours", 24))
        if spread > tolerance:
            warnings.append(WARN_CONFLICTING_TIMESTAMPS)

    if explicit is not None:
        selected, source, reason = explicit, "explicit_release", f"explicit {explicit_key}"
    elif primary_time is not None:
        selected, source, reason = primary_time, "primary_source", "primary source publication time"
    else:
        credible = [t for t in unique if discovery is None or t != discovery]
        if credible:
            selected, source, reason = credible[0], "earliest_source", "earliest credible source time"
        elif discovery is not None:
            selected, source = discovery, "discovery"
            reason = "no event or source time; fell back to discovery"
            warnings.append(WARN_EVENT_TIME_FROM_DISCOVERY)
        else:
            warnings.append(WARN_MISSING_EVENT_TIME)
            return TimeResolution(None, "none", "no usable timestamp", (), tuple(warnings))

    alternatives = tuple(t for t in unique if t != selected)
    return TimeResolution(selected, source, reason, alternatives, tuple(warnings))


# ── Claim extraction (deterministic) ────────────────────────────────────────

def extract_claims(title: str, description: str, development_type: str,
                   sources: Iterable[SourceRef], metadata: dict[str, Any],
                   release_key: str, release_reason: str,
                   config: NormalizationConfig) -> tuple[tuple[Claim, ...], list[str]]:
    """Pull claims from structured metadata and known text fields only.

    No LLM, no inference from prose. Where a claim cannot be extracted
    reliably, a warning is returned instead of an invented one.
    """
    sources = list(sources)
    warnings: list[str] = []
    claims: list[Claim] = []
    text_blob = " ".join(filter(None, [title, description]))

    primary = next((s for s in sources if s.is_primary and s.covers_exact_development),
                   next((s for s in sources if s.is_primary), None))
    independent = [s for s in sources if not s.is_first_party and not s.is_syndicated
                   and not s.is_press_release]
    best_source = primary or (sources[0] if sources else None)
    vendor_backed = bool(primary and primary.is_first_party)

    def add(text: str, claim_type: str, *, material: bool, vendor: bool,
            source: SourceRef | None, excerpt: str | None = None) -> None:
        if not text:
            return
        urls = (source.url,) if source and source.url else ()
        traceability = TRACEABLE if (urls or excerpt) else UNTRACEABLE
        if vendor:
            verification = VERIFIED_INDEPENDENT if independent else VERIFIED_VENDOR
        else:
            verification = VERIFIED_INDEPENDENT if independent else VERIFIED_UNKNOWN
        claims.append(Claim(
            text=text,
            material=material,
            source_url=urls[0] if urls else None,
            excerpt=excerpt,
            vendor_claim=vendor,
            claim_id="claim_" + digest(normalize_title(text), claim_type, length=12),
            claim_type=claim_type,
            source_urls=urls,
            traceability=traceability,
            verification=verification,
        ))

    # 1. The headline event fact.
    event_types = config.claims.get("event_claim_types") or {}
    if title:
        add(title, event_types.get(development_type, "event_fact"),
            material=True, vendor=vendor_backed, source=best_source,
            excerpt=(best_source.excerpt if best_source else None) or None)

    # 2. A version fact, when a real version was found (not a title-slug guess).
    if release_key and release_reason.startswith("metadata:"):
        add(f"version {release_key}", "version_fact", material=True,
            vendor=vendor_backed, source=primary or best_source)

    # 3. Explicit structured benchmark fields — the only numbers we trust
    #    without reading prose.
    for name, value in sorted((metadata.get("benchmarks") or {}).items()):
        add(f"{name}: {value}", "benchmark", material=True, vendor=True,
            source=primary or best_source)

    # 4. Numeric patterns in the headline/description. Vendor-provided whenever
    #    the backing evidence is the vendor's own material.
    for pattern in config.claims.get("benchmark_patterns") or ():
        for match in re.findall(pattern, text_blob, re.I):
            add(f"reported figure: {match}", "benchmark", material=True,
                vendor=vendor_backed, source=primary or best_source)
    for pattern in config.claims.get("pricing_patterns") or ():
        for match in re.findall(pattern, text_blob, re.I):
            add(f"reported price: {match}", "pricing", material=True,
                vendor=vendor_backed, source=primary or best_source)

    # Deduplicate by claim_id, preserving order.
    unique: dict[str, Claim] = {}
    for claim in claims:
        unique.setdefault(claim.claim_id, claim)
    ordered = list(unique.values())[: int(config.claims.get("max_claims") or 12)]

    if not ordered:
        warnings.append(WARN_NO_CLAIMS_EXTRACTED)
    return tuple(ordered), warnings


# ── Normalization ───────────────────────────────────────────────────────────

def normalize_candidate(record: Any, *,
                        config: NormalizationConfig | None = None,
                        sources: Iterable[Any] | None = None,
                        discovered_at: str = "",
                        artifact: str | None = None,
                        content_kind: str | None = None,
                        opportunity_score: int | None = None,
                        authority_metadata: dict[str, Any] | None = None,
                        cluster_id: str = "") -> Candidate:
    """Convert one intelligence record into a Candidate.

    Accepts a FeedItem, a StoryCluster, an IntelligenceCard, a repository or
    paper record, a vendor announcement, or a plain mapping. Never mutates the
    record it is given.
    """
    config = _config(config)
    raw = _as_dict(record)
    if not raw:
        raise NormalizationError(REJECT_EMPTY_RECORD, record)

    # Cluster-shaped records carry their members; unwrap them into sources.
    cluster_items = raw.get("items") or []
    cluster_id = cluster_id or str(raw.get("cluster_id") or "")

    title = str(raw.get("title") or raw.get("headline") or raw.get("name") or "").strip()
    url = str(raw.get("url") or raw.get("link") or raw.get("html_url") or "").strip()
    if not title and not url:
        raise NormalizationError(REJECT_NO_IDENTITY, record)

    description = str(raw.get("summary") or raw.get("description")
                      or raw.get("abstract") or raw.get("body") or "")
    feed_source = str(raw.get("source") or "")
    discovered_at = discovered_at or str(raw.get("discovered_at") or "")
    metadata = dict(raw.get("metadata") or {})
    for key in ("version", "tag_name", "owner", "repository_owner", "vendor",
                "organization", "subject_org", "benchmarks", "released_at",
                "release_date", "development_type", "cluster_primary_domain"):
        if key in raw and key not in metadata:
            metadata[key] = raw[key]

    # ── Assemble sources ──
    refs: list[SourceRef] = []
    for entry in (sources or ()):
        ref = (entry if isinstance(entry, SourceRef)
               else _source_from_mapping(_as_dict(entry), discovered_at))
        if ref:
            refs.append(ref)
    for entry in raw.get("sources") or ():
        ref = (entry if isinstance(entry, SourceRef)
               else _source_from_mapping(_as_dict(entry), discovered_at))
        if ref:
            refs.append(ref)
    for entry in cluster_items:
        item = _as_dict(entry)
        ref = _source_from_mapping(
            {**item, "cluster_id": cluster_id,
             "cluster_member_count": len(cluster_items)}, discovered_at)
        if ref:
            refs.append(ref)
    if url and not any(r.url == url for r in refs):
        refs.append(SourceRef(
            url=url,
            kind=str(raw.get("kind") or raw.get("source_kind") or "secondary"),
            title=title,
            published_at=str(raw.get("published_at") or ""),
            excerpt=description[:500],
            discovered_at=discovered_at,
            feed_source=feed_source,
            cluster_id=cluster_id,
        ))
    deduped = dedupe_sources(refs)

    warnings: list[str] = []

    development_type, _type_reason = resolve_development_type(
        title, url, deduped, metadata, config)
    if development_type == "unknown":
        warnings.append(WARN_DEVELOPMENT_TYPE_UNKNOWN)

    org = resolve_subject_org(title, url, deduped, metadata, config)
    if not org.org:
        warnings.append(WARN_SUBJECT_ORG_UNRESOLVED)
    elif org.confidence < 0.8:
        warnings.append(WARN_SUBJECT_ORG_LOW_CONFIDENCE)

    time_res = resolve_event_time(metadata, deduped, discovered_at, config,
                                  record_event_time=str(raw.get("event_time") or
                                                        raw.get("published_at") or ""))
    warnings.extend(time_res.warnings)

    release_key, release_reason, from_title = resolve_release_key(
        title, development_type, metadata, time_res.selected, config)
    if from_title:
        warnings.append(WARN_TOPIC_KEY_FROM_TITLE)

    topic_id = build_canonical_topic_id(
        _entity_slug(org, title), development_type, release_key)

    claims, claim_warnings = extract_claims(
        title, description, development_type, deduped, metadata,
        release_key, release_reason, config)
    warnings.extend(claim_warnings)

    if not any(s.is_primary for s in deduped):
        warnings.append(WARN_NO_PRIMARY_SOURCE)

    # Order-independent, so rediscovery through a different feed is identical.
    fingerprint = digest(*sorted(s.canonical_url for s in deduped), length=24)
    candidate_id = "cand_" + digest(topic_id, fingerprint)

    seen: set[str] = set()
    ordered_warnings = tuple(w for w in warnings if not (w in seen or seen.add(w)))

    return Candidate(
        title=title,
        url=url,
        source=feed_source,
        event_time=time_res.selected.isoformat() if time_res.selected else "",
        discovered_at=discovered_at,
        content_kind=content_kind or _content_kind_for(development_type),
        artifact=artifact,
        subject_org=org.org,
        sources=deduped,
        claims=claims,
        metadata=metadata,
        candidate_id=candidate_id,
        canonical_topic_id=topic_id,
        development_type=development_type,
        subject_name=org.name,
        subject_org_confidence=org.confidence,
        subject_org_resolution_reason=org.reason,
        event_time_source=time_res.source,
        alternative_event_times=tuple(t.isoformat() for t in time_res.alternatives),
        event_time_selection_reason=time_res.reason,
        cluster_id=cluster_id,
        source_fingerprint=fingerprint,
        opportunity_score=_opportunity_from(raw, opportunity_score),
        authority_metadata=dict(authority_metadata or raw.get("authority") or {}),
        warnings=ordered_warnings,
    )


# Which recency profile a development type should be judged on.
_CONTENT_KIND_BY_TYPE = {
    "repository_release": "repository",
    "research_paper": "paper",
    "documentation_update": "tutorial",
}


def _content_kind_for(development_type: str) -> str:
    return _CONTENT_KIND_BY_TYPE.get(development_type, "news")


def _opportunity_from(raw: dict[str, Any], override: int | None) -> int | None:
    if override is not None:
        return int(override)
    opportunity = raw.get("opportunity")
    if isinstance(opportunity, dict) and "opportunity_score" in opportunity:
        return int(opportunity["opportunity_score"])
    for key in ("opportunity_score", "score"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def normalize_many(records: Iterable[Any], **kwargs
                   ) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """Normalize a batch. Returns (candidates, rejections).

    A rejection carries its exact reason; nothing is dropped silently.
    """
    candidates: list[Candidate] = []
    rejections: list[dict[str, Any]] = []
    for record in records:
        try:
            candidates.append(normalize_candidate(record, **kwargs))
        except NormalizationError as exc:
            raw = _as_dict(record)
            rejections.append({
                "reason": exc.reason,
                "title": str(raw.get("title") or ""),
                "url": str(raw.get("url") or ""),
            })
    return candidates, rejections


# ── Orchestration (the only place normalization meets scoring) ──────────────

def normalize_and_score(record: Any, *, config: NormalizationConfig | None = None,
                        scoring_config: Any = None, now: dt.datetime | None = None,
                        **kwargs) -> tuple[Candidate, Any]:
    """Convenience wrapper. Normalization stays independently testable."""
    from .source_confidence import score_source_confidence

    candidate = normalize_candidate(record, config=config, **kwargs)
    return candidate, score_source_confidence(candidate, scoring_config, now=now)
