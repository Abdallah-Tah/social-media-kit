"""Explainable authority scoring for smkit feed (Phase 1).

Authority is a combination of:
    1. Domain authority       – editorial trust per base domain
    2. Source type authority  – baseline trust per collector source
    3. Social proof signals   – HN/Reddit engagement when available
    4. Personal history boost – domains that performed well for us

All components are transparent and logged per item.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parents[1]
FEED_DIR = BASE / "content" / "feed"
DOMAIN_AUTHORITY_PATH = FEED_DIR / "domain_authority.json"
DOMAIN_HISTORY_PATH = FEED_DIR / "domain_history.json"


@dataclass
class AuthorityBreakdown:
    domain_score: float = 0.0
    source_score: float = 0.0
    social_score: float = 0.0
    history_score: float = 0.0
    final_score: float = 0.0
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_score": round(self.domain_score, 2),
            "source_score": round(self.source_score, 2),
            "social_score": round(self.social_score, 2),
            "history_score": round(self.history_score, 2),
            "final_score": round(self.final_score, 2),
            "signals": self.signals,
        }


# ── Built-in domain authority tiers ───────────────────────────────────────────

def _default_domain_tiers() -> dict[str, float]:
    """Hand-curated baseline. Users can override via domain_authority.json."""
    return {
        # Tier 1: primary tech / business outlets
        "techcrunch.com": 0.80,
        "theverge.com": 0.80,
        "arstechnica.com": 0.85,
        "wired.com": 0.80,
        "bloomberg.com": 0.85,
        "reuters.com": 0.85,
        "wsj.com": 0.80,
        "ft.com": 0.80,
        "mit.edu": 0.90,
        "stanford.edu": 0.90,
        "arxiv.org": 0.85,
        # Tier 2: developer / engineering focused
        "github.com": 0.85,
        "github.blog": 0.80,
        "news.ycombinator.com": 0.75,
        "dev.to": 0.55,
        "medium.com": 0.50,
        "substack.com": 0.50,
        "stackoverflow.blog": 0.75,
        "producthunt.com": 0.60,
        # Tier 3: general aggregators / platforms
        "reddit.com": 0.55,
        "youtube.com": 0.50,
        "googletagmanager.com": 0.30,
        "google.com": 0.60,
    }


def load_domain_authority() -> dict[str, float]:
    """Load user overrides; defaults always present as fallback."""
    defaults = _default_domain_tiers()
    if not DOMAIN_AUTHORITY_PATH.exists():
        return defaults
    try:
        overrides = json.loads(DOMAIN_AUTHORITY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return defaults
    if isinstance(overrides, dict):
        defaults.update(overrides)
    return defaults


def save_domain_authority(overrides: dict[str, float]) -> None:
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    DOMAIN_AUTHORITY_PATH.write_text(json.dumps(overrides, indent=2), encoding="utf-8")


# ── Personal domain history (what has worked for us) ──────────────────────────

def load_domain_history() -> dict[str, Any]:
    if not DOMAIN_HISTORY_PATH.exists():
        return {"clicks": {}, "shares": {}, "drafts": {}}
    try:
        data = json.loads(DOMAIN_HISTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"clicks": {}, "shares": {}, "drafts": {}}
    data.setdefault("clicks", {})
    data.setdefault("shares", {})
    data.setdefault("drafts", {})
    return data


def record_domain_success(domain: str, kind: str = "click", value: int = 1) -> None:
    """Record post-hoc success signal for a domain.

    kind: click | share | draft
    """
    history = load_domain_history()
    bucket = history.setdefault(kind + "s", {})
    bucket[domain] = bucket.get(domain, 0) + value
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    DOMAIN_HISTORY_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")


def history_score_for(domain: str, history: dict[str, Any] | None = None) -> float:
    if history is None:
        history = load_domain_history()
    clicks = history.get("clicks", {}).get(domain, 0)
    shares = history.get("shares", {}).get(domain, 0)
    drafts = history.get("drafts", {}).get(domain, 0)
    # Diminishing returns: first few signals matter most.
    score = 0.05 * min(clicks, 5) + 0.08 * min(shares, 3) + 0.02 * min(drafts, 10)
    return min(0.25, score)


# ── Social proof signals (HN/Reddit engagement) ───────────────────────────────

def social_score_for(metadata: dict[str, Any] | None = None) -> tuple[float, list[str]]:
    """Return a small boost when high engagement is detected in metadata."""
    if not metadata:
        return 0.0, []
    signals: list[str] = []
    score = 0.0
    upvotes = metadata.get("upvotes") or metadata.get("score") or 0
    comments = metadata.get("comments") or metadata.get("num_comments") or 0
    if upvotes:
        try:
            u = int(upvotes)
            if u >= 500:
                score += 0.15
                signals.append(f"{u} upvotes")
            elif u >= 100:
                score += 0.10
                signals.append(f"{u} upvotes")
            elif u >= 20:
                score += 0.05
                signals.append(f"{u} upvotes")
        except (ValueError, TypeError):
            pass
    if comments:
        try:
            c = int(comments)
            if c >= 100:
                score += 0.05
                signals.append(f"{c} comments")
        except (ValueError, TypeError):
            pass
    return min(0.20, score), signals


# ── Main authority scorer ───────────────────────────────────────────────────

def item_authority(
    url: str,
    source: str,
    metadata: dict[str, Any] | None = None,
    domain_authority: dict[str, float] | None = None,
    history: dict[str, Any] | None = None,
) -> AuthorityBreakdown:
    """Compute an explainable authority score for a feed item."""
    if domain_authority is None:
        domain_authority = load_domain_authority()
    if history is None:
        history = load_domain_history()

    parsed = urlparse(url)
    domain = parsed.netloc.lower().removeprefix("www.")

    # Domain score: exact, then suffix, then default.
    domain_score = domain_authority.get(domain)
    signals: list[str] = []
    if domain_score is None:
        # Try suffix match for subdomains.
        for key, val in domain_authority.items():
            if domain.endswith(key) or key.endswith(domain):
                domain_score = val
                break
    if domain_score is None:
        # Default by source type.
        if source in ("hackernews", "reddit"):
            domain_score = 0.60
            signals.append(f"community source ({source})")
        elif source == "google_news":
            domain_score = 0.65
            signals.append("Google News syndicated")
        else:
            domain_score = 0.45
            signals.append("unknown domain")
    else:
        signals.append(f"domain: {domain}")

    # Source-type baseline.
    from scripts.feed_sources import source_authority
    source_score = source_authority(source)

    # Social proof.
    social_score, social_signals = social_score_for(metadata)
    signals.extend(social_signals)

    # Personal history.
    hist_score = history_score_for(domain, history)
    if hist_score > 0:
        signals.append(f"history bonus {hist_score:.0%}")

    # Weighted blend. Domain and source are the dominant signals.
    final = min(1.0, 0.45 * domain_score + 0.30 * source_score + 0.15 * social_score + 0.10 * hist_score)

    return AuthorityBreakdown(
        domain_score=domain_score,
        source_score=source_score,
        social_score=social_score,
        history_score=hist_score,
        final_score=final,
        signals=signals,
    )


def score_feed_item_authority(item: Any) -> tuple[float, AuthorityBreakdown]:
    """Convenience: attach authority to an item with a `url` and `source`."""
    metadata = getattr(item, "metadata", None) or {}
    breakdown = item_authority(item.url, item.source, metadata=metadata)
    return breakdown.final_score, breakdown
