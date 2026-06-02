#!/usr/bin/env python3
"""Blog Publisher — Push articles to your blog via REST API.

Supports any blog platform with a REST API (WordPress, Laravel, Ghost, etc).
Configure BLOG_API_URL and BLOG_API_TOKEN in secrets.env.
"""
import os
import sys
import json
import argparse
import re
import requests

BLOG_API_URL = os.environ.get("BLOG_API_URL", "")
BLOG_API_TOKEN = os.environ.get("BLOG_API_TOKEN", "")
SECRETS_PATH = os.environ.get(
    "SECRETS_PATH",
    os.path.expanduser("~/.config/social-media-kit/secrets.env"),
)


def load_credentials():
    """Load blog API credentials from secrets.env."""
    global BLOG_API_URL, BLOG_API_TOKEN

    if BLOG_API_URL and BLOG_API_TOKEN:
        return BLOG_API_URL, BLOG_API_TOKEN

    if os.path.exists(SECRETS_PATH):
        with open(SECRETS_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("BLOG_API_URL=") and not BLOG_API_URL:
                    BLOG_API_URL = line.split("=", 1)[1]
                elif line.startswith("BLOG_API_TOKEN=") and not BLOG_API_TOKEN:
                    BLOG_API_TOKEN = line.split("=", 1)[1]

    return BLOG_API_URL, BLOG_API_TOKEN


def strip_front_matter(content):
    """Remove YAML front matter from markdown."""
    return re.sub(r"^---.*?---\s*", "", content, flags=re.S).strip()


def publish_article(title, slug, content, excerpt="", category_id=None,
                    tags=None, publish=True, featured=False,
                    meta_title="", meta_description=""):
    """Publish an article to the blog."""
    api_url, api_token = load_credentials()

    if not api_url or not api_token:
        print("❌ BLOG_API_URL and BLOG_API_TOKEN not set. See config/secrets.env.example")
        return None

    # Strip front matter if present
    body = strip_front_matter(content) if content.startswith("---") else content

    payload = {
        "title": title,
        "slug": slug,
        "body": body,
        "publish": publish,
        "featured": featured,
    }

    if excerpt:
        payload["excerpt"] = excerpt
    if category_id:
        payload["category_id"] = category_id
    if tags:
        payload["tags"] = tags
    if meta_title:
        payload["meta_title"] = meta_title
    if meta_description:
        payload["meta_description"] = meta_description

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    resp = requests.post(f"{api_url}/posts", json=payload, headers=headers)
    result = resp.json()

    if resp.status_code in (200, 201) and "data" in result:
        post = result["data"]
        print(f"✅ Published: Post ID {post.get('id')}, Slug: {post.get('slug')}")
        return post
    else:
        print(f"❌ Blog API error ({resp.status_code}): {json.dumps(result, indent=2)[:500]}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Publish article to blog")
    parser.add_argument("--title", "-t", required=True, help="Article title")
    parser.add_argument("--slug", "-s", help="URL slug (auto-generated from title if omitted)")
    parser.add_argument("--file", "-f", help="Markdown file to publish")
    parser.add_argument("--excerpt", "-e", help="Article excerpt")
    parser.add_argument("--category", "-c", type=int, help="Category ID")
    parser.add_argument("--tags", help="Comma-separated tag IDs")
    parser.add_argument("--draft", action="store_true", help="Save as draft (don't publish)")
    parser.add_argument("--featured", action="store_true", help="Mark as featured")
    parser.add_argument("--meta-title", help="SEO meta title")
    parser.add_argument("--meta-desc", help="SEO meta description")
    args = parser.parse_args()

    # Generate slug from title
    slug = args.slug or args.title.lower().replace(" ", "-").replace("—", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)

    # Read content
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            content = f.read()
    else:
        print("Enter article content (Ctrl+D to finish):")
        content = sys.stdin.read()

    # Parse tags
    tags = [int(t.strip()) for t in args.tags.split(",")] if args.tags else None

    publish_article(
        title=args.title,
        slug=slug,
        content=content,
        excerpt=args.excerpt or "",
        category_id=args.category,
        tags=tags,
        publish=not args.draft,
        featured=args.featured,
        meta_title=args.meta_title or "",
        meta_description=args.meta_desc or "",
    )


if __name__ == "__main__":
    main()