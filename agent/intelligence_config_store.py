"""Persistent overrides for IntelligenceConfig stored in content/intelligence_config.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "content" / "intelligence_config.json"

EDITABLE_FIELDS = {
    "enable_reddit", "enable_hacker_news", "enable_github_trending",
    "enable_newsletters", "enable_newsletter_mining",
    "reddit_subreddits", "hacker_news_queries", "github_trending_topics", "newsletters",
}


def load_config_overrides() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config_overrides(overrides: dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = load_config_overrides()
    for k, v in overrides.items():
        if k in EDITABLE_FIELDS:
            existing[k] = v
    CONFIG_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def get_intelligence_config_dict() -> dict[str, Any]:
    """Return the current IntelligenceConfig merged with persisted overrides."""
    from .intelligence.config import IntelligenceConfig
    cfg = IntelligenceConfig()
    overrides = load_config_overrides()
    for k, v in overrides.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    return {
        "enable_reddit": cfg.enable_reddit,
        "enable_hacker_news": cfg.enable_hacker_news,
        "enable_github_trending": cfg.enable_github_trending,
        "enable_newsletters": cfg.enable_newsletters,
        "enable_newsletter_mining": cfg.enable_newsletter_mining,
        "reddit_subreddits": cfg.reddit_subreddits,
        "hacker_news_queries": cfg.hacker_news_queries,
        "github_trending_topics": cfg.github_trending_topics,
        "newsletters": cfg.newsletters,
    }
