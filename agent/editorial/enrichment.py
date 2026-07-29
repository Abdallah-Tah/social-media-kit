"""Phase 1 Stage 7C.5 — editorial candidate enrichment before admission.

Converts shallow feed records into evidence-rich Candidate inputs that
Stages 2–7 can evaluate correctly. Deterministic: no LLM, no network,
no publishing, no notifications.

The enrichment stage prepares evidence. It does not make the final
admission decision.

Input:  shallow feed item dict (title, url, source, score, summary, ...)
Output: EnrichmentResult with structured evidence
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

from .models import (
    CLAIM_TYPES,
    DEVELOPMENT_TYPES,
    PRIMARY_KINDS,
    FIRST_PARTY_KINDS,
    TRACEABLE,
    UNTRACEABLE,
    TRACE_UNASSESSED,
    VERIFIED_INDEPENDENT,
    VERIFIED_VENDOR,
    VERIFIED_UNKNOWN,
    registrable_domain,
)

ENRICHMENT_VERSION = 1

# ── Status constants ─────────────────────────────────────────────────────────

STATUS_ENRICHED = "enriched"
STATUS_PARTIALLY_ENRICHED = "partially_enriched"
STATUS_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
STATUS_FAILED = "failed"

# ── Primary-source domain patterns ───────────────────────────────────────────

# Domains that are official primary sources for their own products.
_OFFICIAL_DOMAINS: dict[str, str] = {
    "openai.com": "official_announcement",
    "anthropic.com": "official_announcement",
    "google.com": "official_announcement",
    "deepmind.google": "official_announcement",
    "blog.google": "official_announcement",
    "microsoft.com": "official_announcement",
    "devblogs.microsoft.com": "official_announcement",
    "meta.com": "official_announcement",
    "ai.meta.com": "official_announcement",
    "mistral.ai": "official_announcement",
    "huggingface.co": "official_announcement",
    "apple.com": "official_announcement",
    "developer.apple.com": "official_documentation",
    "amazon.com": "official_announcement",
    "aws.amazon.com": "official_announcement",
    "nvidia.com": "official_announcement",
    "developer.nvidia.com": "official_documentation",
    "rust-lang.org": "official_announcement",
    "blog.rust-lang.org": "official_announcement",
    "python.org": "official_announcement",
    "blog.python.org": "official_announcement",
    "golang.org": "official_announcement",
    "go.dev": "official_announcement",
    "nodejs.org": "official_announcement",
    "react.dev": "official_documentation",
    "nextjs.org": "official_documentation",
    "vuejs.org": "official_documentation",
    "angular.dev": "official_documentation",
    "svelte.dev": "official_documentation",
    "tailwindcss.com": "official_documentation",
    "typescriptlang.org": "official_documentation",
    "developer.mozilla.org": "official_documentation",
    "docs.github.com": "official_documentation",
    "github.blog": "official_announcement",
    "gitlab.com": "official_announcement",
    "about.gitlab.com": "official_announcement",
    "docker.com": "official_announcement",
    "kubernetes.io": "official_announcement",
    "postgresql.org": "official_announcement",
    "mysql.com": "official_announcement",
    "mongodb.com": "official_announcement",
    "redis.io": "official_announcement",
    "elastic.co": "official_announcement",
    "grafana.com": "official_announcement",
    "prometheus.io": "official_announcement",
    "terraform.io": "official_documentation",
    "ansible.com": "official_documentation",
    "cloudflare.com": "official_announcement",
    "blog.cloudflare.com": "official_announcement",
    "vercel.com": "official_announcement",
    "netlify.com": "official_announcement",
    "stripe.com": "official_documentation",
    "docs.stripe.com": "official_documentation",
    "twilio.com": "official_documentation",
    "sendgrid.com": "official_documentation",
    "auth0.com": "official_documentation",
    "okta.com": "official_documentation",
    "datadog.com": "official_documentation",
    "sentry.io": "official_documentation",
    "newrelic.com": "official_documentation",
    "jetbrains.com": "official_announcement",
    "blog.jetbrains.com": "official_announcement",
    "visualstudio.com": "official_announcement",
    "code.visualstudio.com": "official_announcement",
    "sublimetext.com": "official_announcement",
    "neovim.io": "official_announcement",
    "emacs.org": "official_announcement",
    "gnu.org": "official_announcement",
    "fsf.org": "official_announcement",
    "eff.org": "official_announcement",
    "w3.org": "standards_publication",
    "ietf.org": "standards_publication",
    "rfc-editor.org": "standards_publication",
    "ecma-international.org": "standards_publication",
    "iso.org": "standards_publication",
    "nist.gov": "government_publication",
    "cisa.gov": "government_publication",
    "arxiv.org": "research_paper",
    "aclanthology.org": "research_paper",
    "ieee.org": "research_paper",
    "acm.org": "research_paper",
    "springer.com": "research_paper",
    "nature.com": "research_paper",
    "science.org": "research_paper",
    "cell.com": "research_paper",
    "thelancet.com": "research_paper",
    "nejm.org": "research_paper",
    "bmj.com": "research_paper",
}

# URL path patterns that indicate primary sources.
_PRIMARY_PATH_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"/releases?(/|$)", re.I), "repository_release"),
    (re.compile(r"/changelog(/|$)", re.I), "release_notes"),
    (re.compile(r"/release-notes?(/|$)", re.I), "release_notes"),
    (re.compile(r"/security/advisory", re.I), "security_advisory"),
    (re.compile(r"/advisory(/|$)", re.I), "security_advisory"),
    (re.compile(r"/cve-", re.I), "security_advisory"),
    (re.compile(r"/docs?(/|$)", re.I), "official_documentation"),
    (re.compile(r"/documentation(/|$)", re.I), "official_documentation"),
    (re.compile(r"/api-reference(/|$)", re.I), "official_documentation"),
    (re.compile(r"/blog(/|$)", re.I), "official_announcement"),
    (re.compile(r"/announcement(/|$)", re.I), "official_announcement"),
    (re.compile(r"/press(/|$)", re.I), "official_announcement"),
]

# GitHub-specific patterns.
_GITHUB_RELEASE_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/releases?(/|$)", re.I)
_GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(/|$)", re.I)
_GITHUB_ADVISORY_RE = re.compile(
    r"^https?://github\.com/advisories?(/|$)", re.I)

# ── Development-type keyword patterns ────────────────────────────────────────

_DEV_TYPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(releases?|launches?|ships?|announces?|introduces?|unveils?)\b.*\b(model|gpt|claude|gemini|llama|mistral|copilot)\b", re.I), "model_release"),
    (re.compile(r"\b(model|gpt|claude|gemini|llama|mistral|copilot)\b.*\b(releases?|launches?|ships?|announces?|available|now)\b", re.I), "model_release"),
    (re.compile(r"\bapi\b.*\b(releases?|launches?|ships?|available|endpoint|v\d+)\b", re.I), "api_release"),
    (re.compile(r"\b(releases?|launches?|ships?|announces?)\b.*\bapi\b", re.I), "api_release"),
    (re.compile(r"\b(product|app|service|platform|tool|feature)\b.*\b(releases?|launches?|ships?|announces?|available)\b", re.I), "product_release"),
    (re.compile(r"\b(releases?|launches?|ships?|announces?)\b.*\b(product|app|service|platform|tool|feature)\b", re.I), "product_release"),
    (re.compile(r"\b(v?\d+\.\d+|version)\b.*\b(released?|ships?|available|out)\b", re.I), "repository_release"),
    (re.compile(r"\b(released?|ships?|available)\b.*\b(v?\d+\.\d+|version)\b", re.I), "repository_release"),
    (re.compile(r"\bgithub\.com/[^/]+/[^/]+/releases?\b", re.I), "repository_release"),
    (re.compile(r"\b(paper|research|study|arxiv)\b.*\b(published?|released?|published)\b", re.I), "research_paper"),
    (re.compile(r"\b(benchmark|score|performance|evaluation)\b.*\b(result|score|ranking|leaderboard)\b", re.I), "benchmark"),
    (re.compile(r"\b(pricing|price|cost|free tier|subscription|plan)\b.*\b(change|update|new|announced?)\b", re.I), "pricing_change"),
    (re.compile(r"\b(security|vulnerability|cve|exploit|patch|advisory)\b", re.I), "security_issue"),
    (re.compile(r"\b(license|licensing|open.?source|mit|apache|gpl|bsd)\b.*\b(change|update|switch)\b", re.I), "licensing_change"),
    (re.compile(r"\b(documentation|docs?|guide|tutorial|reference)\b.*\b(update|improved?|new|expanded?)\b", re.I), "documentation_update"),
    (re.compile(r"\b(deploy|deployment|available|region|cloud)\b.*\b(now|new|expanded?|launched?)\b", re.I), "deployment_availability"),
    (re.compile(r"\b(compatib|breaking|deprecat|migration|upgrade)\b", re.I), "compatibility_change"),
    (re.compile(r"\b(funding|raised?|acquisition|merger|ipo|valuation)\b", re.I), "funding_or_company_news"),
]

# ── Practical-signal keyword patterns ────────────────────────────────────────

_PRACTICAL_SIGNAL_PATTERNS: dict[str, re.Pattern] = {
    "has_code_change": re.compile(r"\b(code|commit|pull request|patch|diff|snippet|example)\b", re.I),
    "has_api_change": re.compile(r"\b(api|endpoint|rest|graphql|grpc|sdk|client library)\b", re.I),
    "has_repository_reference": re.compile(r"\b(github|gitlab|bitbucket|repository|repo|source code)\b", re.I),
    "has_documentation_reference": re.compile(r"\b(documentation|docs?|guide|reference|manual|readme)\b", re.I),
    "has_deployment_impact": re.compile(r"\b(deploy|deployment|infrastructure|server|cloud|aws|azure|gcp)\b", re.I),
    "has_compatibility_impact": re.compile(r"\b(compatib|breaking|deprecat|backward|forward|migration)\b", re.I),
    "has_migration_requirement": re.compile(r"\b(migrat|upgrade|transition|move from|switch to)\b", re.I),
    "has_security_action": re.compile(r"\b(security|vulnerability|patch|cve|exploit|remediat|fix)\b", re.I),
    "has_pricing_impact": re.compile(r"\b(pricing|price|cost|free|paid|subscription|billing)\b", re.I),
    "has_reproducible_test": re.compile(r"\b(test|benchmark|reproduc|measure|evaluat|compare)\b", re.I),
    "has_architecture_implication": re.compile(r"\b(architect|design|pattern|structure|system|scalab)\b", re.I),
    "has_developer_decision": re.compile(r"\b(should|recommend|consider|choose|decide|adopt|evaluat)\b", re.I),
    "has_tooling_impact": re.compile(r"\b(tool|ide|editor|plugin|extension|cli|command|workflow)\b", re.I),
}

# ── Artifact recommendation rules ────────────────────────────────────────────

_ARTIFACT_RULES: dict[str, list[str]] = {
    "model_release": ["technical_analysis", "intelligence_brief", "takeaway_checklist"],
    "product_release": ["technical_analysis", "intelligence_brief", "compatibility_brief"],
    "api_release": ["technical_analysis", "tutorial_deep_dive", "migration_note"],
    "repository_release": ["tutorial_deep_dive", "technical_analysis", "takeaway_checklist"],
    "research_paper": ["technical_analysis", "intelligence_brief"],
    "benchmark": ["technical_analysis", "tradeoff_study", "intelligence_brief"],
    "pricing_change": ["compatibility_brief", "takeaway_checklist", "technical_analysis"],
    "security_issue": ["technical_analysis", "migration_note", "takeaway_checklist"],
    "licensing_change": ["compatibility_brief", "technical_analysis", "takeaway_checklist"],
    "documentation_update": ["tutorial_deep_dive", "technical_analysis"],
    "deployment_availability": ["takeaway_checklist", "compatibility_brief", "technical_analysis"],
    "compatibility_change": ["migration_note", "compatibility_brief", "takeaway_checklist"],
    "funding_or_company_news": ["intelligence_brief"],
    "general_news": ["intelligence_brief", "technical_analysis"],
    "unknown": ["intelligence_brief"],
}


# ── Output dataclass ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EnrichmentResult:
    """Structured evidence extracted from a shallow feed item."""
    status: str
    primary_source: dict[str, Any] | None = None
    sources: tuple[dict[str, Any], ...] = ()
    claims: tuple[dict[str, Any], ...] = ()
    development_type: str = "unknown"
    subject_org: str = ""
    event_time: str = ""
    practical_signals: dict[str, bool] = field(default_factory=dict)
    recommended_artifact_types: tuple[str, ...] = ()
    excerpts: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    confidence: int = 0
    version: int = ENRICHMENT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "primary_source": self.primary_source,
            "sources": list(self.sources),
            "claims": list(self.claims),
            "development_type": self.development_type,
            "subject_org": self.subject_org,
            "event_time": self.event_time,
            "practical_signals": dict(self.practical_signals),
            "recommended_artifact_types": list(self.recommended_artifact_types),
            "excerpts": list(self.excerpts),
            "warnings": list(self.warnings),
            "confidence": self.confidence,
            "version": self.version,
        }


# ── Primary-source resolution ────────────────────────────────────────────────

def _resolve_primary_source(url: str, title: str, summary: str,
                            metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Identify the primary source from URL patterns and metadata.

    Returns a source dict or None if no primary source can be established.
    Never fabricates a primary source.
    """
    if not url:
        return None

    domain = registrable_domain(url)
    parsed = urlparse(url)
    path = parsed.path or ""

    # Check GitHub-specific patterns first.
    gh_release = _GITHUB_RELEASE_RE.match(url)
    if gh_release:
        owner, repo = gh_release.group(1), gh_release.group(2)
        return {
            "url": url,
            "kind": "repository_release",
            "title": f"{owner}/{repo} release",
            "publisher": f"github.com/{owner}",
            "covers_exact_development": True,
            "adds_independent_evidence": False,
            "is_primary": True,
        }

    gh_advisory = _GITHUB_ADVISORY_RE.match(url)
    if gh_advisory:
        return {
            "url": url,
            "kind": "security_advisory",
            "title": title or "GitHub Security Advisory",
            "publisher": "github.com",
            "covers_exact_development": True,
            "adds_independent_evidence": False,
            "is_primary": True,
        }

    gh_repo = _GITHUB_REPO_RE.match(url)
    if gh_repo:
        owner, repo = gh_repo.group(1), gh_repo.group(2)
        return {
            "url": url,
            "kind": "repository",
            "title": f"{owner}/{repo}",
            "publisher": f"github.com/{owner}",
            "covers_exact_development": False,
            "adds_independent_evidence": False,
            "is_primary": True,
        }

    # Check official domain registry.
    if domain in _OFFICIAL_DOMAINS:
        kind = _OFFICIAL_DOMAINS[domain]
        # Refine kind based on path patterns.
        for pattern, path_kind in _PRIMARY_PATH_PATTERNS:
            if pattern.search(path):
                kind = path_kind
                break
        return {
            "url": url,
            "kind": kind,
            "title": title,
            "publisher": domain,
            "covers_exact_development": True,
            "adds_independent_evidence": False,
            "is_primary": True,
        }

    # Check path patterns for any domain.
    for pattern, kind in _PRIMARY_PATH_PATTERNS:
        if pattern.search(path):
            return {
                "url": url,
                "kind": kind,
                "title": title,
                "publisher": domain,
                "covers_exact_development": True,
                "adds_independent_evidence": False,
                "is_primary": True,
            }

    # Check arxiv.
    if "arxiv.org" in domain:
        return {
            "url": url,
            "kind": "research_paper",
            "title": title,
            "publisher": "arxiv.org",
            "covers_exact_development": True,
            "adds_independent_evidence": False,
            "is_primary": True,
        }

    return None


# ── Subject organization resolution ──────────────────────────────────────────

_ORG_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bOpenAI\b", re.I), "openai"),
    (re.compile(r"\bAnthropic\b", re.I), "anthropic"),
    (re.compile(r"\bGoogle\b|\bDeepMind\b", re.I), "google"),
    (re.compile(r"\bMicrosoft\b|\bGitHub\b|\bVS\s*Code\b|\bVisual\s+Studio\b", re.I), "microsoft"),
    (re.compile(r"\bMeta\b|\bFacebook\b|\bInstagram\b|\bWhatsApp\b", re.I), "meta"),
    (re.compile(r"\bMistral\b", re.I), "mistral"),
    (re.compile(r"\bHugging\s*Face\b", re.I), "huggingface"),
    (re.compile(r"\bApple\b|\bSwift\b|\bXcode\b|\biOS\b|\bmacOS\b", re.I), "apple"),
    (re.compile(r"\bAmazon\b|\bAWS\b", re.I), "amazon"),
    (re.compile(r"\bNVIDIA\b|\bCUDA\b", re.I), "nvidia"),
    (re.compile(r"\bRust\b|\brustc\b|\bcargo\b", re.I), "rust-lang"),
    (re.compile(r"\bPython\b|\bCPython\b|\bpip\b|\bPyPI\b", re.I), "python"),
    (re.compile(r"\bGo\b|\bGolang\b", re.I), "golang"),
    (re.compile(r"\bNode\.?js\b|\bnpm\b", re.I), "nodejs"),
    (re.compile(r"\bReact\b", re.I), "react"),
    (re.compile(r"\bNext\.?js\b|\bVercel\b", re.I), "vercel"),
    (re.compile(r"\bVue\b", re.I), "vuejs"),
    (re.compile(r"\bAngular\b", re.I), "angular"),
    (re.compile(r"\bSvelte\b", re.I), "svelte"),
    (re.compile(r"\bTailwind\b", re.I), "tailwind"),
    (re.compile(r"\bTypeScript\b", re.I), "typescript"),
    (re.compile(r"\bDocker\b", re.I), "docker"),
    (re.compile(r"\bKubernetes\b|\bk8s\b", re.I), "kubernetes"),
    (re.compile(r"\bPostgreSQL\b|\bPostgres\b", re.I), "postgresql"),
    (re.compile(r"\bMySQL\b", re.I), "mysql"),
    (re.compile(r"\bMongoDB\b", re.I), "mongodb"),
    (re.compile(r"\bRedis\b", re.I), "redis"),
    (re.compile(r"\bElastic\b|\bElasticsearch\b", re.I), "elastic"),
    (re.compile(r"\bGrafana\b", re.I), "grafana"),
    (re.compile(r"\bCloudflare\b", re.I), "cloudflare"),
    (re.compile(r"\bJetBrains\b|\bIntelliJ\b|\bPyCharm\b", re.I), "jetbrains"),
    (re.compile(r"\bClaude\b", re.I), "anthropic"),
    (re.compile(r"\bGPT\b|\bChatGPT\b|\bDALL-E\b|\bSora\b", re.I), "openai"),
    (re.compile(r"\bGemini\b", re.I), "google"),
    (re.compile(r"\bCopilot\b", re.I), "microsoft"),
    (re.compile(r"\bLlama\b", re.I), "meta"),
]


def _resolve_subject_org(title: str, summary: str, url: str,
                         metadata: dict[str, Any]) -> tuple[str, float]:
    """Resolve the subject organization from text and URL.

    Returns (org_name, confidence). Confidence 0.0 means unresolved.
    """
    # Check metadata first.
    for key in ("subject_org", "organization", "vendor", "owner",
                "repository_owner"):
        val = str(metadata.get(key, "")).strip().lower()
        if val:
            return val, 0.9

    # Check URL domain.
    domain = registrable_domain(url)
    if domain:
        # Strip TLD for org name.
        org = domain.split(".")[0]
        if org and org not in ("www", "blog", "docs", "api", "app"):
            return org, 0.6

    # Check title and summary patterns.
    text = f"{title} {summary}"
    for pattern, org in _ORG_PATTERNS:
        if pattern.search(text):
            return org, 0.8

    return "", 0.0


# ── Development type classification ──────────────────────────────────────────

def _classify_development_type(title: str, summary: str, url: str,
                               metadata: dict[str, Any]) -> str:
    """Classify the development type from text patterns and metadata."""
    # Check metadata first.
    dt = str(metadata.get("development_type", "")).strip().lower()
    if dt in DEVELOPMENT_TYPES:
        return dt

    # Check URL patterns.
    if _GITHUB_RELEASE_RE.match(url):
        return "repository_release"
    if _GITHUB_ADVISORY_RE.match(url):
        return "security_issue"
    if "arxiv.org" in url:
        return "research_paper"

    # Check text patterns.
    text = f"{title} {summary}"
    for pattern, dev_type in _DEV_TYPE_PATTERNS:
        if pattern.search(text):
            return dev_type

    return "unknown"


# ── Claim extraction ─────────────────────────────────────────────────────────

_VERSION_RE = re.compile(r"\b(v?\d+(?:\.\d+)*(?:\s*(?:rc|beta|alpha|preview)\d*)?)\b", re.I)
_PRICING_RE = re.compile(r"(\$\d+(?:\.\d+)?(?:\s*/\s*(?:month|year|mo|yr|token|request|call))?)", re.I)
_BENCHMARK_RE = re.compile(r"\b(\d+(?:\.\d+)?%)\b", re.I)


def _extract_claims(title: str, summary: str, url: str,
                    metadata: dict[str, Any],
                    primary_source: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract structured claims from title, summary, and metadata.

    Deterministic: no LLM. Every claim includes source references and
    verification status.
    """
    claims: list[dict[str, Any]] = []
    text = f"{title}. {summary}"
    source_url = primary_source["url"] if primary_source else url
    is_vendor = primary_source is not None and primary_source.get("kind") in (
        "official_announcement", "release_notes", "repository_release")

    # Version claims.
    for match in _VERSION_RE.finditer(text):
        claims.append({
            "text": f"Version {match.group(1)} mentioned",
            "material": True,
            "claim_type": "version_fact",
            "source_url": source_url,
            "source_urls": (source_url,) if source_url else (),
            "vendor_claim": is_vendor,
            "verification": VERIFIED_VENDOR if is_vendor else VERIFIED_UNKNOWN,
            "traceability": TRACEABLE if source_url else UNTRACEABLE,
        })

    # Pricing claims.
    for match in _PRICING_RE.finditer(text):
        claims.append({
            "text": f"Pricing: {match.group(1)}",
            "material": True,
            "claim_type": "pricing",
            "source_url": source_url,
            "source_urls": (source_url,) if source_url else (),
            "vendor_claim": is_vendor,
            "verification": VERIFIED_VENDOR if is_vendor else VERIFIED_UNKNOWN,
            "traceability": TRACEABLE if source_url else UNTRACEABLE,
        })

    # Benchmark claims.
    for match in _BENCHMARK_RE.finditer(text):
        claims.append({
            "text": f"Benchmark result: {match.group(1)}",
            "material": True,
            "claim_type": "benchmark",
            "source_url": source_url,
            "source_urls": (source_url,) if source_url else (),
            "vendor_claim": is_vendor,
            "verification": VERIFIED_VENDOR if is_vendor else VERIFIED_UNKNOWN,
            "traceability": TRACEABLE if source_url else UNTRACEABLE,
        })

    # Event fact claim (the thing happened).
    if title:
        claims.append({
            "text": title,
            "material": True,
            "claim_type": "event_fact",
            "source_url": source_url,
            "source_urls": (source_url,) if source_url else (),
            "vendor_claim": is_vendor,
            "verification": VERIFIED_VENDOR if is_vendor else VERIFIED_UNKNOWN,
            "traceability": TRACEABLE if source_url else UNTRACEABLE,
        })

    # Security claims.
    if re.search(r"\b(security|vulnerability|cve|exploit|patch)\b", text, re.I):
        claims.append({
            "text": "Security-related development",
            "material": True,
            "claim_type": "security",
            "source_url": source_url,
            "source_urls": (source_url,) if source_url else (),
            "vendor_claim": is_vendor,
            "verification": VERIFIED_VENDOR if is_vendor else VERIFIED_UNKNOWN,
            "traceability": TRACEABLE if source_url else UNTRACEABLE,
        })

    # Metadata-derived claims.
    for key in ("version", "tag_name", "benchmarks", "pricing"):
        val = metadata.get(key)
        if val:
            claims.append({
                "text": f"{key}: {val}",
                "material": True,
                "claim_type": "version_fact" if key in ("version", "tag_name") else "unclassified",
                "source_url": source_url,
                "source_urls": (source_url,) if source_url else (),
                "vendor_claim": True,
                "verification": VERIFIED_VENDOR,
                "traceability": TRACEABLE if source_url else UNTRACEABLE,
            })

    return claims


# ── Practical signal detection ───────────────────────────────────────────────

def _detect_practical_signals(title: str, summary: str, url: str,
                              metadata: dict[str, Any],
                              development_type: str) -> dict[str, bool]:
    """Detect practical developer-value signals from content.

    Signals are detected from content keywords, not solely from the
    development-type label.
    """
    text = f"{title} {summary} {url}"
    signals: dict[str, bool] = {}
    for signal_name, pattern in _PRACTICAL_SIGNAL_PATTERNS.items():
        signals[signal_name] = bool(pattern.search(text))

    # Repository-specific signals.
    if _GITHUB_REPO_RE.match(url) or _GITHUB_RELEASE_RE.match(url):
        signals["has_repository_reference"] = True
        signals["has_code_change"] = True

    # Documentation-specific signals.
    if re.search(r"\b(docs?|documentation|guide|reference)\b", url, re.I):
        signals["has_documentation_reference"] = True

    return signals


# ── Artifact recommendation ──────────────────────────────────────────────────

def _recommend_artifacts(development_type: str,
                         practical_signals: dict[str, bool]) -> tuple[str, ...]:
    """Recommend artifact types based on development type and signals."""
    base = _ARTIFACT_RULES.get(development_type, _ARTIFACT_RULES["unknown"])

    # Adjust based on practical signals.
    result = list(base)
    if practical_signals.get("has_migration_requirement") and "migration_note" not in result:
        result.append("migration_note")
    if practical_signals.get("has_security_action") and "takeaway_checklist" not in result:
        result.append("takeaway_checklist")
    if practical_signals.get("has_reproducible_test") and "tradeoff_study" not in result:
        result.append("tradeoff_study")

    return tuple(result[:5])  # Cap at 5 recommendations.


# ── Excerpt handling ─────────────────────────────────────────────────────────

def _extract_excerpts(title: str, summary: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Capture the best available local excerpt from already-ingested content.

    No unrestricted full-page scraping. Uses only saved summary, description,
    release notes, abstract, or feed-provided excerpt.
    """
    excerpts: list[dict[str, Any]] = []

    if summary:
        excerpts.append({
            "text": summary,
            "source": "feed_summary",
            "length": len(summary),
        })

    desc = str(metadata.get("description", "")).strip()
    if desc and desc != summary:
        excerpts.append({
            "text": desc,
            "source": "metadata_description",
            "length": len(desc),
        })

    abstract = str(metadata.get("abstract", "")).strip()
    if abstract:
        excerpts.append({
            "text": abstract,
            "source": "paper_abstract",
            "length": len(abstract),
        })

    release_notes = str(metadata.get("release_notes", "")).strip()
    if release_notes:
        excerpts.append({
            "text": release_notes,
            "source": "release_notes",
            "length": len(release_notes),
        })

    body = str(metadata.get("body", "")).strip()
    if body:
        excerpts.append({
            "text": body[:2000],  # Cap at 2000 chars.
            "source": "stored_body",
            "length": len(body),
        })

    return excerpts


# ── Corroboration detection ──────────────────────────────────────────────────

def _detect_corroboration(
    item: dict[str, Any],
    related_items: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Identify related-source candidates from same-day related items.

    Title overlap identifies RELATED sources only. It does NOT set
    adds_independent_evidence=True. Every related source must pass the
    Stage 2.6 relationship detector before counting as independent
    corroboration.

    Excludes: syndicated copies, press-release mirrors, same-owner domains,
    duplicate canonical URLs.
    """
    item_url = str(item.get("url", ""))
    item_domain = registrable_domain(item_url)
    item_title_words = set(re.findall(r"\b[a-z]{3,}\b", str(item.get("title", "")).lower()))

    corroborating: list[dict[str, Any]] = []
    seen_domains: set[str] = set()
    if item_domain:
        seen_domains.add(item_domain)

    for related in related_items:
        rel_url = str(related.get("url", ""))
        rel_domain = registrable_domain(rel_url)
        if not rel_domain or rel_domain in seen_domains:
            continue

        # Check title similarity (simple word overlap).
        rel_title_words = set(re.findall(r"\b[a-z]{3,}\b", str(related.get("title", "")).lower()))
        if not item_title_words or not rel_title_words:
            continue
        overlap = len(item_title_words & rel_title_words)
        similarity = overlap / max(len(item_title_words), len(rel_title_words))
        if similarity < 0.3:
            continue

        # Exclude syndicated copies and press-release mirrors.
        rel_source = str(related.get("source", "")).lower()
        if rel_source in ("press_release", "pr_newswire", "business_wire"):
            continue

        seen_domains.add(rel_domain)
        # Title overlap identifies a RELATED source candidate only.
        # adds_independent_evidence is False until Stage 2.6 validates it.
        corroborating.append({
            "url": rel_url,
            "kind": "secondary",
            "title": str(related.get("title", "")),
            "publisher": rel_domain,
            "covers_exact_development": similarity > 0.5,
            "adds_independent_evidence": False,  # Must be validated by Stage 2.6
            "relationship_candidate": True,  # Flag for Stage 2.6 review
            "is_primary": False,
            "similarity": round(similarity, 2),
        })

    return corroborating


# ── Main enrichment function ─────────────────────────────────────────────────

def enrich_candidate(
    item: dict[str, Any],
    related_items: Sequence[dict[str, Any]] = (),
) -> EnrichmentResult:
    """Enrich a shallow feed item with structured evidence.

    Deterministic: no LLM, no network, no publishing, no notifications.
    Does not mutate the input item.
    """
    title = str(item.get("title", "")).strip()
    url = str(item.get("url", "")).strip()
    summary = str(item.get("summary", "") or item.get("description", "")).strip()
    source = str(item.get("source", "")).strip()
    metadata = dict(item.get("metadata", {}) or {})

    warnings: list[str] = []

    if not title and not url:
        return EnrichmentResult(
            status=STATUS_FAILED,
            warnings=("no_title_and_no_url",),
        )

    # 1. Primary-source resolution.
    primary_source = _resolve_primary_source(url, title, summary, metadata)
    if primary_source is None:
        warnings.append("no_primary_source")

    # 2. Subject organization.
    subject_org, org_confidence = _resolve_subject_org(title, summary, url, metadata)
    if not subject_org:
        warnings.append("subject_org_unresolved")
    elif org_confidence < 0.5:
        warnings.append("subject_org_low_confidence")

    # 3. Development type.
    development_type = _classify_development_type(title, summary, url, metadata)
    if development_type == "unknown":
        warnings.append("development_type_unknown")

    # 4. Claims.
    claims = _extract_claims(title, summary, url, metadata, primary_source)
    if not claims:
        warnings.append("no_claims_extracted")

    # 5. Corroboration.
    corroborating = _detect_corroboration(item, related_items)

    # 6. Build sources list.
    sources: list[dict[str, Any]] = []
    if primary_source:
        sources.append(primary_source)
    sources.extend(corroborating)
    # Add the original URL as a source if it's not already the primary.
    if url and (not primary_source or primary_source.get("url") != url):
        sources.append({
            "url": url,
            "kind": "secondary",
            "title": title,
            "publisher": registrable_domain(url),
            "covers_exact_development": False,
            "adds_independent_evidence": bool(corroborating),
            "is_primary": False,
            "feed_source": source,
        })

    # 7. Practical signals.
    practical_signals = _detect_practical_signals(
        title, summary, url, metadata, development_type)

    # 8. Artifact recommendations.
    recommended_artifacts = _recommend_artifacts(development_type, practical_signals)

    # 9. Excerpts.
    excerpts = _extract_excerpts(title, summary, metadata)
    if not excerpts:
        warnings.append("no_excerpt_available")

    # 10. Event time.
    event_time = str(item.get("published_at", "") or item.get("discovered_at", "")).strip()
    if not event_time:
        warnings.append("missing_event_time")

    # 11. Confidence scoring.
    confidence = 0
    if primary_source:
        confidence += 30
    if subject_org and org_confidence >= 0.5:
        confidence += 15
    if development_type != "unknown":
        confidence += 10
    if claims:
        confidence += 15
    # Related-source candidates add partial credit (not full corroboration).
    # Full corroboration credit requires Stage 2.6 validation.
    relationship_candidates = [s for s in sources if s.get("relationship_candidate")]
    if relationship_candidates:
        confidence += 5  # Partial credit for related sources found
    if excerpts:
        confidence += 10
    if event_time:
        confidence += 5
    confidence = min(100, confidence)

    # 12. Status.
    if confidence >= 60:
        status = STATUS_ENRICHED
    elif confidence >= 30:
        status = STATUS_PARTIALLY_ENRICHED
    else:
        status = STATUS_INSUFFICIENT_EVIDENCE

    return EnrichmentResult(
        status=status,
        primary_source=primary_source,
        sources=tuple(sources),
        claims=tuple(claims),
        development_type=development_type,
        subject_org=subject_org,
        event_time=event_time,
        practical_signals=practical_signals,
        recommended_artifact_types=recommended_artifacts,
        excerpts=tuple(excerpts),
        warnings=tuple(warnings),
        confidence=confidence,
    )


def enrich_many(
    items: Iterable[dict[str, Any]],
) -> list[tuple[dict[str, Any], EnrichmentResult]]:
    """Enrich a batch of feed items with cross-item corroboration.

    Each item is enriched with awareness of all other items in the batch
    for corroboration detection.
    """
    items_list = list(items)
    results: list[tuple[dict[str, Any], EnrichmentResult]] = []
    for i, item in enumerate(items_list):
        related = items_list[:i] + items_list[i + 1:]
        result = enrich_candidate(item, related_items=related)
        results.append((item, result))
    return results
