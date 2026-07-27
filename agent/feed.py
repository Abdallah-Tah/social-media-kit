"""Personalized AI news feed engine for smkit.

Google Discover-style feed that collects articles from multiple sources,
ranks them by user interests + freshness + authority + novelty, summarizes
them, dedupes stories, and optionally notifies or drafts social content.

Public entry points:
    build_feed(...) -> list[FeedItem]
    print_feed(items)
    save_feed(items)
    notify_feed(items, dry_run=True)
    post_feed(items, dry_run=True)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

__all__ = [
    "FEED_DIR",
    "EnrichmentStats",
    "FeedItem",
    "build_feed",
    "canonical_url",
    "doctor_feed",
    "enrichment_fingerprint",
    "enrichment_settings",
    "is_seen",
    "last_enrichment_stats",
    "load_profile_with_interests",
    "mark_seen",
    "notify_feed",
    "post_feed",
    "print_feed",
    "save_feed",
    "source_authority",
]

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from agent.config import load_env

load_env()

if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

FEED_DIR = KIT / "content" / "feed"
SEEN_PATH = FEED_DIR / "seen.json"
SEEN_DEFAULT_TTL_DAYS = 30

DEFAULT_SOURCES = ["google_news", "hackernews", "reddit"]
DEFAULT_LIMIT = 10
NOTIFY_TOP_N = 3

# ── LLM enrichment bounds ────────────────────────────────────────────────────
# feed_run is a *scheduled* job (every 3h via agent/automation.py), so anything
# per-item here multiplies by 8 runs/day forever. Two calls per item (summary +
# reason) against an unbounded feed is how a background job quietly becomes the
# largest line on the bill. Every bound below exists to make that impossible.
ENRICHMENT_CACHE_PATH = FEED_DIR / "enrichment_cache.json"
ENRICHMENT_LOG_PATH = FEED_DIR / "enrichment_log.jsonl"
ENRICHMENT_CACHE_TTL_DAYS = 30
ENRICHMENT_JOB_ID = "feed_llm"
LLM_CALLS_PER_ITEM = 2  # _llm_summary + _llm_reason

# Production defaults. Enrichment is ON because the summaries are the point of
# the feed, but capped at the 5 items the pre-existing code already implied, so
# turning the fixed code on does not raise call volume above what was intended.
DEFAULT_ENRICHMENT_ENABLED = True
DEFAULT_MAX_ITEMS_PER_RUN = 5
DEFAULT_DAILY_BUDGET_USD = 0.50


class EnrichmentEmpty(RuntimeError):
    """Provider returned 200 with blank content.

    Treated as a failure, never as a successful empty summary — an empty string
    written to `item.summary` would cache as valid and suppress every retry.
    """


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass
class FeedItem:
    title: str = ""
    url: str = ""
    source: str = ""
    published_at: str = ""
    summary: str = ""
    score: float = 0.0
    matched_interests: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
            "score": round(self.score, 2),
            "matched_interests": self.matched_interests,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeedItem":
        return cls(
            title=data.get("title", ""),
            url=data.get("url", ""),
            source=data.get("source", ""),
            published_at=data.get("published_at", ""),
            summary=data.get("summary", ""),
            score=float(data.get("score", 0) or 0),
            matched_interests=list(data.get("matched_interests", [])),
            reason=data.get("reason", ""),
        )


# ── Configuration helpers ─────────────────────────────────────────────────────

def load_profile_with_interests(name: str = "default") -> dict[str, Any]:
    from agent.config import load_profile

    profile = load_profile(name)
    profile.setdefault("interests", [])
    # If profile doesn't define interests, fall back to global feed config.
    if not profile.get("interests"):
        feed_cfg = _load_feed_config()
        profile["interests"] = feed_cfg.get("interests", _default_interests())
    return profile


def _default_interests() -> list[str]:
    return [
        "artificial intelligence",
        "software engineering",
        "Laravel",
        "Python",
        "startups",
    ]


def _load_feed_config() -> dict[str, Any]:
    """Load optional config/feed.yaml or the feed block from agent.yaml."""
    from agent.config import _read_yaml, CONFIG_DIR

    feed_yaml = CONFIG_DIR / "feed.yaml"
    if feed_yaml.exists():
        return _read_yaml(feed_yaml)
    settings = _read_yaml(CONFIG_DIR / "agent.yaml")
    return settings.get("feed", {}) if isinstance(settings, dict) else {}


def get_feed_sources(profile: dict[str, Any] | None = None) -> list[str]:
    cfg = _load_feed_config()
    sources = cfg.get("sources", DEFAULT_SOURCES)
    if profile and profile.get("feed", {}).get("sources"):
        sources = profile["feed"]["sources"]
    return list(sources)


def get_notification_channel(profile: dict[str, Any] | None = None) -> str | None:
    cfg = _load_feed_config()
    channel = cfg.get("notification_channel")
    if profile and profile.get("feed", {}).get("notification_channel"):
        channel = profile["feed"]["notification_channel"]
    return channel


# ── Seen URL store (dedupe across runs) ───────────────────────────────────────

def load_seen() -> dict[str, Any]:
    if not SEEN_PATH.exists():
        return {"urls": {}, "ttl_days": SEEN_DEFAULT_TTL_DAYS}
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"urls": {}, "ttl_days": SEEN_DEFAULT_TTL_DAYS}
    data.setdefault("urls", {})
    data.setdefault("ttl_days", SEEN_DEFAULT_TTL_DAYS)
    return data


def save_seen(seen: dict[str, Any]) -> None:
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen, indent=2), encoding="utf-8")


def is_seen(url: str, seen: dict[str, Any] | None = None) -> bool:
    if seen is None:
        seen = load_seen()
    canon = canonical_url(url)
    if canon in seen["urls"]:
        return True
    # Also dedupe by netloc + last path segment if redirect/tracking params differ.
    parsed = urlparse(canon)
    fuzzy = f"{parsed.netloc}{parsed.path}"
    for stored in seen["urls"]:
        sp = urlparse(stored)
        if f"{sp.netloc}{sp.path}" == fuzzy:
            return True
    return False


def mark_seen(urls: list[str], seen: dict[str, Any] | None = None) -> None:
    if seen is None:
        seen = load_seen()
    now = _now().isoformat()
    ttl_days = int(seen.get("ttl_days", SEEN_DEFAULT_TTL_DAYS))
    cutoff = (_now() - dt.timedelta(days=ttl_days)).isoformat()
    # Evict old entries.
    seen["urls"] = {
        u: ts for u, ts in seen["urls"].items() if ts >= cutoff
    }
    for url in urls:
        seen["urls"][canonical_url(url)] = now
    save_seen(seen)


# ── URL normalization ─────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    """Strip tracking params and normalize a URL for dedupe keys."""
    url = url.strip()
    parsed = urlparse(url)
    q = parsed.query
    if q:
        stripped = {
            k: v
            for k, v in urllib.parse.parse_qsl(q)
            if k.lower() not in _TRACKING_PARAMS
        }
        q = urlencode(stripped)
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.params, q, "")
    )


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ttclid", "li_fat_id", "mc_cid", "mc_eid",
    "ref", "source", "si", "feature", "ref_src",
}


# ── Fetching pipeline ───────────────────────────────────────────────────────

def build_feed(
    topic: str | None = None,
    profile_name: str = "default",
    limit: int = DEFAULT_LIMIT,
    excluded_sources: list[str] | None = None,
    use_llm: bool = True,
    include_seen: bool = False,
) -> list[FeedItem]:
    """Fetch, dedupe, rank, and summarize a personalized feed.

    Args:
        topic: Optional topic override. If given, sources are queried with it.
        profile_name: Brand profile to pull interests from.
        limit: How many top items to return.
        excluded_sources: Source names to skip this run.
        use_llm: Whether to use the LLM provider for summaries/explanations.
        include_seen: If True, include previously seen URLs (demo/analysis mode).
    """
    profile = load_profile_with_interests(profile_name)
    interests = [i.lower() for i in profile.get("interests", [])]
    sources = get_feed_sources(profile)
    if excluded_sources:
        sources = [s for s in sources if s not in excluded_sources]

    raw: list[FeedItem] = []
    from scripts.feed_sources import fetch_all

    raw = fetch_all(sources, topic=topic)

    seen = load_seen()
    if not include_seen:
        raw = [item for item in raw if not is_seen(item.url, seen)]

    from scripts.feed_ranker import dedupe_items, rank_items

    ranked = rank_items(dedupe_items(raw), interests, topic=topic)

    if use_llm:
        ranked = _summarize_top(ranked, profile, topic=topic)

    # Mark top N as seen so reruns don't surface the same stories.
    # When include_seen is True, do not update the seen store.
    if not include_seen:
        mark_seen([item.url for item in ranked[:limit]], seen)
    return ranked[:limit]


# ── Enrichment configuration ─────────────────────────────────────────────────

def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return None


def _as_number(value: Any, cast: Any) -> Any:
    if value is None:
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def enrichment_settings() -> dict[str, Any]:
    """Resolve enrichment bounds: env var > config/feed.yaml `llm:` block > default.

    Env wins so a runaway job can be stopped without editing committed config.
    """
    cfg = _load_feed_config().get("llm") or {}
    max_items = _coalesce(
        _as_number(os.environ.get("FEED_LLM_MAX_ITEMS_PER_RUN"), int),
        _as_number(cfg.get("max_items_per_run"), int),
        DEFAULT_MAX_ITEMS_PER_RUN,
    )
    budget = _coalesce(
        _as_number(os.environ.get("FEED_LLM_DAILY_BUDGET_USD"), float),
        _as_number(cfg.get("daily_budget_usd"), float),
        DEFAULT_DAILY_BUDGET_USD,
    )
    return {
        "enabled": _coalesce(
            _as_bool(os.environ.get("FEED_LLM_ENRICHMENT_ENABLED")),
            _as_bool(cfg.get("enabled")),
            DEFAULT_ENRICHMENT_ENABLED,
        ),
        "max_items_per_run": max(0, int(max_items)),
        "daily_budget_usd": max(0.0, float(budget)),
    }


# ── Enrichment cache (fingerprint of the source content) ─────────────────────

def enrichment_fingerprint(item: FeedItem) -> str:
    """Hash of everything that feeds the two prompts.

    If this is unchanged, re-asking the model is guaranteed waste: the prompts
    would be byte-identical. matched_interests is included because it is
    interpolated into the reason prompt.
    """
    basis = "\n".join([
        canonical_url(item.url),
        (item.title or "").strip(),
        (item.source or "").strip(),
        ",".join(sorted(item.matched_interests or [])),
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _load_enrichment_cache() -> dict[str, Any]:
    if not ENRICHMENT_CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(ENRICHMENT_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_enrichment_cache(cache: dict[str, Any]) -> None:
    cutoff = (_now() - dt.timedelta(days=ENRICHMENT_CACHE_TTL_DAYS)).isoformat()
    pruned = {
        fp: entry for fp, entry in cache.items()
        if isinstance(entry, dict) and str(entry.get("ts", "")) >= cutoff
    }
    try:
        FEED_DIR.mkdir(parents=True, exist_ok=True)
        ENRICHMENT_CACHE_PATH.write_text(json.dumps(pruned, indent=2), encoding="utf-8")
    except OSError:
        pass  # caching is an optimization; never break a feed refresh over it


def _log_enrichment(fingerprint: str, item: FeedItem, action: str,
                    detail: str | None = None) -> None:
    """Append one line per item decision. Skips are recorded, not inferred."""
    row = {
        "ts": _now().isoformat(),
        "job_id": ENRICHMENT_JOB_ID,
        "fingerprint": fingerprint,
        "url": item.url,
        "action": action,  # enriched | unchanged | item_limit | budget | disabled | error
        "detail": detail,
    }
    try:
        FEED_DIR.mkdir(parents=True, exist_ok=True)
        with ENRICHMENT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


# ── Daily spend (reads the Phase 0 ledger; never estimates) ──────────────────

def _budget_enforceable(model: str) -> bool:
    """A budget can only bind if the model has a price.

    With an unpriced model (ollama, gemini, alibaba) the ledger records cost as
    unknown by design. Counting those as $0 would let an unlimited number of
    calls pass a budget check, which is worse than saying the check cannot run.
    """
    from . import llm_ops

    return model in llm_ops.PRICING


def _spend_today() -> float:
    """Known feed_llm cost recorded so far today, from the usage ledger."""
    from . import llm_ops

    today = _now().strftime("%Y-%m-%d")
    total = 0.0
    for row in llm_ops.read_usage():
        if row.get("job_id") != ENRICHMENT_JOB_ID or not row.get("cost_known"):
            continue
        if str(row.get("ts", "")).startswith(today):
            total += row.get("cost_usd") or 0.0
    return round(total, 6)


@dataclass
class EnrichmentStats:
    """Per-run accounting for the feed's LLM enrichment pass."""
    enabled: bool = True
    considered: int = 0
    already_summarized: int = 0
    enriched: int = 0
    cache_hits: int = 0
    skipped_item_limit: int = 0
    skipped_budget: int = 0
    failed: int = 0
    llm_calls: int = 0
    max_items_per_run: int = 0
    daily_budget_usd: float = 0.0
    budget_enforceable: bool = False
    spend_usd_at_start: float = 0.0
    spend_usd_at_end: float = 0.0
    no_credentials: bool = False

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


_LAST_ENRICHMENT_STATS = EnrichmentStats()


def last_enrichment_stats() -> EnrichmentStats:
    """Stats from the most recent enrichment pass in this process."""
    return _LAST_ENRICHMENT_STATS


def _summarize_top(items: list[FeedItem], profile: dict[str, Any], topic: str | None = None) -> list[FeedItem]:
    """Write LLM summaries + reason strings for items, under hard bounds.

    Bounds, in the order they are applied per item:
      1. an item that already has a summary is left alone;
      2. a cache hit on the content fingerprint is reused — no LLM call;
      3. `FEED_LLM_MAX_ITEMS_PER_RUN` caps how many items may hit the provider;
      4. `FEED_LLM_DAILY_BUDGET_USD` stops the run once today's recorded spend
         reaches it (only when the model is priced — see `_budget_enforceable`).

    Cache hits do not consume the per-run item cap: they cost nothing. The cap
    counts *attempts*, including failed ones, because a failed call still costs
    quota.

    Every skip is written to the enrichment log with its reason. A failure on
    one item never propagates — the item keeps its deterministic ranker reason
    and an empty summary, and the run continues.
    """
    global _LAST_ENRICHMENT_STATS

    settings = enrichment_settings()
    stats = EnrichmentStats(
        enabled=bool(settings["enabled"]),
        considered=len(items),
        max_items_per_run=settings["max_items_per_run"],
        daily_budget_usd=settings["daily_budget_usd"],
    )
    _LAST_ENRICHMENT_STATS = stats

    if not stats.enabled:
        for item in items:
            _log_enrichment(enrichment_fingerprint(item), item, "disabled")
        return items

    from agent.config import AgentConfig

    config = AgentConfig.load()
    if not config.api_key and config.provider != "ollama":
        # Ollama local needs no key; cloud models need a key.
        stats.no_credentials = True
        return items

    stats.budget_enforceable = _budget_enforceable(config.model)
    spent = _spend_today() if stats.budget_enforceable else 0.0
    stats.spend_usd_at_start = spent
    stats.spend_usd_at_end = spent

    cache = _load_enrichment_cache()
    cache_dirty = False
    attempts = 0

    for item in items:
        if item.summary:
            stats.already_summarized += 1
            continue

        fingerprint = enrichment_fingerprint(item)
        cached = cache.get(fingerprint)
        if isinstance(cached, dict) and cached.get("summary"):
            item.summary = cached["summary"]
            if cached.get("reason"):
                item.reason = cached["reason"]
            stats.cache_hits += 1
            _log_enrichment(fingerprint, item, "unchanged")
            continue

        if attempts >= stats.max_items_per_run:
            stats.skipped_item_limit += 1
            _log_enrichment(fingerprint, item, "item_limit")
            continue

        if stats.budget_enforceable and spent >= stats.daily_budget_usd:
            stats.skipped_budget += 1
            _log_enrichment(
                fingerprint, item, "budget",
                detail=f"spent={spent:.6f} budget={stats.daily_budget_usd:.6f}",
            )
            continue

        attempts += 1
        try:
            stats.llm_calls += 1  # counted before the call: a failure still costs quota
            summary = (_llm_summary(item, profile, topic=topic, config=config) or "").strip()
            if not summary:
                raise EnrichmentEmpty("provider returned an empty summary")
            item.summary = summary

            # A reason failure is survivable on its own: the ranker already put
            # a deterministic reason on the item, so we keep that rather than
            # blanking it.
            reason = ""
            try:
                stats.llm_calls += 1
                reason = (_llm_reason(item, topic=topic, config=config) or "").strip()
            except Exception as exc:  # noqa: BLE001 — one item must not fail the run
                _log_enrichment(fingerprint, item, "error",
                                detail=f"reason: {type(exc).__name__}: {exc}"[:300])
            if reason:
                item.reason = reason

            cache[fingerprint] = {
                "ts": _now().isoformat(),
                "summary": item.summary,
                "reason": reason,
                "model": config.model,
            }
            cache_dirty = True
            stats.enriched += 1
            _log_enrichment(fingerprint, item, "enriched")
        except Exception as exc:  # noqa: BLE001 — one item must not fail the run
            stats.failed += 1
            _log_enrichment(fingerprint, item, "error",
                            detail=f"{type(exc).__name__}: {exc}"[:300])
        finally:
            if stats.budget_enforceable:
                spent = _spend_today()
                stats.spend_usd_at_end = spent

    if cache_dirty:
        _save_enrichment_cache(cache)
    return items


def _llm_summary(item: FeedItem, profile: dict[str, Any], topic: str | None, config: Any) -> str:
    prompt = (
        f"Summarize this article in 1-2 sentences for a {profile.get('tone', 'practical developer audience')}. "
        f"Be specific, not hypey.\n\nTitle: {item.title}\nSource: {item.source}\nURL: {item.url}"
    )
    return _llm_chat(prompt, config)


def _llm_reason(item: FeedItem, topic: str | None, config: Any) -> str:
    interest_list = ", ".join(item.matched_interests) or "general audience"
    prompt = (
        f"In one short sentence, explain why this article matters to someone interested in {interest_list}. "
        f"Title: {item.title}\nSummary: {item.summary}"
    )
    return _llm_chat(prompt, config)


def _llm_chat(prompt: str, config: Any) -> str:
    """Minimal chat call through the configured provider, via the shared client.

    Instrumented through agent.llm_ops so the call lands in the usage ledger
    (Phase 0.5). Payload is byte-identical to the previous hand-rolled request:
    same model, 256 max_tokens, temperature 0.4, 60s timeout, no json mode.

    NOTE: the previous implementation referenced `requests` without importing
    it, so every call raised NameError and the caller's bare `except Exception:
    pass` swallowed it — feed items silently had no LLM summary or reason. This
    routing fixes that as a side effect.
    """
    from . import llm_ops

    result = llm_ops.chat(
        [{"role": "user", "content": prompt}],
        model=config.model,
        temperature=0.4,
        max_tokens=256,
        timeout=60,
        base_url=(config.base_url or "https://api.openai.com/v1"),
        api_key=(config.api_key or ""),
        job_id="feed_llm",
    )
    result.raise_for_status()
    return result.text


# ── Output / persistence ────────────────────────────────────────────────────

def save_feed(items: list[FeedItem], path: Path | None = None) -> Path:
    if path is None:
        today = _now().strftime("%Y-%m-%d")
        path = FEED_DIR / f"{today}.json"
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": _now().isoformat(),
        "count": len(items),
        "items": [item.to_dict() for item in items],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def print_feed(items: list[FeedItem]) -> None:
    if not items:
        print("No new feed items found.")
        return
    print(f"\n📰 smkit feed — {len(items)} items\n")
    for idx, item in enumerate(items, 1):
        print(f"{idx}. {item.title}")
        print(f"   Source: {item.source}  |  Score: {item.score:.2f}")
        print(f"   URL: {item.url}")
        if item.matched_interests:
            print(f"   Interests: {', '.join(item.matched_interests)}")
        if item.summary:
            print(f"   Summary: {item.summary}")
        if item.reason:
            print(f"   Why it matters: {item.reason}")
        print()


# ── Notification ───────────────────────────────────────────────────────────

def notify_feed(items: list[FeedItem], channel: str | None = None, profile_name: str = "default", dry_run: bool = True) -> dict[str, Any]:
    profile = load_profile_with_interests(profile_name)
    channel = channel or get_notification_channel(profile) or "telegram"
    top = items[:NOTIFY_TOP_N]
    if not top:
        return {"ok": True, "channel": channel, "sent": 0, "message": "No items to notify."}
    lines = ["📰 Your personalized smkit feed"]
    for idx, item in enumerate(top, 1):
        lines.append(f"\n{idx}. {item.title}\n   {item.url}\n   Score: {item.score:.2f}")
        if item.summary:
            lines.append(f"   {item.summary}")
    message = "\n".join(lines)
    if dry_run:
        return {"ok": True, "channel": channel, "sent": len(top), "dry_run": True, "message": message}

    if channel.lower() in ("telegram", "tg"):
        from scripts.telegram_poster import post_message

        result = post_message(message)
        return {"ok": bool(result), "channel": channel, "sent": len(top), "message": message[:200]}
    return {"ok": False, "channel": channel, "sent": 0, "error": f"Unsupported channel: {channel}"}


# ── Social post draft ────────────────────────────────────────────────────────

def post_feed(items: list[FeedItem], profile_name: str = "default", dry_run: bool = True) -> dict[str, Any]:
    """Draft a social post from the top feed item using the existing smkit pipeline."""
    if not items:
        return {"ok": True, "dry_run": dry_run, "message": "No feed items to post."}
    top = items[0]
    # Run the existing `smkit run` flow for the top story topic.
    import subprocess

    cmd = [sys.executable, "-m", "agent.cli", "run", "--topic", top.title, "--profile", profile_name]
    if dry_run:
        cmd.append("--dry-run")
    else:
        cmd.append("--yes")
    try:
        result = subprocess.run(cmd, cwd=KIT, capture_output=True, text=True, timeout=300)
        return {
            "ok": result.returncode == 0,
            "dry_run": dry_run,
            "topic": top.title,
            "url": top.url,
            "stdout": result.stdout[-800:],
            "stderr": result.stderr[-400:],
        }
    except Exception as exc:
        return {"ok": False, "dry_run": dry_run, "error": str(exc)}


# ── Doctor checks ───────────────────────────────────────────────────────────

def doctor_feed() -> dict[str, Any]:
    from scripts.feed_sources import source_status

    return {
        "feed_dir": FEED_DIR.exists(),
        "seen_store": SEEN_PATH.exists(),
        "sources": source_status(),
    }
