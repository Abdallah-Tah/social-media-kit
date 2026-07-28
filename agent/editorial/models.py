"""Shared editorial data model (Phase 1, Stage 2.5).

One model, not two. Stage 2 defined SourceRef / Claim / Candidate inside the
scorer; Stage 2.5 needs richer versions for the adapter. Rather than introduce a
parallel structure, those dataclasses moved here and were extended, so the
scorer and the adapter agree by construction.

Direction of dependency is deliberate and one-way:

    models.py  <--  source_confidence.py   (scores a Candidate)
        ^
        |--------  candidate_adapter.py    (builds a Candidate)

The scorer never imports the adapter, so it stays independently testable.

Derived facts (canonical url, registrable domain, syndication, first-party) are
exposed as properties rather than stored fields. Storing them would let them
drift out of sync with the values they are derived from.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

NORMALIZATION_VERSION = 1
SCHEMA_VERSION = 1

# ── Source kinds ────────────────────────────────────────────────────────────

PRIMARY_KINDS = frozenset({
    "official_announcement",
    "official_documentation",
    "release_notes",
    "repository",
    "repository_release",
    "research_paper",
    "standards_publication",
    "government_publication",
    "security_advisory",
})

# Primary kinds that are, by definition, the subject's OWN material. These are
# evidence, never a second opinion, so they can never count toward independent
# corroboration. The remaining primary kinds are excluded on purpose: a paper,
# a standards publication, a government filing, or an advisory from a body
# other than the affected vendor CAN be genuine independent corroboration.
FIRST_PARTY_KINDS = frozenset({
    "official_announcement",
    "official_documentation",
    "release_notes",
    "repository",
    "repository_release",
})

# ── Development types ───────────────────────────────────────────────────────

DEVELOPMENT_TYPES = (
    "model_release",
    "product_release",
    "api_release",
    "repository_release",
    "research_paper",
    "benchmark",
    "pricing_change",
    "security_issue",
    "licensing_change",
    "documentation_update",
    "deployment_availability",
    "compatibility_change",
    "funding_or_company_news",
    "general_news",
    "unknown",
)

# ── Claim vocabulary ────────────────────────────────────────────────────────

CLAIM_TYPES = (
    "event_fact",        # the thing happened
    "version_fact",      # a specific version/tag exists
    "capability",        # it can now do X
    "benchmark",         # a number about performance
    "pricing",
    "availability",
    "security",
    "licensing",
    "unclassified",
)

TRACEABLE = "traceable"
UNTRACEABLE = "untraceable"
TRACE_UNASSESSED = "unassessed"

VERIFIED_INDEPENDENT = "independently_established"
VERIFIED_VENDOR = "vendor_provided"
VERIFIED_UNKNOWN = "unverified"

# ── Warnings ────────────────────────────────────────────────────────────────

WARN_MISSING_EVENT_TIME = "missing_event_time"
WARN_FUTURE_TIMESTAMP = "future_timestamp"
WARN_CONFLICTING_TIMESTAMPS = "conflicting_source_timestamps"
WARN_UNPARSEABLE_TIMESTAMP = "unparseable_timestamp"
WARN_UNVERIFIED_VENDOR_CLAIM = "unverified_vendor_claim"
WARN_NO_MATERIAL_CLAIMS = "no_material_claims"
WARN_EVENT_TIME_FROM_DISCOVERY = "event_time_fell_back_to_discovery"
WARN_SUBJECT_ORG_UNRESOLVED = "subject_org_unresolved"
WARN_SUBJECT_ORG_LOW_CONFIDENCE = "subject_org_low_confidence"
WARN_DEVELOPMENT_TYPE_UNKNOWN = "development_type_unknown"
WARN_NO_CLAIMS_EXTRACTED = "no_claims_extracted"
WARN_NO_PRIMARY_SOURCE = "no_primary_source"
WARN_TOPIC_KEY_FROM_TITLE = "topic_release_key_from_title"

# Multi-label public suffixes, so bbc.co.uk and news.bbc.co.uk collapse to one
# organization instead of reading as two independent sources.
_TWO_LABEL_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "co.jp", "or.jp", "ne.jp",
    "com.au", "net.au", "org.au", "co.nz", "com.br", "co.in", "co.za",
    "com.cn", "com.sg", "com.hk", "co.kr",
})

_WORD_RE = re.compile(r"[a-z0-9]+")


# ── Shared helpers ──────────────────────────────────────────────────────────

def registrable_domain(url: str) -> str:
    """Collapse subdomains so one organization reads as one organization."""
    host = (urlparse(url or "").netloc or "").lower().split(":")[0]
    host = host.removeprefix("www.")
    if not host:
        return ""
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def host_of(url: str) -> str:
    return (urlparse(url or "").netloc or "").lower().split(":")[0].removeprefix("www.")


def canonical(url: str) -> str:
    """Tracking-stripped, trailing-slash-normalized URL used as an identity key."""
    from agent.feed import canonical_url

    return canonical_url(url or "").rstrip("/").lower()


def parse_timestamp(raw: Any) -> dt.datetime | None:
    """Parse to an aware UTC datetime, or None. Naive input is assumed UTC."""
    if not raw:
        return None
    if isinstance(raw, dt.datetime):
        parsed = raw
    else:
        text = str(raw).strip().replace("Z", "+00:00")
        try:
            parsed = dt.datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def normalize_title(title: str) -> str:
    """Lowercased alphanumeric words, for stable comparison and slugging."""
    return " ".join(_WORD_RE.findall((title or "").lower()))


def slugify(text: str, max_words: int = 6) -> str:
    words = _WORD_RE.findall((text or "").lower())
    return "-".join(words[:max_words])


def digest(*parts: str, length: int = 16) -> str:
    joined = "|".join(p or "" for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


# ── SourceRef ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceRef:
    """One piece of evidence behind a candidate.

    `kind` keeps its Stage 2 name as the constructor argument; `source_kind` is
    the serialized name and is exposed as a property so both vocabularies work.
    """
    url: str
    kind: str = "secondary"
    title: str = ""
    published_at: str = ""
    publisher: str = ""              # explicit org identity; beats domain guessing
    covers_exact_development: bool = False
    links_to_primary: bool = False
    syndicated_from: str | None = None
    is_press_release: bool = False
    adds_independent_evidence: bool = True
    excerpt: str = ""
    # Stage 2.5 additions
    discovered_at: str = ""
    organization_id: str = ""
    cluster_id: str = ""
    cluster_member_count: int = 0
    evidence_reference: str = ""
    feed_source: str = ""            # which collector found it (hackernews, ...)

    # ── derived ──
    @property
    def source_kind(self) -> str:
        return self.kind

    @property
    def is_primary(self) -> bool:
        return self.kind in PRIMARY_KINDS

    @property
    def is_first_party(self) -> bool:
        return self.kind in FIRST_PARTY_KINDS

    @property
    def is_syndicated(self) -> bool:
        return bool(self.syndicated_from)

    @property
    def is_press_release_mirror(self) -> bool:
        return bool(self.is_press_release)

    @property
    def repeated_vendor_statement(self) -> bool:
        return not self.adds_independent_evidence

    @property
    def canonical_url(self) -> str:
        return canonical(self.url)

    @property
    def domain(self) -> str:
        return host_of(self.url)

    @property
    def registrable_domain(self) -> str:
        return registrable_domain(self.url)

    @property
    def publication_time(self) -> str:
        return self.published_at

    def organization(self) -> str:
        """Explicit organization_id, then publisher, then registrable domain."""
        return ((self.organization_id or "").strip().lower()
                or (self.publisher or "").strip().lower()
                or self.registrable_domain)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "canonical_url": self.canonical_url,
            "domain": self.domain,
            "registrable_domain": self.registrable_domain,
            "organization_id": self.organization(),
            "source_kind": self.source_kind,
            "publication_time": self.publication_time,
            "discovered_at": self.discovered_at,
            "title": self.title,
            "is_primary": self.is_primary,
            "is_first_party": self.is_first_party,
            "is_syndicated": self.is_syndicated,
            "is_press_release_mirror": self.is_press_release_mirror,
            "repeated_vendor_statement": self.repeated_vendor_statement,
            "cluster_evidence": {
                "cluster_id": self.cluster_id,
                "member_count": self.cluster_member_count,
                "feed_source": self.feed_source,
            },
            "excerpt": self.excerpt,
            "evidence_reference": self.evidence_reference,
        }


# ── Claim ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Claim:
    """A statement the candidate makes, and where it came from."""
    text: str
    material: bool = True
    source_url: str | None = None
    excerpt: str | None = None
    vendor_claim: bool = False
    # Stage 2.5 additions
    claim_id: str = ""
    claim_type: str = "unclassified"
    source_urls: tuple[str, ...] = ()
    traceability: str = TRACE_UNASSESSED
    verification: str = VERIFIED_UNKNOWN
    warnings: tuple[str, ...] = ()

    @property
    def normalized_text(self) -> str:
        return normalize_title(self.text)

    def all_source_urls(self) -> tuple[str, ...]:
        urls = list(self.source_urls)
        if self.source_url and self.source_url not in urls:
            urls.insert(0, self.source_url)
        return tuple(urls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "normalized_text": self.normalized_text,
            "claim_type": self.claim_type,
            "material": self.material,
            "vendor_provided": self.vendor_claim,
            "verification": self.verification,
            "traceability": self.traceability,
            "source_references": list(self.all_source_urls()),
            "excerpt": self.excerpt,
            "warnings": list(self.warnings),
        }


# ── Candidate ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Candidate:
    """Everything the scorer is allowed to look at. No I/O happens from here."""
    title: str = ""
    url: str = ""
    source: str = ""
    event_time: str = ""             # actual event / publication time
    discovered_at: str = ""          # ingestion time — never used for recency
    content_kind: str = "news"       # selects the recency profile
    artifact: str | None = None      # once-weekly artifact name, if any
    subject_org: str = ""
    sources: tuple[SourceRef, ...] = ()
    claims: tuple[Claim, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    # ── Stage 2.5 additions ──
    candidate_id: str = ""
    canonical_topic_id: str = ""
    development_type: str = "unknown"
    subject_name: str = ""
    subject_org_confidence: float = 0.0
    subject_org_resolution_reason: str = "unresolved"
    event_time_source: str = "none"
    alternative_event_times: tuple[str, ...] = ()
    event_time_selection_reason: str = ""
    cluster_id: str = ""
    source_fingerprint: str = ""
    opportunity_score: int | None = None
    authority_metadata: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    normalization_version: int = NORMALIZATION_VERSION

    # ── derived ──
    @property
    def artifact_type(self) -> str:
        """Serialized name for content_kind, which selects the recency profile."""
        return self.content_kind

    @property
    def normalized_title(self) -> str:
        return normalize_title(self.title)

    @property
    def canonical_url(self) -> str:
        return canonical(self.url)

    @property
    def primary_source(self) -> SourceRef | None:
        """Best primary evidence: exact-development first, then any primary."""
        exact = [s for s in self.sources if s.is_primary and s.covers_exact_development]
        if exact:
            return exact[0]
        primaries = [s for s in self.sources if s.is_primary]
        return primaries[0] if primaries else None

    def to_dict(self) -> dict[str, Any]:
        primary = self.primary_source
        return {
            "candidate_id": self.candidate_id,
            "canonical_topic_id": self.canonical_topic_id,
            "title": self.title,
            "normalized_title": self.normalized_title,
            "development_type": self.development_type,
            "artifact_type": self.artifact_type,
            "subject_name": self.subject_name,
            "subject_org": self.subject_org,
            "subject_org_confidence": round(self.subject_org_confidence, 2),
            "subject_org_resolution_reason": self.subject_org_resolution_reason,
            "event_time": self.event_time,
            "event_time_source": self.event_time_source,
            "event_time_selection_reason": self.event_time_selection_reason,
            "alternative_event_times": list(self.alternative_event_times),
            "discovered_at": self.discovered_at,
            "primary_source": primary.to_dict() if primary else None,
            "sources": [s.to_dict() for s in self.sources],
            "claims": [c.to_dict() for c in self.claims],
            "cluster_id": self.cluster_id,
            "canonical_url": self.canonical_url,
            "source_fingerprint": self.source_fingerprint,
            "opportunity_score": self.opportunity_score,
            "authority_metadata": dict(self.authority_metadata),
            "warnings": list(self.warnings),
            "normalization_version": self.normalization_version,
        }


class NormalizationError(ValueError):
    """A record that cannot be turned into a Candidate at all.

    Only structurally unusable input reaches this — missing optional metadata
    produces warnings, never a rejection.
    """

    def __init__(self, reason: str, record: Any = None):
        self.reason = reason
        self.record = record
        super().__init__(reason)
