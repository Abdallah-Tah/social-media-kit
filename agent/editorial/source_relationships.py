"""Deterministic source-relationship and syndication detection (Stage 2.6).

Stage 2 corroboration already honours `is_syndicated`,
`is_press_release_mirror`, and `adds_independent_evidence`. Raw feed records
never supply them, so in production every source looked independent and
corroboration scored higher than the evidence justified. This module derives
those flags from data SMKit already has.

One asymmetry is deliberate and load-bearing, because getting it backwards
would quietly collapse every corroboration score:

    RelationshipResult.adds_independent_evidence is a POSITIVE finding —
    true only when we identified specific new evidence.

    SourceRef.adds_independent_evidence means "not proven to be a bare
    repetition" — it is cleared only when we positively classified the source
    as repeating a vendor statement or mirroring a press release.

A source we cannot read (no excerpt) is therefore `relationship_unknown`: it
earns no positive evidence finding, but it is not excluded from corroboration
either. Absence of evidence is not evidence of syndication.

Purity: no LLM, no network, no scraping, no mutation of the records passed in.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

from .models import (
    FIRST_PARTY_KINDS,
    Candidate,
    SourceRef,
    host_of,
    normalize_title,
    parse_timestamp,
    registrable_domain,
)

KIT = Path(__file__).resolve().parents[2]
CONFIG_PATH = KIT / "config" / "source_relationships.yaml"
SUPPORTED_VERSIONS = (1,)
DETECTION_VERSION = 1

# ── Relationship vocabulary ─────────────────────────────────────────────────

DUPLICATE_CANONICAL_URL = "duplicate_canonical_url"
SAME_ARTICLE_MULTIPLE_FEEDS = "same_article_multiple_feeds"
SYNDICATED_COPY = "syndicated_copy"
PRESS_RELEASE_MIRROR = "press_release_mirror"
SAME_ORGANIZATION = "same_organization"
FIRST_PARTY_REPETITION = "first_party_repetition"
REPEATS_VENDOR_STATEMENT = "repeats_vendor_statement_without_evidence"
INDEPENDENT_REPORTING = "independent_reporting"
ADDS_INDEPENDENT_EVIDENCE = "adds_independent_evidence"
RELATIONSHIP_UNKNOWN = "relationship_unknown"

RELATIONSHIPS = (
    DUPLICATE_CANONICAL_URL,
    SAME_ARTICLE_MULTIPLE_FEEDS,
    SYNDICATED_COPY,
    PRESS_RELEASE_MIRROR,
    SAME_ORGANIZATION,
    FIRST_PARTY_REPETITION,
    REPEATS_VENDOR_STATEMENT,
    INDEPENDENT_REPORTING,
    ADDS_INDEPENDENT_EVIDENCE,
    RELATIONSHIP_UNKNOWN,
)

# Classifications that mean "this is not a second opinion". Only these clear
# SourceRef.adds_independent_evidence.
_NON_CORROBORATING = frozenset({PRESS_RELEASE_MIRROR, REPEATS_VENDOR_STATEMENT})

_SHINGLE_SIZE = 4


class RelationshipConfigError(ValueError):
    """Reports every problem in config/source_relationships.yaml at once."""

    def __init__(self, problems: list[str], path: Path | None = None):
        self.problems = list(problems)
        self.path = path
        joined = "\n  - ".join(self.problems)
        super().__init__(
            f"{len(self.problems)} problem(s)"
            f"{f' in {path}' if path else ''}:\n  - {joined}")


# ── Configuration ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RelationshipConfig:
    version: int
    organization_groups: dict[str, tuple[str, ...]]
    organization_aliases: dict[str, tuple[str, ...]]
    press_release_domains: frozenset[str]
    syndication_domains: frozenset[str]
    syndication_metadata_keys: tuple[str, ...]
    similarity: dict[str, Any]
    ordering_tolerance: dt.timedelta
    evidence_markers: dict[str, tuple[re.Pattern, ...]]
    commentary_markers: tuple[re.Pattern, ...]
    min_markers: int
    confidence: dict[str, float]
    path: Path | None = None


def _compile(patterns: Any, label: str, problems: list[str]) -> tuple[re.Pattern, ...]:
    out = []
    for raw in patterns or ():
        try:
            out.append(re.compile(raw, re.I))
        except re.error as exc:
            problems.append(f"{label}: invalid regex {raw!r} ({exc})")
    return tuple(out)


def load_relationship_config(path: Path | str | None = None) -> RelationshipConfig:
    """Parse and fully validate. Fails closed: never partially loads."""
    from agent.config import _read_yaml

    target = Path(path) if path else CONFIG_PATH
    problems: list[str] = []

    if not target.exists():
        raise RelationshipConfigError([f"config file not found: {target}"], target)
    data = _read_yaml(target)
    if not isinstance(data, dict) or not data:
        raise RelationshipConfigError(["file is empty or not a YAML mapping"], target)

    if data.get("version") not in SUPPORTED_VERSIONS:
        problems.append(f"unsupported version {data.get('version')!r}")

    groups: dict[str, tuple[str, ...]] = {}
    raw_groups = data.get("organization_groups") or {}
    if not isinstance(raw_groups, dict):
        problems.append("organization_groups must be a mapping")
        raw_groups = {}
    for name, spec in raw_groups.items():
        members = (spec or {}).get("members") if isinstance(spec, dict) else None
        if not members:
            problems.append(f"organization_groups[{name!r}] needs at least one member")
            continue
        groups[str(name)] = tuple(str(m).strip().lower() for m in members)

    aliases: dict[str, tuple[str, ...]] = {}
    raw_aliases = data.get("organization_aliases") or {}
    if not isinstance(raw_aliases, dict):
        problems.append("organization_aliases must be a mapping")
        raw_aliases = {}
    for name, spec in raw_aliases.items():
        domains = (spec or {}).get("domains") if isinstance(spec, dict) else None
        if not domains:
            problems.append(f"organization_aliases[{name!r}] needs at least one domain")
            continue
        aliases[str(name)] = tuple(str(d).strip().lower() for d in domains)

    similarity = data.get("similarity") or {}
    if not isinstance(similarity, dict):
        problems.append("similarity must be a mapping")
        similarity = {}
    for key in ("syndication_min_body", "repetition_min_body"):
        value = similarity.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) \
                or not 0 < value <= 1:
            problems.append(f"similarity.{key} must be a number in (0, 1]")
    syn = similarity.get("syndication_min_body")
    rep = similarity.get("repetition_min_body")
    if isinstance(syn, (int, float)) and isinstance(rep, (int, float)) and syn < rep:
        problems.append(
            f"similarity.syndication_min_body ({syn}) must be >= "
            f"repetition_min_body ({rep}); a syndicated copy is a stronger "
            f"claim than a restatement")
    if similarity.get("title_only_is_never_sufficient") is not True:
        problems.append(
            "similarity.title_only_is_never_sufficient must be true; matching "
            "titles alone never establish a relationship")
    min_tokens = similarity.get("min_comparable_tokens", 8)
    if not isinstance(min_tokens, int) or isinstance(min_tokens, bool) or min_tokens < 1:
        problems.append("similarity.min_comparable_tokens must be a positive integer")
        min_tokens = 8

    ordering = data.get("publication_ordering") or {}
    tolerance = ordering.get("tolerance_minutes", 5)
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) \
            or tolerance < 0:
        problems.append("publication_ordering.tolerance_minutes must be >= 0")
        tolerance = 5

    evidence = data.get("evidence") or {}
    if not isinstance(evidence, dict):
        problems.append("evidence must be a mapping")
        evidence = {}
    markers: dict[str, tuple[re.Pattern, ...]] = {}
    raw_markers = evidence.get("markers") or {}
    if not isinstance(raw_markers, dict) or not raw_markers:
        problems.append("evidence.markers must be a non-empty mapping")
        raw_markers = {}
    for name, patterns in raw_markers.items():
        compiled = _compile(patterns, f"evidence.markers[{name!r}]", problems)
        if not compiled:
            problems.append(f"evidence.markers[{name!r}] has no usable patterns")
        markers[str(name)] = compiled
    commentary = _compile(evidence.get("commentary_markers"),
                          "evidence.commentary_markers", problems)
    min_markers = evidence.get("min_markers", 1)
    if not isinstance(min_markers, int) or isinstance(min_markers, bool) or min_markers < 1:
        problems.append("evidence.min_markers must be a positive integer")
        min_markers = 1

    confidence = data.get("confidence") or {}
    if not isinstance(confidence, dict):
        problems.append("confidence must be a mapping")
        confidence = {}
    unknown = sorted(set(confidence) - set(RELATIONSHIPS))
    if unknown:
        problems.append(f"confidence: unknown relationship(s): {', '.join(unknown)}")
    missing = sorted(set(RELATIONSHIPS) - set(confidence))
    if missing:
        problems.append(f"confidence: missing relationship(s): {', '.join(missing)}")
    for name, value in confidence.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) \
                or not 0 <= value <= 1:
            problems.append(f"confidence[{name!r}] must be within 0-1")

    press = frozenset(str(d).strip().lower()
                      for d in (data.get("press_release_domains") or ()))
    syndication = frozenset(str(d).strip().lower()
                            for d in (data.get("syndication_domains") or ()))
    overlap = press & syndication
    if overlap:
        problems.append(
            f"a domain cannot be both a press-release and a syndication "
            f"network: {', '.join(sorted(overlap))}")

    if problems:
        raise RelationshipConfigError(problems, target)

    return RelationshipConfig(
        version=int(data["version"]),
        organization_groups=groups,
        organization_aliases=aliases,
        press_release_domains=press,
        syndication_domains=syndication,
        syndication_metadata_keys=tuple(data.get("syndication_metadata_keys") or ()),
        similarity={**similarity, "min_comparable_tokens": min_tokens},
        ordering_tolerance=dt.timedelta(minutes=float(tolerance)),
        evidence_markers=markers,
        commentary_markers=commentary,
        min_markers=int(min_markers),
        confidence={k: float(v) for k, v in confidence.items()},
        path=target,
    )


_CACHED: RelationshipConfig | None = None


def _config(config: RelationshipConfig | None) -> RelationshipConfig:
    global _CACHED
    if config is not None:
        return config
    if _CACHED is None:
        _CACHED = load_relationship_config()
    return _CACHED


# ── Text comparison ─────────────────────────────────────────────────────────

def _tokens(text: str) -> list[str]:
    return normalize_title(text).split()


def _shingles(tokens: Sequence[str], size: int = _SHINGLE_SIZE) -> set[tuple[str, ...]]:
    if len(tokens) < size:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i:i + size]) for i in range(len(tokens) - size + 1)}


def text_similarity(a: str, b: str) -> float:
    """Jaccard over 4-token shingles. Deterministic and symmetric."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    sa, sb = _shingles(ta), _shingles(tb)
    if not sa or not sb:
        return 0.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def _body(ref: SourceRef) -> str:
    return (ref.excerpt or "").strip()


def _comparable(ref: SourceRef, config: RelationshipConfig) -> bool:
    """Enough text to compare? Without this, everything looks 0% similar."""
    return len(_tokens(_body(ref))) >= int(config.similarity["min_comparable_tokens"])


# ── Organization identity ───────────────────────────────────────────────────

def resolve_organization(ref: SourceRef, config: RelationshipConfig) -> str:
    """Collapse subdomains, configured groups, and aliases to one identity.

    Ownership is never inferred from domain similarity: vendor.com and
    vendor-news.com stay separate unless a group declares otherwise.
    """
    if ref.organization_id:
        return ref.organization_id.strip().lower()

    parsed = urlparse(ref.url or "")
    host = host_of(ref.url)
    first_segment = (parsed.path or "").strip("/").split("/")[0].lower()
    path_identity = f"{host}/{first_segment}" if first_segment else ""
    domain = registrable_domain(ref.url)

    for group, members in sorted(config.organization_groups.items()):
        if path_identity and path_identity in members:
            return group
        if domain and domain in members:
            return group
        if host and host in members:
            return group

    for alias, domains in sorted(config.organization_aliases.items()):
        if domain in domains or host in domains:
            return alias

    if ref.publisher:
        return ref.publisher.strip().lower()
    return domain


# ── Evidence detection ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class EvidenceFinding:
    kinds: tuple[str, ...] = ()
    commentary_only: bool = False
    readable: bool = False

    @property
    def has_evidence(self) -> bool:
        return bool(self.kinds)


def detect_evidence(ref: SourceRef, config: RelationshipConfig) -> EvidenceFinding:
    """Find markers of evidence the primary source does not already contain.

    Commentary is explicitly not evidence. An article that says "what this
    means for developers" has added an opinion, not a measurement.
    """
    text = _body(ref)
    if not text:
        return EvidenceFinding(readable=False)

    kinds = sorted(
        name for name, patterns in config.evidence_markers.items()
        if any(p.search(text) for p in patterns)
    )
    if len(kinds) < config.min_markers:
        kinds = []
    commentary = any(p.search(text) for p in config.commentary_markers)
    return EvidenceFinding(kinds=tuple(kinds),
                           commentary_only=bool(commentary and not kinds),
                           readable=True)


# ── Relationship result ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceRelationship:
    source_id: str
    relationship: str
    confidence: float
    reasons: tuple[str, ...] = ()
    origin_source_id: str | None = None
    adds_independent_evidence: bool = False
    evidence_kinds: tuple[str, ...] = ()
    organization_id: str = ""
    discovery_paths: tuple[str, ...] = ()
    version: int = DETECTION_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "origin_source_id": self.origin_source_id,
            "relationship": self.relationship,
            "confidence": round(self.confidence, 2),
            "reasons": list(self.reasons),
            "adds_independent_evidence": self.adds_independent_evidence,
            "evidence_kinds": list(self.evidence_kinds),
            "organization_id": self.organization_id,
            "discovery_paths": list(self.discovery_paths),
            "version": self.version,
        }


# ── Detection ───────────────────────────────────────────────────────────────

def _sort_key(ref: SourceRef) -> tuple:
    """Deterministic ordering: earliest first, primary before secondary.

    Every decision below iterates in this order, so the classification cannot
    depend on the order sources happened to arrive in.
    """
    stamp = parse_timestamp(ref.published_at)
    return (
        stamp or dt.datetime.max.replace(tzinfo=dt.timezone.utc),
        0 if ref.is_primary else 1,
        ref.canonical_url or ref.url.lower(),
    )


def detect_relationships(sources: Iterable[SourceRef], *,
                         subject_org: str = "",
                         config: RelationshipConfig | None = None,
                         metadata: dict[str, Any] | None = None,
                         ) -> list[SourceRelationship]:
    """Classify every source against the group it belongs to.

    Returns one result per input source, in the input order, so callers can zip
    results back onto their own list.
    """
    config = _config(config)
    metadata = metadata or {}
    refs = list(sources)
    ordered = sorted(refs, key=_sort_key)
    subject = (subject_org or "").strip().lower()

    orgs = {r.source_id: resolve_organization(r, config) for r in refs}
    evidence = {r.source_id: detect_evidence(r, config) for r in refs}
    stamps = {r.source_id: parse_timestamp(r.published_at) for r in refs}

    # Discovery paths: the same canonical URL reached through several feeds.
    paths: dict[str, list[str]] = {}
    for ref in ordered:
        key = ref.canonical_url or ref.url.lower()
        if ref.feed_source:
            paths.setdefault(key, [])
            if ref.feed_source not in paths[key]:
                paths[key].append(ref.feed_source)

    seen_urls: dict[str, SourceRef] = {}
    seen_fingerprints: dict[str, SourceRef] = {}
    counted_orgs: dict[str, SourceRef] = {}
    # Keyed by position in the caller's list, not by source_id: two records
    # with the same canonical URL share a source_id, and keying by it made the
    # later duplicate overwrite the origin's own classification.
    results: dict[int, SourceRelationship] = {}
    positions = {id(r): i for i, r in enumerate(refs)}
    current_index = 0

    def emit(ref: SourceRef, relationship: str, reasons: list[str],
             origin: SourceRef | None = None, adds: bool = False,
             kinds: tuple[str, ...] = ()) -> None:
        results[current_index] = SourceRelationship(
            source_id=ref.source_id,
            relationship=relationship,
            confidence=config.confidence.get(relationship, 0.0),
            reasons=tuple(reasons),
            origin_source_id=origin.source_id if origin else None,
            adds_independent_evidence=adds,
            evidence_kinds=kinds,
            organization_id=orgs[ref.source_id],
            discovery_paths=tuple(paths.get(ref.canonical_url or ref.url.lower(), ())),
        )

    for ref in ordered:
        current_index = positions[id(ref)]
        sid = ref.source_id
        org = orgs[sid]
        url_key = ref.canonical_url or ref.url.lower()
        fingerprint = ref.content_fingerprint
        found = evidence[sid]
        stamp = stamps[sid]

        # 1. Same canonical URL as something already seen.
        prior = seen_urls.get(url_key)
        if prior is not None:
            discovery = paths.get(url_key, [])
            if ref.feed_source and prior.feed_source and \
                    ref.feed_source != prior.feed_source:
                emit(ref, SAME_ARTICLE_MULTIPLE_FEEDS,
                     ["matching_canonical_url",
                      f"discovered_via_{ref.feed_source}_and_{prior.feed_source}"],
                     origin=prior)
            else:
                emit(ref, DUPLICATE_CANONICAL_URL, ["matching_canonical_url"],
                     origin=prior)
            continue
        seen_urls[url_key] = ref

        # 2. Identical body reached by a different URL — same article, different
        #    front door. Only counts when there was enough text to compare.
        twin = seen_fingerprints.get(fingerprint) if fingerprint else None
        if (twin is not None and _comparable(ref, config)
                and orgs[twin.source_id] == org):
            # Same publisher, same body, different URL — one article reached by
            # two front doors. A matching body from a DIFFERENT organization is
            # syndication or a press-release mirror, and is classified below.
            emit(ref, SAME_ARTICLE_MULTIPLE_FEEDS,
                 ["matching_content_fingerprint", "same_organization"], origin=twin)
            continue
        upstream_id = (ref.evidence_reference or "").strip()
        if upstream_id:
            match = next((s for s in ordered
                          if s.source_id != sid
                          and (s.evidence_reference or "").strip() == upstream_id
                          and positions[id(s)] in results
                          and orgs[s.source_id] == org), None)
            if match is not None:
                emit(ref, SAME_ARTICLE_MULTIPLE_FEEDS,
                     ["matching_upstream_identifier"], origin=match)
                continue
        if fingerprint:
            seen_fingerprints.setdefault(fingerprint, ref)

        # 3. First-party material: the subject talking about itself.
        if ref.kind in FIRST_PARTY_KINDS or (subject and org == subject):
            reasons = (["first_party_source_kind"] if ref.kind in FIRST_PARTY_KINDS
                       else ["organization_matches_subject"])
            if org in counted_orgs:
                emit(ref, FIRST_PARTY_REPETITION,
                     reasons + ["organization_already_represented"],
                     origin=counted_orgs[org])
            else:
                counted_orgs[org] = ref
                emit(ref, FIRST_PARTY_REPETITION, reasons)
            continue

        # 4. Press-release distribution networks and explicit press-release flags.
        domain = registrable_domain(ref.url)
        if domain in config.press_release_domains or ref.is_press_release:
            reasons = ["known_press_release_domain"] if \
                domain in config.press_release_domains else ["declared_press_release"]
            emit(ref, PRESS_RELEASE_MIRROR, reasons)
            continue

        # 5. Explicit syndication metadata beats any inference.
        declared = ref.syndicated_from or next(
            (metadata[k] for k in config.syndication_metadata_keys
             if metadata.get(k)), None)
        if declared:
            emit(ref, SYNDICATED_COPY,
                 ["explicit_syndication_metadata", f"attributed_to_{declared}"])
            continue
        if domain in config.syndication_domains:
            emit(ref, SYNDICATED_COPY, ["known_syndication_network"])
            continue

        # 6. Near-identical body published after an identifiable origin.
        #    Similar titles alone are deliberately never enough here.
        if _comparable(ref, config):
            origin = _syndication_origin(ref, ordered, orgs, stamps, config)
            if origin is not None:
                emit(ref, SYNDICATED_COPY,
                     ["matching_content_fingerprint", "published_after_origin"],
                     origin=origin)
                continue

        # 7. Same organization as a source already counted.
        if org and org in counted_orgs:
            emit(ref, SAME_ORGANIZATION,
                 ["organization_already_counted", f"organization_{org}"],
                 origin=counted_orgs[org])
            continue

        # 8. Positive evidence -> independent. Commentary is not evidence.
        if found.has_evidence:
            counted_orgs[org] = ref
            emit(ref, ADDS_INDEPENDENT_EVIDENCE,
                 ["evidence_markers_found"] + [f"evidence_{k}" for k in found.kinds],
                 adds=True, kinds=found.kinds)
            continue

        # 9. Readable, substantially restates the origin, and adds nothing.
        if found.readable and _comparable(ref, config):
            origin = _restatement_origin(ref, ordered, orgs, config)
            if origin is not None:
                reasons = ["restates_origin_without_new_evidence"]
                if found.commentary_only:
                    reasons.append("commentary_only")
                emit(ref, REPEATS_VENDOR_STATEMENT, reasons, origin=origin)
                continue
            counted_orgs[org] = ref
            emit(ref, INDEPENDENT_REPORTING,
                 ["different_organization", "not_syndicated_or_mirrored",
                  "no_substantial_overlap_with_origin"])
            continue

        # 10. Not enough to go on. Explicitly unknown — never guessed, and never
        #     excluded from corroboration on the strength of silence.
        counted_orgs.setdefault(org, ref)
        emit(ref, RELATIONSHIP_UNKNOWN,
             ["insufficient_content_to_classify"]
             + ([] if found.readable else ["no_source_excerpt"]))

    return [results[i] for i in range(len(refs))]


def _syndication_origin(ref: SourceRef, ordered: list[SourceRef],
                        orgs: dict[str, str], stamps: dict[str, Any],
                        config: RelationshipConfig) -> SourceRef | None:
    """An earlier, different-organization source with a near-identical body."""
    threshold = float(config.similarity["syndication_min_body"])
    stamp = stamps[ref.source_id]
    for other in ordered:
        if other.source_id == ref.source_id:
            continue
        if orgs[other.source_id] == orgs[ref.source_id]:
            continue
        if not _comparable(other, config):
            continue
        other_stamp = stamps[other.source_id]
        if stamp is None or other_stamp is None:
            continue
        if stamp - other_stamp < config.ordering_tolerance:
            continue
        if text_similarity(_body(ref), _body(other)) >= threshold:
            return other
    return None


def _restatement_origin(ref: SourceRef, ordered: list[SourceRef],
                        orgs: dict[str, str],
                        config: RelationshipConfig) -> SourceRef | None:
    """A first-party/primary source whose content this one substantially repeats."""
    threshold = float(config.similarity["repetition_min_body"])
    for other in ordered:
        if other.source_id == ref.source_id:
            continue
        if not (other.is_first_party or other.is_primary):
            continue
        if not _comparable(other, config):
            continue
        if text_similarity(_body(ref), _body(other)) >= threshold:
            return other
    return None


# ── Enrichment ──────────────────────────────────────────────────────────────

def apply_relationships(candidate: Candidate,
                        relationships: Sequence[SourceRelationship]) -> Candidate:
    """Return a NEW Candidate with detector findings folded into its sources.

    Nothing is mutated: SourceRef and Candidate are frozen, so this builds
    replacements. The raw feed records the candidate was normalized from are
    never touched.

    Only a positive non-corroborating classification clears
    `adds_independent_evidence`. `relationship_unknown` leaves the flag alone —
    absence of evidence is not evidence of syndication.
    """
    by_id = {r.source_id: r for r in relationships}
    updated: list[SourceRef] = []

    for ref in candidate.sources:
        result = by_id.get(ref.source_id)
        if result is None:
            updated.append(ref)
            continue

        syndicated_from = ref.syndicated_from
        if result.relationship == SYNDICATED_COPY and not syndicated_from:
            syndicated_from = result.origin_source_id or "detected"

        updated.append(replace(
            ref,
            syndicated_from=syndicated_from,
            is_press_release=(ref.is_press_release
                              or result.relationship == PRESS_RELEASE_MIRROR),
            adds_independent_evidence=(
                False if result.relationship in _NON_CORROBORATING
                else ref.adds_independent_evidence),
            organization_id=ref.organization_id or result.organization_id,
        ))

    return replace(candidate, sources=tuple(updated))


# ── Orchestration ───────────────────────────────────────────────────────────

def analyze_candidate(record: Any, *,
                      normalization_config: Any = None,
                      relationship_config: RelationshipConfig | None = None,
                      scoring_config: Any = None,
                      now: dt.datetime | None = None,
                      **kwargs) -> tuple[Candidate, list[SourceRelationship], Any]:
    """Normalize -> detect relationships -> rescore.

    The three steps stay independently testable; this only wires them together.
    """
    from .candidate_adapter import normalize_candidate
    from .source_confidence import score_source_confidence

    candidate = normalize_candidate(record, config=normalization_config, **kwargs)
    relationships = detect_relationships(
        candidate.sources, subject_org=candidate.subject_org,
        config=relationship_config, metadata=candidate.metadata)
    enriched = apply_relationships(candidate, relationships)
    confidence = score_source_confidence(enriched, scoring_config, now=now)
    return enriched, relationships, confidence
