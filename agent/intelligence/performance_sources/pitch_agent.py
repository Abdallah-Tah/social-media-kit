"""Pitch Agent / World Cup performance collector for the Content Intelligence Engine."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PERFORMANCE_DIR = Path.home() / ".openclaw" / "workspace" / "performance"


@dataclass
class PitchAgentPost:
    title: str = ""
    platform: str = ""
    url: str = ""
    published_at: str | None = None
    match_name: str = ""
    content_type: str = "generic_sports_content"  # classification
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    subscribers_gained: int = 0
    watch_time: float = 0.0
    average_view_duration: float = 0.0
    click_throughs_to_website: int = 0
    tutorial_clicks: int = 0
    source_file: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_technical(self) -> bool:
        return self.content_type in {
            "software_build_log",
            "automation_pipeline",
            "analytics_explainer",
        }


# Keywords used to classify Pitch Agent posts.
TECHNICAL_CLASSIFIERS = {
    "software_build_log": [
        "build", "code", "render", "pipeline", "remotion", "ffmpeg", "deploy",
        "architecture", "technical", "how i built", "behind the scenes",
    ],
    "automation_pipeline": [
        "automation", "pipeline", "cron", "workflow", "bot", "telegram",
        "schedule", "approval", "self-hosted", "self hosted",
    ],
    "analytics_explainer": [
        "analytics", "data", "prediction", "model", "algorithm", "odds",
        "metrics", "retention", "ctr", "click-through", "engagement",
    ],
}

GENERIC_SPORTS_MARKERS = [
    "prediction", "who wins", "match preview", "recap", "highlights",
    "score", "goal", "betting", "odds", "pick", "best bet",
]

GAMBLING_GUARD_KEYWORDS = [
    "bet", "betting", "gamble", "gambling", "odds", "stake", "wager",
    "bookmaker", "payout", "parlay",
]


def _parse_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return value


def classify_pitch_post(title: str, summary: str = "") -> str:
    """Classify a Pitch Agent / World Cup post by technical vs generic sports angle."""
    text = f"{title} {summary}".lower()

    for ctype, keywords in TECHNICAL_CLASSIFIERS.items():
        if any(kw in text for kw in keywords):
            return ctype

    if any(kw in text for kw in GENERIC_SPORTS_MARKERS):
        return "generic_sports_content"

    return "prediction_card"


def contains_gambling_language(title: str, summary: str = "") -> bool:
    text = f"{title} {summary}".lower()
    return any(kw in text for kw in GAMBLING_GUARD_KEYWORDS)


def _load_pitch_agent_posts_json(path: Path) -> list[PitchAgentPost]:
    """Load Pitch Agent post metadata from JSON."""
    posts: list[PitchAgentPost] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return posts
    if not isinstance(raw, list):
        return posts
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = item.get("title", "")
        content_type = item.get("content_type") or classify_pitch_post(
            title, item.get("summary", "")
        )
        if contains_gambling_language(title, item.get("summary", "")):
            content_type = "generic_sports_content"
        posts.append(
            PitchAgentPost(
                title=title,
                platform=item.get("platform", ""),
                url=item.get("url", ""),
                published_at=_parse_iso(item.get("published_at")),
                match_name=item.get("match_name", ""),
                content_type=content_type,
                views=int(item.get("views", 0) or 0),
                likes=int(item.get("likes", 0) or 0),
                comments=int(item.get("comments", 0) or 0),
                shares=int(item.get("shares", 0) or 0),
                saves=int(item.get("saves", 0) or 0),
                subscribers_gained=int(item.get("subscribers_gained", 0) or 0),
                watch_time=float(item.get("watch_time", 0) or 0),
                average_view_duration=float(item.get("average_view_duration", 0) or 0),
                click_throughs_to_website=int(item.get("click_throughs_to_website", 0) or 0),
                tutorial_clicks=int(item.get("tutorial_clicks", 0) or 0),
                source_file=str(path),
                metadata=item,
            )
        )
    return posts


def _load_csv_metrics(path: Path) -> list[PitchAgentPost]:
    """Load metrics from a CSV file with column headers matching PitchAgentPost fields."""
    posts: list[PitchAgentPost] = []
    if not path.exists():
        return posts
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                title = row.get("title", "")
                content_type = row.get("content_type") or classify_pitch_post(title)
                if contains_gambling_language(title):
                    content_type = "generic_sports_content"
                posts.append(
                    PitchAgentPost(
                        title=title,
                        platform=row.get("platform", ""),
                        url=row.get("url", ""),
                        published_at=_parse_iso(row.get("published_at")),
                        match_name=row.get("match_name", ""),
                        content_type=content_type,
                        views=int(row.get("views", 0) or 0),
                        likes=int(row.get("likes", 0) or 0),
                        comments=int(row.get("comments", 0) or 0),
                        shares=int(row.get("shares", 0) or 0),
                        saves=int(row.get("saves", 0) or 0),
                        subscribers_gained=int(row.get("subscribers_gained", 0) or 0),
                        watch_time=float(row.get("watch_time", 0) or 0),
                        average_view_duration=float(row.get("average_view_duration", 0) or 0),
                        click_throughs_to_website=int(row.get("click_throughs_to_website", 0) or 0),
                        tutorial_clicks=int(row.get("tutorial_clicks", 0) or 0),
                        source_file=str(path),
                    )
                )
    except Exception:
        pass
    return posts


def collect_pitch_agent_metrics(
    performance_dir: Path | None = None,
) -> list[PitchAgentPost]:
    """Collect all Pitch Agent / World Cup performance metrics from the workspace."""
    directory = performance_dir or PERFORMANCE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    posts: list[PitchAgentPost] = []

    # JSON source.
    json_path = directory / "pitch_agent_posts.json"
    if json_path.exists():
        posts.extend(_load_pitch_agent_posts_json(json_path))

    # CSV sources.
    for csv_name in ["youtube_shorts_metrics.csv", "website_traffic.csv", "social_metrics.csv"]:
        csv_path = directory / csv_name
        if csv_path.exists():
            posts.extend(_load_csv_metrics(csv_path))

    return posts


def _fit_score(post: PitchAgentPost) -> int:
    """Score how well a single post serves BuildWithAbdallah goals."""
    score = 0

    # Technical content alignment is the strongest signal.
    if post.is_technical:
        score += 40

    # Conversion signals.
    if post.click_throughs_to_website > 0:
        score += min(post.click_throughs_to_website * 5, 25)
    if post.tutorial_clicks > 0:
        score += min(post.tutorial_clicks * 8, 30)
    if post.subscribers_gained > 0:
        score += min(post.subscribers_gained * 5, 20)

    # Engagement quality.
    if post.comments > 0 and post.is_technical:
        score += 10
    if post.saves > 0 and post.is_technical:
        score += 10

    # Penalize gambling language.
    if contains_gambling_language(post.title):
        score -= 50

    return max(0, min(score, 100))


def _compute_decision(posts: list[PitchAgentPost]) -> tuple[str, str]:
    """Return a recommendation (YES / NO / CONDITIONAL) and reason."""
    if not posts:
        return "NO DATA", "No Pitch Agent / World Cup metrics loaded."

    technical_posts = [p for p in posts if p.is_technical]
    generic_posts = [p for p in posts if not p.is_technical]

    total_views = sum(p.views for p in posts)
    total_subscribers = sum(p.subscribers_gained for p in posts)
    total_website_clicks = sum(p.click_throughs_to_website for p in posts)
    total_tutorial_clicks = sum(p.tutorial_clicks for p in posts)

    technical_views = sum(p.views for p in technical_posts)
    generic_views = sum(p.views for p in generic_posts)

    # Continue if technical content shows conversion or strong views.
    if technical_posts:
        if total_website_clicks > 0 or total_tutorial_clicks > 0:
            return "YES", (
                f"Technical World Cup posts drove {total_website_clicks} website clicks "
                f"and {total_tutorial_clicks} tutorial clicks."
            )
        if technical_views >= generic_views and total_subscribers > 0:
            return "YES", (
                f"Technical posts ({technical_views} views) matched or beat generic posts "
                f"({generic_views} views) and gained {total_subscribers} subscribers."
            )
        if total_subscribers > 0:
            return "CONDITIONAL", (
                f"Gained {total_subscribers} subscribers, but technical posts need stronger "
                "website/tutorial conversion. Reframe toward software/automation angles."
            )

    # If only generic sports content exists and no conversion.
    if generic_posts and not technical_posts:
        if total_website_clicks == 0 and total_tutorial_clicks == 0:
            return "STOP OR REDUCE", (
                "Only generic sports content with no BWA conversion. World Cup is not growing "
                "the core audience."
            )

    if total_views == 0:
        return "STOP OR REDUCE", "No meaningful views detected."

    return "CONDITIONAL", (
        "Some views but weak BWA conversion. Double down on technical build-log and "
        "pipeline content."
    )


@dataclass
class PitchAgentPerformanceSummary:
    posts: list[PitchAgentPost]
    recommendation: str = ""
    reason: str = ""
    technical_conversion_rate: float = 0.0
    website_ctr: float = 0.0
    subscriber_conversion_rate: float = 0.0
    best_posts: list[PitchAgentPost] = field(default_factory=list)
    worst_posts: list[PitchAgentPost] = field(default_factory=list)


def summarize_pitch_agent_metrics(posts: list[PitchAgentPost]) -> PitchAgentPerformanceSummary:
    """Summarize Pitch Agent / World Cup metrics for reporting."""
    summary = PitchAgentPerformanceSummary(posts=posts)
    if not posts:
        summary.recommendation, summary.reason = _compute_decision(posts)
        return summary

    total_views = sum(p.views for p in posts) or 1
    total_subscribers = sum(p.subscribers_gained for p in posts)
    total_website_clicks = sum(p.click_throughs_to_website for p in posts)
    total_tutorial_clicks = sum(p.tutorial_clicks for p in posts)

    summary.website_ctr = total_website_clicks / total_views
    summary.subscriber_conversion_rate = total_subscribers / total_views
    summary.technical_conversion_rate = (
        total_tutorial_clicks / total_views
        if total_tutorial_clicks > 0
        else summary.website_ctr
    )

    # Add fit score to each post and sort.
    for post in posts:
        post.metadata["fit_score"] = _fit_score(post)
    sorted_desc = sorted(posts, key=lambda p: p.metadata["fit_score"], reverse=True)
    sorted_asc = sorted(posts, key=lambda p: p.metadata["fit_score"])
    summary.best_posts = [p for p in sorted_desc if p.metadata["fit_score"] >= 60][:3]
    summary.worst_posts = [p for p in sorted_asc if p.metadata["fit_score"] < 50][:3]
    if not summary.best_posts:
        summary.best_posts = sorted_desc[:3]
    if not summary.worst_posts:
        summary.worst_posts = sorted_asc[:3]

    summary.recommendation, summary.reason = _compute_decision(posts)
    return summary


def generate_pitch_report(
    posts: list[PitchAgentPost] | None = None,
    report_path: Path | None = None,
) -> Path:
    """Generate the standalone Pitch Agent performance report."""
    if posts is None:
        posts = collect_pitch_agent_metrics()
    summary = summarize_pitch_agent_metrics(posts)
    if report_path is None:
        report_path = PERFORMANCE_DIR / "pitch-agent-performance-report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Pitch Agent / World Cup Performance Report")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    lines.append("## Executive Recommendation")
    lines.append("")
    lines.append(f"**Should Continue?** {summary.recommendation}")
    lines.append("")
    lines.append(f"**Reason:** {summary.reason}")
    lines.append("")

    if posts:
        total_views = sum(p.views for p in posts)
        total_subscribers = sum(p.subscribers_gained for p in posts)
        total_website = sum(p.click_throughs_to_website for p in posts)
        total_tutorial = sum(p.tutorial_clicks for p in posts)
        lines.append("## Key Metrics")
        lines.append("")
        lines.append(f"- **Total posts analyzed:** {len(posts)}")
        lines.append(f"- **Total views:** {total_views}")
        lines.append(f"- **Subscribers gained:** {total_subscribers}")
        lines.append(f"- **Website click-throughs:** {total_website}")
        lines.append(f"- **Tutorial clicks:** {total_tutorial}")
        lines.append(f"- **Website CTR:** {summary.website_ctr:.2%}")
        lines.append(f"- **Subscriber conversion rate:** {summary.subscriber_conversion_rate:.2%}")
        lines.append(f"- **Technical conversion rate:** {summary.technical_conversion_rate:.2%}")
        lines.append("")

        lines.append("## Best-Aligned Posts")
        lines.append("")
        for post in summary.best_posts:
            fit = post.metadata.get("fit_score", 0)
            lines.append(f"### {post.title}")
            lines.append(f"- **Platform:** {post.platform}")
            lines.append(f"- **Type:** {post.content_type}")
            lines.append(f"- **Fit Score:** {fit}/100")
            lines.append(f"- **Views:** {post.views} | **Likes:** {post.likes} | **Comments:** {post.comments}")
            lines.append(f"- **Website clicks:** {post.click_throughs_to_website} | **Tutorial clicks:** {post.tutorial_clicks}")
            lines.append(f"- **URL:** {post.url or 'n/a'}")
            lines.append("")

        lines.append("## Worst-Aligned Posts")
        lines.append("")
        for post in summary.worst_posts:
            fit = post.metadata.get("fit_score", 0)
            lines.append(f"- **{post.title}** ({post.content_type}) — fit {fit}/100, views {post.views}")
        lines.append("")

        lines.append("## Post Breakdown by Type")
        lines.append("")
        by_type: dict[str, list[PitchAgentPost]] = defaultdict(list)
        for post in posts:
            by_type[post.content_type].append(post)
        for ctype, type_posts in sorted(by_type.items()):
            total_type_views = sum(p.views for p in type_posts)
            total_type_subs = sum(p.subscribers_gained for p in type_posts)
            total_type_web = sum(p.click_throughs_to_website for p in type_posts)
            lines.append(
                f"- **{ctype}**: {len(type_posts)} posts, {total_type_views} views, "
                f"{total_type_subs} subscribers, {total_type_web} website clicks"
            )
        lines.append("")
    else:
        lines.append("_No Pitch Agent metrics found. Place data in `~/.openclaw/workspace/performance/`._")
        lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "Technical content types (software_build_log, automation_pipeline, analytics_explainer) "
        "are scored higher than generic sports content. Fit score rewards website clicks, "
        "tutorial clicks, subscriber growth, and engagement on technical posts. Gambling/betting "
        "language is penalized."
    )
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
