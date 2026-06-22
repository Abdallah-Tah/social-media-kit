"""Newsletter and release mining for the Content Intelligence Engine.

Phase 1 scope:
- Parse RSS/Atom feeds, HTML pages, and JSON endpoints.
- Score each item against the BuildWithAbdallah knowledge base.
- Classify suggested action (tutorial, short, newsletter, skip).
- Produce a ranked list and a markdown report.
- Never write articles.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
import yaml

from .knowledge import KnowledgeBase, load_knowledge_base, match_text_against_knowledge
from .scoring import CONTENT_GUARD_KEYWORDS, score_social_potential, score_tutorial_potential

_NEWSLETTER_SOURCES_PATH = Path(__file__).resolve().parent / "knowledge" / "newsletter_sources.yaml"

NEWSLETTER_ACTIONS = {
    "create_tutorial",
    "create_short",
    "newsletter_note",
    "skip",
    "conditional",
}


@dataclass
class NewsletterSource:
    """A configured source of developer news."""

    name: str
    url: str
    type: str = "rss"
    category: str = "general"
    priority: int = 50
    enabled: bool = True
    selectors: dict[str, str] = field(default_factory=dict)


@dataclass
class NewsletterItem:
    """A single mined newsletter/update item."""

    title: str
    url: str
    source: str
    published_at: str | None = None
    summary: str = ""
    category: str = ""
    detected_technologies: list[str] = field(default_factory=list)
    why_developers_care: str = ""
    possible_bwa_angle: str = ""
    tutorial_potential: int = 0
    urgency_score: int = 0
    knowledge_score: int = 0
    social_potential: int = 0
    action: str = "skip"
    related_projects: list[str] = field(default_factory=list)
    gap_status: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


def load_newsletter_sources(path: Path | None = None) -> list[NewsletterSource]:
    """Load newsletter source configuration from YAML."""
    path = path or _NEWSLETTER_SOURCES_PATH
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = []
    for item in data.get("sources", []):
        sources.append(NewsletterSource(**item))
    return sources


def _fetch_text(url: str, timeout: int = 20) -> str:
    """Fetch raw text from a URL."""
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "smkit-intelligence/1.0"},
        )
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        return f"<!-- fetch-error: {exc} -->"


def _xml_ns(tag: str) -> str:
    """Strip common RSS/Atom namespace prefixes for simpler matching."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _child_text(parent: ET.Element, tag: str, ns: dict[str, str] | None = None) -> str:
    """Get child element text by local tag name across RSS/Atom namespaces."""
    for child in parent:
        local = _xml_ns(child.tag)
        if local == tag:
            return (child.text or "").strip()
    # Fallback to namespaced find if provided.
    if ns:
        child = parent.find(f"ns:{tag}", ns)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def _parse_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return value


def _clean_html(raw: str) -> str:
    """Strip tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_rss_items(source: NewsletterSource, xml_text: str, base_url: str) -> list[NewsletterItem]:
    """Parse RSS/Atom XML into newsletter items."""
    items: list[NewsletterItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    # Detect Atom vs RSS by root tag local name.
    root_tag = _xml_ns(root.tag)
    is_atom = root_tag in {"feed", "entry"}

    # Collect entry/item elements.
    entries: list[ET.Element] = []
    for elem in root.iter():
        if _xml_ns(elem.tag) in {"item", "entry"}:
            entries.append(elem)
    if not entries and is_atom:
        entries = [root]

    for entry in entries:
        title = _child_text(entry, "title")
        link = _child_text(entry, "link")
        if not link:
            # Atom often uses <link href="..." />.
            link_elem = None
            for child in entry:
                if _xml_ns(child.tag) == "link" and child.get("href"):
                    link_elem = child
                    break
            if link_elem is not None:
                link = link_elem.get("href") or ""
        if link and not link.startswith(("http://", "https://")):
            link = urljoin(base_url, link)
        summary = _child_text(entry, "description") or _child_text(entry, "summary") or _child_text(entry, "content")
        summary = _clean_html(summary)
        published = _child_text(entry, "pubDate") or _child_text(entry, "published") or _child_text(entry, "updated")
        published = _parse_iso(published)
        if len(title) < 8:
            continue
        items.append(
            NewsletterItem(
                title=title,
                url=link or base_url,
                source=source.name,
                published_at=published,
                summary=summary[:500],
                category=source.category,
            )
        )
    return items


def _extract_title_links(html: str, base_url: str) -> list[tuple[str, str, str]]:
    """Extract article-like links and their titles from an HTML page."""
    results: list[tuple[str, str, str]] = []
    # Article cards with h2/h3 + anchor.
    for tag in ["h2", "h3", "article"]:
        pattern = rf"<{tag}[^>]*>(.*?)</{tag}>"
        for block in re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL):
            clean = re.sub(r"<[^>]+>", " ", block)
            title_match = re.search(r"<a[^>]+href=\"([^\"]+)\"[^>]*>([^<]+)</a>", block, flags=re.IGNORECASE)
            if title_match:
                href, title = title_match.groups()
                href = urljoin(base_url, href)
                results.append((title.strip(), href, clean.strip()))
    # Fallback: any anchor with text.
    if not results:
        for match in re.finditer(r"<a[^>]+href=\"([^\"]+)\"[^>]*>([^<]{15,120})</a>", html, flags=re.IGNORECASE):
            href, title = match.groups()
            href = urljoin(base_url, href)
            results.append((title.strip(), href, ""))
    return results


def parse_html_items(source: NewsletterSource, html: str, base_url: str) -> list[NewsletterItem]:
    """Parse an HTML newsletter/blog index into items."""
    items: list[NewsletterItem] = []
    entries = _extract_title_links(html, base_url)
    seen: set[str] = set()
    for title, link, summary in entries:
        if link.lower() in seen or len(title) < 15:
            continue
        seen.add(link.lower())
        items.append(
            NewsletterItem(
                title=title,
                url=link,
                source=source.name,
                summary=summary[:400],
                category=source.category,
            )
        )
    return items


def parse_json_items(source: NewsletterSource, json_text: str, base_url: str) -> list[NewsletterItem]:
    """Parse a JSON endpoint into items using configured selectors."""
    items: list[NewsletterItem] = []
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return items

    if not isinstance(data, (list, dict)):
        return items

    entries: list[Any]
    if isinstance(data, list):
        entries = data
    else:
        items_key = source.selectors.get("items", "items")
        entries = data.get(items_key, [])

    title_key = source.selectors.get("title", "title")
    url_key = source.selectors.get("url", "url")
    summary_key = source.selectors.get("summary", "summary")
    date_key = source.selectors.get("date", "date")

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = entry.get(title_key, "")
        link = entry.get(url_key, "")
        summary = entry.get(summary_key, "")
        published = entry.get(date_key)
        if isinstance(link, str) and not link.startswith(("http://", "https://")):
            link = urljoin(base_url, link)
        if not title or len(title) < 8:
            continue
        items.append(
            NewsletterItem(
                title=title,
                url=link or base_url,
                source=source.name,
                published_at=_parse_iso(published) if isinstance(published, str) else None,
                summary=str(summary)[:500],
                category=source.category,
            )
        )
    return items


def fetch_source(source: NewsletterSource) -> list[NewsletterItem]:
    """Fetch and parse a single newsletter source."""
    if not source.enabled:
        return []
    raw = _fetch_text(source.url, timeout=15)
    if raw.startswith("<!-- fetch-error"):
        return []
    source_type = source.type.lower()
    if source_type in {"rss", "atom", "xml"}:
        return parse_rss_items(source, raw, source.url)
    if source_type in {"html", "blog", "page"}:
        return parse_html_items(source, raw, source.url)
    if source_type in {"json", "api"}:
        return parse_json_items(source, raw, source.url)
    # Auto-detect by content sniffing.
    stripped = raw.lstrip()
    if stripped.startswith("<?xml") or stripped.startswith("<rss") or stripped.startswith("<feed"):
        return parse_rss_items(source, raw, source.url)
    if stripped.startswith(("{", "[")):
        return parse_json_items(source, raw, source.url)
    return parse_html_items(source, raw, source.url)


def collect_newsletter_items(sources: list[NewsletterSource] | None = None) -> list[NewsletterItem]:
    """Collect items from all enabled newsletter sources."""
    if sources is None:
        sources = load_newsletter_sources()
    items: list[NewsletterItem] = []
    for source in sources:
        try:
            items.extend(fetch_source(source))
        except Exception:
            continue
    return items


def _detect_technologies(text: str) -> list[str]:
    """Detect BWA-relevant technologies in text."""
    tech_map = {
        "Laravel": ["laravel"],
        "PHP": ["php"],
        "Python": ["python"],
        "Filament": ["filament"],
        "Livewire": ["livewire"],
        "AI agents": ["ai agent", "agentic"],
        "OpenAI": ["openai", "gpt"],
        "Anthropic Claude": ["claude", "anthropic"],
        "n8n": ["n8n"],
        "Raspberry Pi": ["raspberry pi", "rpi"],
        "Remotion": ["remotion"],
        "ffmpeg": ["ffmpeg"],
        "Docker": ["docker"],
        "GitHub Actions": ["github actions"],
        "Next.js": ["next.js", "nextjs"],
        "Vue": ["vue", "nuxt"],
        "React": ["react"],
        "Node.js": ["node", "nodejs"],
        "Local LLMs": ["ollama", "local llm"],
        "SQLite": ["sqlite"],
        "PostgreSQL": ["postgres", "postgresql"],
        "MySQL": ["mysql", "mariadb"],
    }
    lowered = text.lower()
    detected = []
    for tech, markers in tech_map.items():
        if any(m in lowered for m in markers):
            detected.append(tech)
    return detected


def _recency_score(published_at: str | None) -> int:
    """Score recency: 100 if <=1 day, decaying to 0 after ~30 days."""
    if not published_at:
        return 50
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt
        days = delta.total_seconds() / 86400
        if days <= 1:
            return 100
        if days <= 7:
            return 80
        if days <= 14:
            return 60
        if days <= 30:
            return 40
        return 20
    except Exception:
        return 50


def _hype_guard_adjustment(item: NewsletterItem) -> tuple[int, str]:
    """Downrank pure hype / generic AI news with no implementation angle."""
    text = f"{item.title} {item.summary}".lower()
    hype_markers = [
        "announced", "raises", "funding", "acquired", "partnership",
        "executive", "ceo", "cto", "leadership", "venture capital",
    ]
    implementation_markers = [
        "tutorial", "how to", "guide", "build", "deploy", "setup",
        "open source", "self-host", "api", "sdk", "integration",
        "code", "example", "implementation", "release notes", "changelog",
    ]
    hype_hits = sum(1 for m in hype_markers if m in text)
    impl_hits = sum(1 for m in implementation_markers if m in text)

    if hype_hits >= 2 and impl_hits == 0:
        return -25, "Hype-only business news — no implementation angle."

    generic_ai_markers = [r"\bai\b", "artificial intelligence", r"\bllm\b", r"\bmodel\b"]
    if any(re.search(m, text, flags=re.IGNORECASE) for m in generic_ai_markers) and impl_hits == 0:
        return -15, "Generic AI news without a buildable angle."

    guard_hits = [kw for kw in CONTENT_GUARD_KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", text)]
    if guard_hits:
        return -35, f"Guardrail hit: '{', '.join(guard_hits)}' — conflicts with BWA values."

    return 0, ""


def _classify_action(item: NewsletterItem) -> str:
    """Pick suggested action from score profile."""
    if item.tutorial_potential >= 75 and item.knowledge_score >= 50:
        return "create_tutorial"
    if item.tutorial_potential >= 55 and item.knowledge_score >= 35:
        return "create_short"
    if item.knowledge_score >= 25 or item.urgency_score >= 70:
        return "newsletter_note"
    return "skip"


def score_newsletter_items(
    items: list[NewsletterItem],
    kb: KnowledgeBase | None = None,
    existing_content: list[Any] | None = None,
) -> list[NewsletterItem]:
    """Score and classify each mined newsletter item."""
    if kb is None:
        kb = load_knowledge_base()
    scored: list[NewsletterItem] = []
    for item in items:
        text = f"{item.title} {item.summary}"
        knowledge = match_text_against_knowledge(text.lower(), kb)
        item.knowledge_score = knowledge["total_knowledge_score"]
        item.related_projects = knowledge["matched_projects"]
        item.detected_technologies = _detect_technologies(text)

        # Tutorial and social potential.
        pseudo_signal = type("S", (), {"title": item.title, "summary": item.summary, "topics": []})()
        item.tutorial_potential = score_tutorial_potential(pseudo_signal)
        item.social_potential = score_social_potential(pseudo_signal)

        # Urgency combines recency, source priority, knowledge, and tutorial/social.
        recency = _recency_score(item.published_at)
        urgency = int(recency * 0.25 + item.knowledge_score * 0.3 + item.tutorial_potential * 0.2 + item.social_potential * 0.25)
        item.urgency_score = min(urgency, 100)

        # Why developers care.
        item.why_developers_care = _why_developers_care(item, knowledge)
        item.possible_bwa_angle = _possible_bwa_angle(item, knowledge)
        # Content gap status.
        item.gap_status = "unknown"
        if existing_content is not None:
            from .content_gap import detect_content_gap
            gap = detect_content_gap(item.title, item.summary, existing_content)
            item.gap_status = f"{gap.action} (score {gap.gap_score}, risk {gap.duplicate_risk})"

        # Content gap status.
        item.gap_status = "unknown"
        if existing_content is not None:
            from .content_gap import detect_content_gap
            gap = detect_content_gap(item.title, item.summary, existing_content)
            item.gap_status = f"{gap.action} (score {gap.gap_score}, risk {gap.duplicate_risk})"
        item.action = _classify_action(item)

        # Apply guard adjustments.
        penalty, note = _hype_guard_adjustment(item)
        if penalty:
            item.knowledge_score = max(0, item.knowledge_score + int(penalty / 2))
            item.urgency_score = max(0, item.urgency_score + penalty)
            if item.action not in {"skip", "newsletter_note"}:
                item.action = "skip" if penalty <= -25 else item.action
            item.metadata["guard_note"] = note

        scored.append(item)
    return sorted(scored, key=lambda i: i.urgency_score, reverse=True)


def _why_developers_care(item: NewsletterItem, knowledge: dict[str, Any]) -> str:
    """Generate a one-sentence reason developers care."""
    parts = []
    if knowledge.get("expertise_matches"):
        areas = ", ".join({m[0] for m in knowledge["expertise_matches"]})
        parts.append(f"touches {areas}")
    if knowledge.get("stack_matches"):
        stack = ", ".join({m[0] for m in knowledge["stack_matches"]})
        parts.append(f"uses {stack}")
    if not parts and item.detected_technologies:
        parts.append(f"mentions {', '.join(item.detected_technologies[:3])}")
    if not parts:
        parts.append("developer tooling or workflow update")
    return f"Relevant to BWA audience because it {', and '.join(parts)}."


def _possible_bwa_angle(item: NewsletterItem, knowledge: dict[str, Any]) -> str:
    """Suggest an angle Abdallah could take."""
    if item.tutorial_potential >= 75:
        return "Build a step-by-step tutorial with working code on a real project."
    if item.tutorial_potential >= 55:
        return "Create a 60-second Short or quick LinkedIn post showing the new tool in action."
    if knowledge.get("matched_projects"):
        projects = ", ".join(knowledge["matched_projects"][:2])
        return f"Connect to existing BWA projects ({projects}) in a brief newsletter note."
    return "Monitor and skip unless audience demand appears."


def top_newsletter_opportunities(
    limit: int = 20,
    min_score: int = 30,
    sources: list[NewsletterSource] | None = None,
    kb: KnowledgeBase | None = None,
    existing_content: list[Any] | None = None,
) -> list[NewsletterItem]:
    """Collect, score, and return the top newsletter opportunities."""
    items = collect_newsletter_items(sources)
    scored = score_newsletter_items(items, kb, existing_content=existing_content)
    return [i for i in scored if i.urgency_score >= min_score][:limit]


def generate_newsletter_report(
    items: list[NewsletterItem],
    report_path: Path | None = None,
) -> Path:
    """Write a standalone newsletter mining report."""
    if report_path is None:
        report_path = Path.home() / ".openclaw" / "workspace" / "performance" / "newsletter-mining-report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Newsletter / Release Mining Report",
        f"Generated: {now}",
        "",
        "> Intelligence only. No content generated.",
        "",
        f"**Items analyzed:** {len(items)}",
        "",
        "## Top Opportunities",
        "",
    ]
    if not items:
        lines.append("_No newsletter opportunities met the minimum score this run._")
        lines.append("")
    for idx, item in enumerate(items, 1):
        lines.append(f"### {idx}. {item.title}")
        lines.append(f"- **Source:** {item.source}")
        lines.append(f"- **URL:** {item.url}")
        if item.published_at:
            lines.append(f"- **Published:** {item.published_at}")
        lines.append(f"- **Category:** {item.category}")
        lines.append(f"- **Detected Technologies:** {', '.join(item.detected_technologies) or 'none'}")
        lines.append(f"- **Why Developers Care:** {item.why_developers_care}")
        lines.append(f"- **BWA Angle:** {item.possible_bwa_angle}")
        lines.append(f"- **Tutorial Potential:** {item.tutorial_potential}/100")
        lines.append(f"- **Urgency Score:** {item.urgency_score}/100")
        lines.append(f"- **Knowledge Score:** {item.knowledge_score}/100")
        if item.gap_status and item.gap_status != "unknown":
            lines.append(f"- **Content Gap Status:** {item.gap_status}")
        lines.append(f"- **Suggested Action:** {item.action.replace('_', ' ')}")
        if item.related_projects:
            lines.append(f"- **Related BWA Projects:** {', '.join(item.related_projects)}")
        if item.summary:
            lines.append(f"- **Summary:** {item.summary}")
        if item.metadata.get("guard_note"):
            lines.append(f"- **Guard Note:** {item.metadata['guard_note']}")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def items_to_trend_signals(items: list[NewsletterItem]) -> list[Any]:
    """Convert top newsletter items into TrendSignal-compatible objects."""
    from .models import TrendSignal
    signals = []
    for item in items:
        signals.append(
            TrendSignal(
                title=item.title,
                source=f"newsletter:{item.source}",
                url=item.url,
                summary=item.summary,
                topics=item.detected_technologies,
                published=item.published_at,
                raw={"action": item.action, "urgency_score": item.urgency_score},
            )
        )
    return signals
