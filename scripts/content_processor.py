#!/usr/bin/env python3
"""Content Processor — Transform raw research into publish-ready content.

Pipeline: raw research JSON → draft article → formatted for blog + social media.
"""
import argparse
import json
import os
import re
from datetime import date


def load_research(filepath):
    """Load research results from JSON."""
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def generate_slug(title):
    """Generate a URL-safe slug from a title."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug[:80]


def extract_key_points(content, max_points=5):
    """Extract key points from article content (simple heuristic)."""
    if not content or content.startswith("[Extraction failed"):
        return []

    # Split into sentences, pick ones that look like claims or facts
    sentences = re.split(r"[.!?]\s+", content)
    points = []
    for s in sentences:
        s = s.strip()
        if len(s) > 30 and len(s) < 200:
            # Heuristic: sentences with numbers, "is", "are", "was" tend to be factual
            if re.search(r"\d+|is |are |was |has |can |will |should ", s, re.I):
                points.append(s)
                if len(points) >= max_points:
                    break
    return points


def generate_article_draft(research, template="tutorial"):
    """Generate a draft article from research data."""
    topic = research.get("topic", "Unknown Topic")
    results = research.get("results", [])
    today = date.today().isoformat()

    slug = generate_slug(topic)
    title = topic.title() if len(topic.split()) <= 6 else topic

    # Extract key points from content
    all_points = []
    sources = []
    for r in results:
        if r.get("content"):
            points = extract_key_points(r["content"])
            all_points.extend(points)
        sources.append({"title": r.get("title", ""), "url": r.get("url", "")})

    # Build article
    if template == "news":
        article = f"""# {title}

*Published {today}*

## Summary

{topic} — here's what you need to know.

## Key Points

"""
        for i, point in enumerate(all_points[:7], 1):
            article += f"{i}. {point}\n\n"

        article += """## What This Means

[Add your analysis here]

## Sources

"""
        for i, src in enumerate(sources, 1):
            article += f"- [{src['title']}]({src['url']})\n"

    elif template == "tutorial":
        article = f"""# {title}

*Published {today}*

## Introduction

{topic} — in this tutorial, we'll walk through the key concepts and build something practical.

## Prerequisites

- A development environment with Python 3.11+
- Basic familiarity with the command line

## Getting Started

[Add setup steps here]

## Step 1: [First Step]

[Add content here — reference your sources]

## Step 2: [Second Step]

[Add content here]

## Step 3: [Third Step]

[Add content here]

## Key Takeaways

"""
        for i, point in enumerate(all_points[:5], 1):
            article += f"{i}. {point}\n"

        article += """
## Sources

"""
        for i, src in enumerate(sources, 1):
            article += f"- [{src['title']}]({src['url']})\n"

    else:  # comparison
        article = f"""# {title}

*Published {today}*

## Overview

{topic} — let's compare the options.

"""
        article += "## Comparison\n\n| Feature | Option A | Option B |\n|---------|----------|----------|\n"
        article += "| [Feature] | [Value] | [Value] |\n\n"

        article += "## Verdict\n\n[Add your recommendation here]\n\n"
        article += "## Sources\n\n"
        for src in sources:
            article += f"- [{src['title']}]({src['url']})\n"

    return {
        "title": title,
        "slug": slug,
        "content": article,
        "template": template,
        "sources": sources,
        "date": today,
    }


def save_draft(draft, output_dir="content/drafts"):
    """Save a draft article to a markdown file."""
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{draft['date']}_{draft['slug']}.md"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(draft["content"])

    print(f"✅ Draft saved: {filepath}")
    return filepath


def generate_social_posts(draft):
    """Generate social media post variants from a draft article."""
    title = draft["title"]
    slug = draft["slug"]
    sources = draft.get("sources", [])
    first_source = sources[0]["url"] if sources else ""

    # Facebook/LinkedIn post (longer, professional)
    fb_post = f"📌 {title}\n\n" + "\n".join(
        f"• {p}" for p in [line.strip() for line in draft["content"].split("\n") if line.strip().startswith(("1.", "2.", "3.", "4.", "5."))][:3]
    )
    if first_source:
        fb_post += f"\n\n🔗 Read more: {first_source}"

    # X/Twitter post (short, punchy)
    x_post = f"{title} — "
    if len(x_post) > 200:
        x_post = x_post[:200] + "…"
    if first_source:
        remaining = 280 - len(x_post) - 2
        x_post += f" {first_source[:remaining]}"

    return {
        "facebook": fb_post,
        "x_twitter": x_post,
        "linkedin": fb_post,  # LinkedIn format similar to Facebook
    }


def main():
    parser = argparse.ArgumentParser(description="Process research into publish-ready content")
    parser.add_argument("input", help="Research JSON file from content_research.py")
    parser.add_argument("--template", "-t", choices=["news", "tutorial", "comparison"],
                      default="tutorial", help="Article template type")
    parser.add_argument("--social", "-s", action="store_true", help="Generate social media posts")
    parser.add_argument("--output", "-o", default="content/drafts", help="Output directory")
    args = parser.parse_args()

    research = load_research(args.input)
    draft = generate_article_draft(research, template=args.template)
    filepath = save_draft(draft, output_dir=args.output)

    if args.social:
        posts = generate_social_posts(draft)
        print("\n📱 Social Posts:\n")
        for platform, post in posts.items():
            print(f"--- {platform.upper()} ---")
            print(post)
            print()

        # Save social posts
        social_dir = os.path.join(args.output, "social")
        os.makedirs(social_dir, exist_ok=True)
        social_path = os.path.join(social_dir, f"{draft['date']}_{draft['slug']}_social.json")
        with open(social_path, "w", encoding="utf-8") as f:
            json.dump(posts, f, indent=2, ensure_ascii=False)
        print(f"✅ Social posts saved: {social_path}")


if __name__ == "__main__":
    main()