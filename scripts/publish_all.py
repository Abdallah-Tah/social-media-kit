#!/usr/bin/env python3
"""Multi-Platform Publisher — Publish to blog, Facebook, X, and LinkedIn in one command.

Usage:
    # Publish article to blog + all social platforms
    python scripts/publish_all.py --file article.md --title "My Article"

    # Publish to specific platforms only
    python scripts/publish_all.py --file article.md --title "My Article" --blog --facebook

    # Dry run (preview without publishing)
    python scripts/publish_all.py --file article.md --title "My Article" --dry-run
"""
import argparse
import os
import sys

# Add scripts dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fb_poster import post_text as fb_post
from x_poster import post_tweet as x_post
from linkedin_poster import post_text as linkedin_post
from blog_publisher import publish_article as blog_publish


def read_article(filepath):
    """Read article from markdown file."""
    with open(filepath, encoding="utf-8") as f:
        return f.read()


def main():
    parser = argparse.ArgumentParser(description="Publish to blog + social platforms")
    parser.add_argument("--file", "-f", required=True, help="Markdown article file")
    parser.add_argument("--title", "-t", required=True, help="Article title")
    parser.add_argument("--slug", "-s", help="URL slug (auto-generated if omitted)")
    parser.add_argument("--excerpt", "-e", help="Article excerpt/summary")
    parser.add_argument("--blog", action="store_true", help="Publish to blog")
    parser.add_argument("--facebook", action="store_true", help="Post to Facebook Page")
    parser.add_argument("--x", action="store_true", help="Post to X (Twitter)")
    parser.add_argument("--linkedin", action="store_true", help="Post to LinkedIn")
    parser.add_argument("--all", action="store_true", help="Publish to all platforms")
    parser.add_argument("--dry-run", action="store_true", help="Preview without publishing")
    parser.add_argument("--social-text", help="Override social media post text")
    args = parser.parse_args()

    # Default to all platforms if none specified
    if not any([args.blog, args.facebook, args.x, args.linkedin]):
        args.all = True

    if args.all:
        args.blog = True
        args.facebook = True
        args.x = True
        args.linkedin = True

    content = read_article(args.file)

    # Generate slug
    import re
    slug = args.slug or re.sub(r"[^a-z0-9-]", "", args.title.lower().replace(" ", "-").replace("—", "-"))

    # Social media text
    social_text = args.social_text or f"📌 {args.title}"
    if args.excerpt:
        social_text += f"\n\n{args.excerpt}"

    results = {}

    # ── Blog ───────────────────────────────────────────────────────────────
    if args.blog:
        if args.dry_run:
            print(f"📝 [DRY RUN] Would publish to blog: {args.title}")
            results["blog"] = "dry_run"
        else:
            print(f"📝 Publishing to blog...")
            result = blog_publish(
                title=args.title,
                slug=slug,
                content=content,
                excerpt=args.excerpt or "",
                publish=True,
            )
            results["blog"] = "published" if result else "failed"

    # ── Facebook ───────────────────────────────────────────────────────────
    if args.facebook:
        if args.dry_run:
            print(f"📘 [DRY RUN] Would post to Facebook: {social_text[:100]}...")
            results["facebook"] = "dry_run"
        else:
            print(f"📘 Posting to Facebook...")
            result = fb_post(social_text)
            results["facebook"] = "posted" if result else "failed"

    # ── X (Twitter) ────────────────────────────────────────────────────────
    if args.x:
        # X has 280 char limit
        x_text = social_text[:277] + "..." if len(social_text) > 280 else social_text
        if args.dry_run:
            print(f"🐦 [DRY RUN] Would tweet: {x_text}")
            results["x"] = "dry_run"
        else:
            print(f"🐦 Posting to X...")
            result = x_post(x_text)
            results["x"] = "posted" if result else "failed"

    # ── LinkedIn ────────────────────────────────────────────────────────────
    if args.linkedin:
        if args.dry_run:
            print(f"💼 [DRY RUN] Would post to LinkedIn: {social_text[:100]}...")
            results["linkedin"] = "dry_run"
        else:
            print(f"💼 Posting to LinkedIn...")
            result = linkedin_post(social_text)
            results["linkedin"] = "posted" if result else "failed"

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("📊 Publish Summary")
    print("=" * 50)
    for platform, status in results.items():
        icon = {"published": "✅", "posted": "✅", "dry_run": "🔍", "failed": "❌"}.get(status, "?")
        print(f"  {icon} {platform}: {status}")


if __name__ == "__main__":
    main()