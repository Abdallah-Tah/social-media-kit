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
                    meta_title="", meta_description="", cover_image_url=""):
    """Publish an article to the blog."""
    api_url, api_token = load_credentials()

    if not api_url or not api_token:
        print("❌ BLOG_API_URL and BLOG_API_TOKEN not set. See config/secrets.env.example")
        return None

    # Strip front matter if present
    body = strip_front_matter(content) if content.startswith("---") else content

    platform = (os.environ.get("BLOG_PLATFORM", "") or "generic").lower()
    fields = {
        "title": title, "slug": slug, "body": body, "excerpt": excerpt,
        "publish": publish, "featured": featured, "category_id": category_id,
        "tags": tags, "meta_title": meta_title, "meta_description": meta_description,
        "cover_image_url": cover_image_url,
    }
    try:
        if platform == "wordpress":
            return _publish_wordpress(api_url, api_token, fields)
        if platform == "ghost":
            return _publish_ghost(api_url, api_token, fields)
        return _publish_generic(api_url, api_token, fields)
    except requests.RequestException as e:
        print(f"❌ Blog request failed: {e}")
        return None


def _ensure_hosted_cover(cover):
    """Rehost any cover (local path or external/temporary URL like FAL's CDN)
    onto the site's media library, so a published cover is never a link that
    expires or a local path the site can't read."""
    if not cover:
        return cover
    base = os.environ.get("BLOG_API_URL", "").rstrip("/")
    origin = base.split("/api/")[0] if "/api/" in base else base
    if origin and cover.startswith(origin):
        return cover  # already hosted on the site
    # BLOG_API_TOKEN carries the media-upload ability; SOCIAL_API_TOKEN often
    # returns 403 "Invalid ability provided" on /media/upload. Try the publish
    # token first, then fall back to the social token.
    tokens = [t for t in (os.environ.get("BLOG_API_TOKEN"),
                          os.environ.get("SOCIAL_API_TOKEN")) if t]
    if not base or not tokens:
        return cover
    try:
        if cover.startswith("http://") or cover.startswith("https://"):
            data = requests.get(cover, timeout=60).content
        elif os.path.exists(cover):
            with open(cover, "rb") as fh:
                data = fh.read()
        else:
            return cover
        for tok in tokens:
            r = requests.post(
                f"{base}/media/upload",
                headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
                files={"file": ("cover.png", data, "image/png")},
                timeout=90,
            )
            if r.status_code in (200, 201):
                url = (r.json().get("data", {}) or {}).get("url")
                if url:
                    print(f"✅ cover rehosted on site: {url}")
                    return url
            else:
                print(f"⚠️ media upload returned {r.status_code} ({r.text[:80]}); "
                      "trying next token." if len(tokens) > 1 else
                      f"⚠️ media upload returned {r.status_code} ({r.text[:80]}).")
    except Exception as e:
        print(f"⚠️ cover rehost failed ({e}); using original.")
    return cover


def _publish_generic(api_url, api_token, f):
    payload = {
        "title": f["title"], "slug": f["slug"], "body": f["body"],
        "publish": f["publish"], "featured": f["featured"],
    }
    for k_src, k_dst in [("excerpt", "excerpt"), ("category_id", "category_id"),
                          ("tags", "tags"), ("meta_title", "meta_title"),
                          ("meta_description", "meta_description")]:
        if f.get(k_src):
            payload[k_dst] = f[k_src]
    if f.get("cover_image_url"):
        hosted = _ensure_hosted_cover(f["cover_image_url"])
        payload["cover_image"] = hosted
        payload["featured_image"] = hosted
    resp = requests.post(
        f"{api_url}/posts", json=payload,
        headers={"Authorization": f"Bearer {api_token}",
                 "Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )
    result = resp.json()
    if resp.status_code in (200, 201) and "data" in result:
        post = result["data"]
        print(f"✅ Published: Post ID {post.get('id')}, Slug: {post.get('slug')}")
        return post
    print(f"❌ Blog API error ({resp.status_code}): {json.dumps(result, indent=2)[:500]}")
    return None


def _publish_wordpress(api_url, api_token, f):
    """WordPress REST API. BLOG_API_URL=site root, auth=user:app_password.

    Set BLOG_API_USER + BLOG_API_TOKEN (an Application Password).
    """
    user = os.environ.get("BLOG_API_USER", "")
    payload = {
        "title": f["title"], "content": f["body"], "slug": f["slug"],
        "status": "publish" if f["publish"] else "draft",
    }
    if f.get("excerpt"):
        payload["excerpt"] = f["excerpt"]
    if f.get("category_id"):
        payload["categories"] = [f["category_id"]]
    if f.get("tags"):
        payload["tags"] = f["tags"]
    resp = requests.post(
        f"{api_url.rstrip('/')}/wp-json/wp/v2/posts",
        json=payload, auth=(user, api_token), timeout=30,
    )
    if resp.status_code in (200, 201):
        post = resp.json()
        print(f"✅ Published to WordPress: ID {post.get('id')} → {post.get('link')}")
        return post
    print(f"❌ WordPress error ({resp.status_code}): {resp.text[:400]}")
    return None


def _ghost_jwt(admin_key):
    """Build a short-lived Ghost Admin API JWT (HS256) without external deps."""
    import hmac, hashlib, base64, time

    kid, secret = admin_key.split(":")
    secret_bytes = bytes.fromhex(secret)

    def b64(obj):
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    iat = int(time.time())
    signing = b64({"alg": "HS256", "typ": "JWT", "kid": kid}) + b"." + b64(
        {"iat": iat, "exp": iat + 300, "aud": "/admin/"}
    )
    sig = base64.urlsafe_b64encode(
        hmac.new(secret_bytes, signing, hashlib.sha256).digest()
    ).rstrip(b"=")
    return (signing + b"." + sig).decode()


def _publish_ghost(api_url, api_token, f):
    """Ghost Admin API. BLOG_API_URL=site root, BLOG_API_TOKEN=Admin API key (id:secret)."""
    token = _ghost_jwt(api_token)
    post = {
        "title": f["title"], "html": f["body"], "slug": f["slug"],
        "status": "published" if f["publish"] else "draft",
        "featured": bool(f.get("featured")),
    }
    if f.get("excerpt"):
        post["custom_excerpt"] = f["excerpt"][:300]
    if f.get("cover_image_url"):
        post["feature_image"] = f["cover_image_url"]
    resp = requests.post(
        f"{api_url.rstrip('/')}/ghost/api/admin/posts/?source=html",
        json={"posts": [post]},
        headers={"Authorization": f"Ghost {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    if resp.status_code in (200, 201):
        created = resp.json().get("posts", [{}])[0]
        print(f"✅ Published to Ghost: {created.get('url', created.get('id'))}")
        return created
    print(f"❌ Ghost error ({resp.status_code}): {resp.text[:400]}")
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