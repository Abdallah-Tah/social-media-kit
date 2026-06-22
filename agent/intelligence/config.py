"""Configuration for the Content Intelligence Engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import ROOT

INTELLIGENCE_DIR = ROOT / "content" / "intelligence"
INTELLIGENCE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_REPORT_PATH = INTELLIGENCE_DIR / "content-intelligence-report.md"

# Topics that define the Build With Abdallah brand.
BRAND_TOPICS = {
    "laravel",
    "php",
    "python",
    "ai automation",
    "ai agents",
    "raspberry pi",
    "software engineering",
    "developer tools",
    "real-world engineering",
    "tutorials",
}

# Sources for trend radar.
DEFAULT_REDDIT_SUBREDDITS = [
    "laravel",
    "python",
    "raspberry_pi",
    "selfhosted",
    "programming",
    "webdev",
    "LocalLLaMA",
]

DEFAULT_HACKER_NEWS_QUERIES = [
    "Laravel",
    "Python",
    "Raspberry Pi",
    "AI agent",
    "automation",
]

DEFAULT_GITHUB_TRENDING_TOPICS = [
    "python",
    "php",
    "laravel",
    "raspberry-pi",
    "agent",
    "automation",
]

DEFAULT_NEWSLETTERS = [
    "https://news.ycombinator.com/",
    "https://openai.com/news/",
    "https://www.anthropic.com/news",
    "https://blog.laravel.com/",
    "https://vercel.com/blog",
]


@dataclass
class IntelligenceConfig:
    """Runtime configuration for the intelligence engine."""

    report_path: Path = DEFAULT_REPORT_PATH
    top_n: int = 10
    min_authority_score: int = 50
    dry_run: bool = False
    enable_reddit: bool = True
    enable_hacker_news: bool = True
    enable_github_trending: bool = True
    enable_newsletters: bool = True
    enable_audience_pain: bool = True
    enable_performance: bool = True
    enable_content_gap: bool = True
    enable_pitch_agent: bool = False
    enable_newsletter_mining: bool = False
    audience_live: bool = False
    audience_text: bool = True
    audience_sources: list[str] | None = None
    sitemap_url: str = "https://buildwithabdallah.com/sitemap.xml"
    existing_content_file: str | None = None
    performance_dir: str | None = None
    reddit_subreddits: list[str] = field(default_factory=list)
    hacker_news_queries: list[str] = field(default_factory=list)
    github_trending_topics: list[str] = field(default_factory=list)
    newsletters: list[str] = field(default_factory=list)
    brand_topics: set[str] = field(default_factory=lambda: set(BRAND_TOPICS))

    def __post_init__(self) -> None:
        if not self.reddit_subreddits:
            self.reddit_subreddits = list(DEFAULT_REDDIT_SUBREDDITS)
        if not self.hacker_news_queries:
            self.hacker_news_queries = list(DEFAULT_HACKER_NEWS_QUERIES)
        if not self.github_trending_topics:
            self.github_trending_topics = list(DEFAULT_GITHUB_TRENDING_TOPICS)
        if not self.newsletters:
            self.newsletters = list(DEFAULT_NEWSLETTERS)
