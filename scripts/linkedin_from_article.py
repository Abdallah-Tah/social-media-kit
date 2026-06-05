#!/usr/bin/env python3
"""Post a published article to the LinkedIn PERSONAL feed (auto, for the cron).

Fetches the article + the LinkedIn token (via the site endpoint, using
SOCIAL_API_TOKEN), writes a short professional post (gpt-4o-mini, template
fallback), and posts to urn:li:person:<sub> with the cover image.

  python3 scripts/linkedin_from_article.py --latest
  python3 scripts/linkedin_from_article.py --slug <slug>
"""
import os
import sys
import json
import argparse
import tempfile
import urllib.request
import requests

sys.path.insert(0, os.path.expanduser("~/social-media-kit"))
from agent.config import load_env
load_env()
sys.path.insert(0, os.path.join(os.path.expanduser("~/social-media-kit"), "scripts"))
import linkedin_org_poster as L

BASE = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
SITE = "https://buildwithabdallah.com"


def _h():
    return {"Authorization": f"Bearer {os.environ.get('BLOG_API_TOKEN','')}", "Accept": "application/json"}


def fetch(slug=None, latest=False):
    if latest:
        d = requests.get(f"{BASE}/posts", params={"per_page": 1}, headers=_h(), timeout=20).json().get("data", [])
        return d[0] if d else None
    for p in requests.get(f"{BASE}/posts", params={"per_page": 50}, headers=_h(), timeout=20).json().get("data", []):
        if p.get("slug") == slug:
            return p
    return None


def person_urn(token):
    try:
        r = requests.get("https://api.linkedin.com/v2/userinfo",
                         headers={"Authorization": f"Bearer {token}"}, timeout=15)
        sub = r.json().get("sub")
        if sub:
            return f"urn:li:person:{sub}"
    except Exception:
        pass
    return os.environ.get("LINKEDIN_PERSON_URN", "urn:li:person:ABnvUUsgfB")


def write_post(title, excerpt, body, url):
    prompt = (
        "Write a concise professional LinkedIn post in PLAIN TEXT (no markdown, no ** or * or # "
        "or backticks — LinkedIn shows them literally) (90-150 words, first-person, strong hook "
        f"first line, real value, ends with 'Read it \U0001f449 {url}'), then 5-7 relevant "
        "hashtags including #BuildWithAbdallah. Return STRICT JSON "
        '{"post":"...","hashtags":["#.."]}.\n'
        f"TITLE: {title}\nEXCERPT: {excerpt}\nBODY: {(body or '')[:1000]}"
    )
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        try:
            r = requests.post("https://api.openai.com/v1/chat/completions",
                              headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                              json={"model": "gpt-4o-mini",
                                    "messages": [{"role": "user", "content": prompt}],
                                    "temperature": 0.6,
                                    "response_format": {"type": "json_object"}}, timeout=45)
            if r.ok:
                o = json.loads(r.json()["choices"][0]["message"]["content"])
                tags = [("#" + h.lstrip("#").strip()) for h in o.get("hashtags", []) if h.strip()][:7]
                if not any(t.lower() == "#buildwithabdallah" for t in tags):
                    tags.append("#BuildWithAbdallah")
                if o.get("post"):
                    return o["post"].strip() + "\n\n" + " ".join(tags)
        except Exception as e:
            print(f"⚠️ LinkedIn copy via OpenAI failed ({e}); using template.")
    return (f"{title}\n\nNew on Build With Abdallah.\n\nRead it \U0001f449 {url}\n\n"
            "#AI #Laravel #PHP #SoftwareDevelopment #BuildWithAbdallah")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--latest", action="store_true")
    args = ap.parse_args()

    p = fetch(slug=args.slug, latest=args.latest or not args.slug)
    if not p:
        print("❌ article not found"); sys.exit(1)
    url = f"{SITE}/tutorials/{p['slug']}"

    token, _ = L.fetch_org_token()      # ignore org urn; we post to the person feed
    if not token:
        print("❌ no LinkedIn token (need SOCIAL_API_TOKEN + the /social/linkedin/token endpoint)")
        sys.exit(1)
    author = person_urn(token)

    work = tempfile.mkdtemp(prefix="li_")
    cover = None
    if p.get("cover_image"):
        cover = os.path.join(work, "cover.png")
        try:
            urllib.request.urlretrieve(p["cover_image"], cover)
        except Exception:
            cover = None

    text = write_post(p["title"], p.get("excerpt") or "", p.get("body") or "", url)
    print(f"→ {p['title']}\n  author: {author}")
    r = L.post_org(text, image_path=cover, title=p["title"][:90], description="",
                   token=token, author=author)
    print("RESULT:", r)
    sys.exit(0 if r else 1)


if __name__ == "__main__":
    main()
