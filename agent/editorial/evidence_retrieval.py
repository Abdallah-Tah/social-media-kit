"""Stage 7C.7 — bounded evidence retrieval for highest-ranked candidates.

Fetches primary and corroborating evidence for top candidates, then re-runs
enrichment with the fetched content. No publishing, no notifications.

Evidence sources:
- Official announcement
- Official documentation
- Release notes
- GitHub repository or release
- Research paper or abstract
- Security advisory
- Pricing page
- Independent technical coverage

Constraints:
- Bounded candidate count (default: 10)
- Bounded URLs per candidate (default: 5)
- Timeouts (default: 10s)
- Domain allow/deny rules
- Cache with TTL (default: 30 days)
- Content-size limits (default: 500KB)
- No unrestricted crawling
- No duplicate fetches
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .enrichment import enrich_candidate
from .models import registrable_domain

KIT = Path(__file__).resolve().parents[2]
EVIDENCE_CACHE_PATH = KIT / "content" / "feed" / "evidence_cache.json"

# Configuration defaults
DEFAULT_EVIDENCE_RETRIEVAL_ENABLED = True
DEFAULT_MAX_CANDIDATES_PER_RUN = 10
DEFAULT_MAX_URLS_PER_CANDIDATE = 5
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_CONTENT_BYTES = 500_000  # 500KB
DEFAULT_CACHE_TTL_DAYS = 30

# Domain rules: allow official sources, documentation, independent coverage
DEFAULT_ALLOWED_DOMAINS = frozenset({
    # Official vendor domains
    "openai.com", "anthropic.com", "google.com", "microsoft.com", "meta.com",
    "mistral.ai", "huggingface.co", "apple.com", "amazon.com", "nvidia.com",
    "python.org", "rust-lang.org", "golang.org", "nodejs.org", "react.dev",
    "postgresql.org", "mysql.com", "mongodb.com", "redis.io", "docker.com",
    "kubernetes.io", "cloudflare.com", "vercel.com", "netlify.com",
    # Code repositories
    "github.com", "gitlab.com", "bitbucket.org",
    # Research
    "arxiv.org", "aclanthology.org", "ieee.org", "acm.org", "nature.com",
    # Documentation
    "readthedocs.io", "docs.python.org", "developer.mozilla.org",
    # Independent technical coverage
    "techcrunch.com", "theverge.com", "arstechnica.com", "zdnet.com",
    "infoworld.com", "developer.com", "stackoverflow.blog",
})

# Deny social media, aggregators, syndicators
DEFAULT_DENIED_DOMAINS = frozenset({
    # Social media (noisy, not primary evidence)
    "twitter.com", "x.com", "facebook.com", "instagram.com", "linkedin.com",
    "reddit.com", "news.ycombinator.com", "slashdot.org",
    # Aggregators (syndicated, not primary)
    "msn.com", "news.google.com", "flipboard.com", "feedly.com",
    # Press release wires (mirrors, not independent)
    "prnewswire.com", "businesswire.com", "globenewswire.com",
})


@dataclass(frozen=True)
class EvidenceRetrievalConfig:
    """Configuration for bounded evidence retrieval."""
    enabled: bool = DEFAULT_EVIDENCE_RETRIEVAL_ENABLED
    max_candidates_per_run: int = DEFAULT_MAX_CANDIDATES_PER_RUN
    max_urls_per_candidate: int = DEFAULT_MAX_URLS_PER_CANDIDATE
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES
    cache_ttl_days: int = DEFAULT_CACHE_TTL_DAYS
    allowed_domains: frozenset[str] = DEFAULT_ALLOWED_DOMAINS
    denied_domains: frozenset[str] = DEFAULT_DENIED_DOMAINS
    cache_path: Path = EVIDENCE_CACHE_PATH


def load_evidence_retrieval_config() -> EvidenceRetrievalConfig:
    """Load config from environment or use defaults."""
    def parse_domains(env_var: str, default: frozenset[str]) -> frozenset[str]:
        val = os.environ.get(env_var, "").strip()
        if not val:
            return default
        return frozenset(d.strip().lower() for d in val.split(",") if d.strip())

    return EvidenceRetrievalConfig(
        enabled=os.environ.get("EVIDENCE_RETRIEVAL_ENABLED", "true").lower() in ("true", "1", "yes"),
        max_candidates_per_run=int(os.environ.get("EVIDENCE_RETRIEVAL_MAX_CANDIDATES", DEFAULT_MAX_CANDIDATES_PER_RUN)),
        max_urls_per_candidate=int(os.environ.get("EVIDENCE_RETRIEVAL_MAX_URLS", DEFAULT_MAX_URLS_PER_CANDIDATE)),
        timeout_seconds=int(os.environ.get("EVIDENCE_RETRIEVAL_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
        max_content_bytes=int(os.environ.get("EVIDENCE_RETRIEVAL_MAX_BYTES", DEFAULT_MAX_CONTENT_BYTES)),
        cache_ttl_days=int(os.environ.get("EVIDENCE_RETRIEVAL_CACHE_TTL", DEFAULT_CACHE_TTL_DAYS)),
        allowed_domains=parse_domains("EVIDENCE_RETRIEVAL_ALLOWED_DOMAINS", DEFAULT_ALLOWED_DOMAINS),
        denied_domains=parse_domains("EVIDENCE_RETRIEVAL_DENIED_DOMAINS", DEFAULT_DENIED_DOMAINS),
    )


def identify_evidence_urls(candidate: dict[str, Any], config: EvidenceRetrievalConfig) -> list[str]:
    """Identify evidence URLs from candidate metadata and sources.

    Returns up to config.max_urls_per_candidate URLs, filtered by domain rules.
    """
    urls: list[str] = []
    seen: set[str] = set()

    def add_url(url: str) -> None:
        if not url or url in seen:
            return
        domain = registrable_domain(url)
        if domain in config.denied_domains:
            return
        if config.allowed_domains and domain not in config.allowed_domains:
            return
        seen.add(url)
        urls.append(url)

    enrichment = candidate.get("metadata", {}).get("enrichment", {})
    primary = enrichment.get("primary_source")

    # 1. Primary source URL (official announcement, GitHub, arxiv, etc.)
    if primary and primary.get("url"):
        add_url(primary["url"])

    # 2. Independent corroborating sources
    for source in enrichment.get("sources", []):
        if source.get("independent_corroboration") and source.get("url"):
            add_url(source["url"])

    # 3. Derive documentation, release notes, pricing from primary domain
    if primary and primary.get("url"):
        parsed = urlparse(primary["url"])
        base_domain = f"{parsed.scheme}://{parsed.netloc}"
        # Documentation
        for path in ["/docs", "/documentation", "/api", "/reference"]:
            add_url(base_domain + path)
        # Release notes / changelog
        for path in ["/changelog", "/release-notes", "/releases"]:
            add_url(base_domain + path)
        # Pricing
        add_url(base_domain + "/pricing")

    return urls[:config.max_urls_per_candidate]


def fetch_url(url: str, config: EvidenceRetrievalConfig) -> dict[str, Any]:
    """Fetch a URL with timeout and size limit.

    Returns {url, content, fetched_at, status, error?}.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "SMKit/1.0 (evidence retrieval; bounded crawling)"}
        )
        with urllib.request.urlopen(req, timeout=config.timeout_seconds) as response:
            content_bytes = response.read(config.max_content_bytes)
            # Try UTF-8, fall back to latin-1
            try:
                text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = content_bytes.decode("latin-1", errors="ignore")
            return {
                "url": url,
                "content": text[:config.max_content_bytes],
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "status": response.status,
            }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return {
            "url": url,
            "content": "",
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": 0,
            "error": str(e),
        }


def load_evidence_cache(config: EvidenceRetrievalConfig) -> dict[str, Any]:
    """Load evidence cache from disk."""
    if not config.cache_path.exists():
        return {}
    try:
        data = json.loads(config.cache_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_evidence_cache(cache: dict[str, Any], config: EvidenceRetrievalConfig) -> None:
    """Save evidence cache to disk with TTL pruning."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=config.cache_ttl_days)).isoformat()
    pruned = {
        url: entry for url, entry in cache.items()
        if isinstance(entry, dict) and str(entry.get("fetched_at", "")) >= cutoff
    }
    try:
        config.cache_path.parent.mkdir(parents=True, exist_ok=True)
        config.cache_path.write_text(json.dumps(pruned, indent=2), encoding="utf-8")
    except OSError:
        pass  # Caching is an optimization; never break the pipeline


def retrieve_evidence_for_candidates(
    candidates: list[dict[str, Any]],
    config: EvidenceRetrievalConfig | None = None,
) -> list[dict[str, Any]]:
    """Retrieve evidence for top candidates and re-run enrichment.

    Selects only the top config.max_candidates_per_run candidates.
    Fetches evidence URLs (bounded, cached, domain-filtered).
    Re-runs enrichment with fetched evidence content.

    Returns updated candidates with fetched evidence in metadata.
    Does not mutate the input candidates.
    """
    if config is None:
        config = load_evidence_retrieval_config()

    if not config.enabled:
        return candidates

    # Work on deep copies to avoid mutating input
    top_candidates = [copy.deepcopy(c) for c in candidates[:config.max_candidates_per_run]]
    remaining = candidates[config.max_candidates_per_run:]

    # Load cache
    cache = load_evidence_cache(config)

    # Retrieve evidence for each top candidate
    for candidate in top_candidates:
        evidence_urls = identify_evidence_urls(candidate, config)
        fetched_evidence: list[dict[str, Any]] = []

        for url in evidence_urls:
            # Check cache first (no duplicate fetches)
            if url in cache:
                fetched_evidence.append(cache[url])
            else:
                # Fetch and cache
                result = fetch_url(url, config)
                cache[url] = result
                fetched_evidence.append(result)

        # Store fetched evidence in candidate metadata
        candidate.setdefault("metadata", {})["fetched_evidence"] = fetched_evidence

        # Re-run enrichment with fetched evidence content
        if fetched_evidence:
            # Concatenate evidence content (bounded)
            evidence_text = "\n\n".join(
                e.get("content", "")[:2000] for e in fetched_evidence if e.get("content")
            )[:10000]  # Cap total evidence text

            if evidence_text:
                # Build enriched item with evidence
                enriched_item = dict(candidate)
                enriched_item["metadata"]["evidence_content"] = evidence_text

                # Re-run enrichment
                re_enrichment = enrich_candidate(enriched_item, related_items=[])
                enriched_item["metadata"]["enrichment"] = re_enrichment.to_dict()

                # Update candidate with re-enrichment results
                candidate["metadata"]["enrichment"] = re_enrichment.to_dict()
                if re_enrichment.sources:
                    candidate["sources"] = list(re_enrichment.sources)
                if re_enrichment.claims:
                    candidate["claims"] = list(re_enrichment.claims)

    # Save cache
    save_evidence_cache(cache, config)

    # Return updated top candidates + unchanged remaining
    return top_candidates + list(remaining)
