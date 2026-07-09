"""Story clustering for smkit feed (Phase 2).

Groups feed items that cover the same underlying story. Two items are in the
same cluster when:
    - their canonical URLs point to the same final domain + path fingerprint,
      OR
    - their titles are sufficiently similar (word overlap), OR
    - they share enough named entities / noun phrases.

Each cluster gets a representative item (best authority + freshness), a
cluster ID, a headline list, and a simple summary structure.

Clustering is optional until wired together in a later phase.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass
class StoryCluster:
    cluster_id: str = ""
    representative: Any | None = None
    items: list[Any] = field(default_factory=list)
    headline: str = ""
    urls: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    earliest: str = ""
    latest: str = ""
    size: int = 0
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "headline": self.headline,
            "urls": self.urls,
            "sources": self.sources,
            "size": self.size,
            "earliest": self.earliest,
            "latest": self.latest,
            "score": round(self.score, 2),
            "items": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.items
            ],
            "representative": (
                self.representative.to_dict()
                if self.representative and hasattr(self.representative, "to_dict")
                else (dict(self.representative) if self.representative else None)
            ),
        }


# ── URL normalization for clustering ────────────────────────────────────────

def cluster_url_key(url: str) -> str:
    """Create a dedupe/cluster key from a URL.

    Strips scheme, www, query params, and trailing index-ish paths so that
    tracking variants of the same article collapse.
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower().rstrip("/")
    # Collapse common suffixes that don't distinguish stories.
    path = re.sub(r"/(index\.html?|default\.html?|)$", "", path)
    # Keep only the first 3 path segments for clustering; stories rarely differ
    # deeper than that, and this makes variants cluster together.
    parts = [p for p in path.split("/") if p][:3]
    return f"{netloc}/{'/'.join(parts)}"


def canonical_host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


# ── Text similarity for clustering ───────────────────────────────────────────

def normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _core_terms(text: str) -> set[str]:
    """Extract meaningful terms, allowing known short tech tokens like 'ai', 'go', 'api'."""
    stop = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "can", "this", "that",
        "these", "those", "it", "its", "as", "new", "latest", "news", "today",
        "for", "with", "the",
    }
    tokens = []
    for raw in normalize_text(text).split():
        # Keep short tech tokens and numbers; otherwise require length >= 3.
        if raw in {"ai", "go", "api", "ml", "llm", "ui", "ux", "io", "qa", "db"} or raw.isdigit() or len(raw) >= 3:
            tokens.append(raw)
    return {t for t in tokens if t not in stop}


def title_similarity(a: str, b: str) -> float:
    """Normalized meaningful-term overlap, ignoring stop words."""
    words_a = _core_terms(a)
    words_b = _core_terms(b)
    if not words_a or not words_b:
        return 0.0
    inter = words_a & words_b
    union = words_a | words_b
    return len(inter) / len(union)


def shared_bigrams(a: str, b: str) -> float:
    """Measure of phrase overlap using adjacent word pairs."""
    def bigrams(text: str) -> set[tuple[str, str]]:
        words = [w for w in normalize_text(text).split() if len(w) >= 3]
        return set(zip(words, words[1:]))

    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / max(len(ba), len(bb))


def should_cluster(a: "StoryCluster | Any", b: "StoryCluster | Any") -> bool:
    """Determine if two items/clusters belong to the same story cluster."""
    # Normalize: if passed a cluster, use its representative; otherwise treat as item.
    item_a = a.representative if isinstance(a, StoryCluster) else a
    item_b = b.representative if isinstance(b, StoryCluster) else b

    url_a, url_b = getattr(item_a, "url", ""), getattr(item_b, "url", "")
    title_a, title_b = getattr(item_a, "title", ""), getattr(item_b, "title", "")

    if not url_a or not url_b or not title_a or not title_b:
        return False

    # Same canonical host + first path segments -> same story.
    if cluster_url_key(url_a) == cluster_url_key(url_b):
        return True

    # Strong title similarity -> same story.
    sim = title_similarity(title_a, title_b)
    if sim >= 0.35:
        return True

    # Bigram phrase overlap catches "X acquires Y" style headlines.
    if shared_bigrams(title_a, title_b) >= 0.20:
        return True

    return False


# ── Cluster builder ──────────────────────────────────────────────────────────

def cluster_items(items: list[Any]) -> list[StoryCluster]:
    """Group items into story clusters using single-pass greedy merging."""
    clusters: list[StoryCluster] = []
    for item in items:
        if not getattr(item, "url", None) or not getattr(item, "title", None):
            continue
        merged = False
        for cluster in clusters:
            if should_cluster(cluster, item):
                cluster.items.append(item)
                _update_cluster(cluster)
                merged = True
                break
        if not merged:
            cluster_id = hashlib.sha1(item.url.encode()).hexdigest()[:12]
            cluster = StoryCluster(
                cluster_id=cluster_id,
                representative=item,
                items=[item],
                headline=item.title,
                urls=[item.url],
                sources=[item.source],
                earliest=item.published_at,
                latest=item.published_at,
                size=1,
            )
            clusters.append(cluster)

    for cluster in clusters:
        _pick_representative(cluster)
    return clusters


def _update_cluster(cluster: StoryCluster) -> None:
    """Recompute cluster metadata after adding an item."""
    cluster.urls = list({item.url for item in cluster.items})
    cluster.sources = list({item.source for item in cluster.items})
    cluster.size = len(cluster.items)
    dates = [item.published_at for item in cluster.items if item.published_at]
    if dates:
        cluster.earliest = min(dates)
        cluster.latest = max(dates)
    # Use the most common title-ish phrase as headline (simple: most frequent title).
    from collections import Counter

    titles = [item.title for item in cluster.items]
    cluster.headline = Counter(titles).most_common(1)[0][0]


def _pick_representative(cluster: StoryCluster) -> None:
    """Pick the best item to represent the cluster: highest authority, then freshness."""
    from agent.feed_authority import item_authority
    from scripts.feed_ranker import _freshness_score

    best = None
    best_score = -1.0
    for item in cluster.items:
        breakdown = item_authority(item.url, item.source)
        auth = breakdown.final_score
        fresh = _freshness_score(item.published_at)
        score = 0.6 * auth + 0.4 * fresh
        if score > best_score:
            best_score = score
            best = item
    cluster.representative = best or cluster.items[0]
    # Cluster score = representative authority + coverage bonus.
    cluster.score = round(best_score + 0.05 * min(cluster.size, 5), 2)


# ── Cluster summary / debugging ─────────────────────────────────────────────

def summarize_clusters(clusters: list[StoryCluster]) -> list[dict[str, Any]]:
    """Return lightweight summaries for inspection."""
    return [c.to_dict() for c in sorted(clusters, key=lambda x: x.score, reverse=True)]


def top_clusters(clusters: list[StoryCluster], n: int = 5) -> list[StoryCluster]:
    return sorted(clusters, key=lambda x: x.score, reverse=True)[:n]
