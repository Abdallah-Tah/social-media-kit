#!/usr/bin/env python3
"""Content Research — Search the web for articles, tutorials, and news to process and publish.

Supports:
- Web search for articles and tutorials
- Content extraction and summarization
- Output to JSON for downstream processing
"""
import argparse
import json
import os
import sys
import re
import html
from datetime import datetime, date
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import requests

# A realistic browser UA — DuckDuckGo blocks bare/empty agents.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def web_search(query, count=10):
    """Search the web, trying providers in order until one returns results.

    Order (each is skipped if not configured/available):
      1. Brave    — best quality; needs BRAVE_API_KEY
      2. SearXNG  — free, no key; set SEARXNG_URL (self-host or any instance)
      3. DuckDuckGo — free, no key, but best-effort (can be rate-limited)
      4. Wikipedia — free, no key, always available (fallback grounding)

    Force one with SEARCH_PROVIDER=brave|searxng|duckduckgo|wikipedia.
    """
    providers = {
        "brave": _search_brave,
        "searxng": _search_searxng,
        "duckduckgo": _search_duckduckgo,
        "wikipedia": _search_wikipedia,
    }
    forced = os.environ.get("SEARCH_PROVIDER", "").strip().lower()
    order = [forced] if forced in providers else [
        "brave", "searxng", "duckduckgo", "wikipedia"
    ]

    for name in order:
        results = providers[name](query, count)
        if results:
            return results[:count]

    print("❌ Search returned no results from any provider.")
    return []


def _search_brave(query, count):
    api_key = os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            params={"q": query, "count": count},
            timeout=15,
        )
        if not resp.ok:
            return []
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "source": "brave",
            }
            for item in resp.json().get("web", {}).get("results", [])
        ]
    except requests.RequestException:
        return []


def _search_searxng(query, count):
    """Free, no-key web search via a SearXNG instance (JSON API).

    Set SEARXNG_URL to your instance (self-hosted is most reliable), e.g.
    https://searxng.example.com. Public instances often enable JSON output.
    """
    base = os.environ.get("SEARXNG_URL", "").rstrip("/")
    if not base:
        return []
    try:
        resp = requests.get(
            f"{base}/search",
            params={"q": query, "format": "json", "safesearch": 1},
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=15,
        )
        if not resp.ok:
            return []
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for item in data.get("results", []):
        url = item.get("url", "")
        title = (item.get("title") or "").strip()
        if url and title:
            results.append({
                "title": title,
                "url": url,
                "description": (item.get("content") or "")[:300],
                "source": "searxng",
            })
            if len(results) >= count:
                break
    return results


def _search_wikipedia(query, count):
    """Free, no-key fallback search using the Wikipedia API (always available)."""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "list": "search", "srsearch": query,
                "srlimit": count, "format": "json",
            },
            headers={"User-Agent": _UA},
            timeout=15,
        )
        if not resp.ok:
            return []
        hits = resp.json().get("query", {}).get("search", [])
    except (requests.RequestException, ValueError):
        return []

    results = []
    for hit in hits:
        title = hit.get("title", "")
        if not title:
            continue
        snippet = html.unescape(re.sub(r"<[^>]+>", "", hit.get("snippet", "")))
        results.append({
            "title": title,
            "url": "https://en.wikipedia.org/wiki/" + quote_plus(title.replace(" ", "_")),
            "description": snippet,
            "source": "wikipedia",
        })
    return results


def _ddg_decode(href):
    """DuckDuckGo wraps result URLs as //duckduckgo.com/l/?uddg=<encoded>."""
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href or href.startswith("/l/"):
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs:
            return unquote(qs["uddg"][0])
    return href


def _search_duckduckgo(query, count):
    """Scrape DuckDuckGo's HTML/lite endpoints, decoding redirect links."""
    results = []
    seen = set()
    for url in ("https://html.duckduckgo.com/html/", "https://lite.duckduckgo.com/lite/"):
        try:
            resp = requests.post(
                url, data={"q": query}, headers={"User-Agent": _UA}, timeout=15
            )
        except requests.RequestException:
            continue
        if not resp.ok:
            continue

        # Prefer the precise result anchor class; fall back to all anchors.
        anchors = re.findall(
            r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            resp.text, re.DOTALL,
        )
        if not anchors:
            anchors = re.findall(
                r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.DOTALL
            )

        for href, raw_title in anchors:
            target = _ddg_decode(href)
            if not target.startswith("http"):
                continue
            if "duckduckgo.com" in urlparse(target).netloc:
                continue
            title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            if not title or target in seen:
                continue
            seen.add(target)
            results.append(
                {"title": title, "url": target, "description": "", "source": "duckduckgo"}
            )
            if len(results) >= count:
                return results
        if results:
            return results
    return results


def extract_article(url, max_chars=5000):
    """Extract readable text from a URL."""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()

        # Remove HTML tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.S | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        return text[:max_chars]
    except Exception as e:
        return f"[Extraction failed: {e}]"


def research_topic(topic, count=5, extract=False):
    """Search for a topic and optionally extract article content."""
    print(f"🔍 Researching: {topic}")
    results = web_search(topic, count=count)

    if not results:
        print("No results found.")
        return []

    print(f"Found {len(results)} results:\n")

    for i, result in enumerate(results, 1):
        print(f"{i}. {result['title']}")
        print(f"   {result['url']}")
        if result.get("description"):
            print(f"   {result['description'][:120]}...")
        print()

        if extract:
            result["content"] = extract_article(result["url"])
            print(f"   Content extracted: {len(result['content'])} chars\n")

    return results


def save_results(results, topic, output_dir="content/raw"):
    """Save research results to a JSON file."""
    os.makedirs(output_dir, exist_ok=True)
    today = date.today().isoformat()
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    filename = f"{today}_{slug}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            "topic": topic,
            "date": today,
            "results": results,
        }, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved to {filepath}")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Research content for articles and tutorials")
    parser.add_argument("topic", help="Search topic/query")
    parser.add_argument("--count", "-n", type=int, default=5, help="Number of results")
    parser.add_argument("--extract", "-e", action="store_true", help="Extract article content")
    parser.add_argument("--save", "-s", action="store_true", help="Save results to JSON")
    parser.add_argument("--output", "-o", default="content/raw", help="Output directory")
    args = parser.parse_args()

    results = research_topic(args.topic, count=args.count, extract=args.extract)

    if args.save and results:
        save_results(results, args.topic, output_dir=args.output)


if __name__ == "__main__":
    main()