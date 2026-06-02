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
from datetime import datetime, date
from urllib.parse import quote_plus

import requests


def web_search(query, count=10):
    """Search the web using a search API. Falls back to DuckDuckGo HTML."""
    # Try Brave Search API first (set BRAVE_API_KEY in secrets.env)
    api_key = os.environ.get("BRAVE_API_KEY", "")
    if api_key:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            params={"q": query, "count": count},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            results = []
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "source": "brave",
                })
            return results

    # Fallback: DuckDuckGo HTML search
    resp = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    if not resp.ok:
        print(f"❌ Search failed: {resp.status_code}")
        return []

    results = []
    # Parse DDG HTML results
    for match in re.finditer(
        r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>',
        resp.text, re.DOTALL
    ):
        url = match.group(1)
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if url and title and "duckduckgo" not in url.lower():
            results.append({
                "title": title,
                "url": url,
                "description": "",
                "source": "duckduckgo",
            })
    return results[:count]


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