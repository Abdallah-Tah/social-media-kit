#!/usr/bin/env python3
"""LinkedIn ORGANIZATION poster for Build With Abdallah (showcase page 119694084).

Fetches the org access token from the buildwithabdallah.com API (the token lives
encrypted in the site DB; the endpoint returns it decrypted to a Sanctum-authed
caller), then posts a UGC share to the organization page with an optional image.

Endpoint contract (server-side, see LINKEDIN_TOKEN_ENDPOINT.md):
  GET {BLOG_API_URL}/social/linkedin/token
  Authorization: Bearer {BLOG_API_TOKEN}
  -> 200 {"data": {"access_token": "...",
                    "author_urn": "urn:li:organization:119694084",
                    "expires_at": "2026-08-03T..."}}

Run:
  python3 scripts/linkedin_org_poster.py --text "..." --image cover.png \
      --title "..." --description "..."
"""
import os
import sys
import argparse
import requests
from pathlib import Path

ORG_URN_DEFAULT = "urn:li:organization:119694084"
LI_API = "https://api.linkedin.com/v2"

import re as _re


def strip_markdown(t):
    """Social platforms don't render markdown — strip it to plain text."""
    if not t:
        return t
    t = _re.sub(r"\*\*([^*]+)\*\*", r"\1", t)          # **bold**
    t = _re.sub(r"__([^_]+)__", r"\1", t)              # __bold__
    t = _re.sub(r"\*([^*\n]+)\*", r"\1", t)            # *italic*
    t = _re.sub(r"`([^`]+)`", r"\1", t)                # `code`
    t = _re.sub(r"^\s{0,3}#{1,6}\s+", "", t, flags=_re.M)   # # headings
    t = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 \2", t)    # [text](url)
    return t


def _secret(key, default=""):
    return os.environ.get(key, default)


def fetch_org_token():
    """GET the decrypted org token + author urn from the site API."""
    base = _secret("BLOG_API_URL", "").rstrip("/")
    # Dedicated token with the `social-tokens:read` ability; falls back to the
    # publish token only if it happens to carry that ability too.
    blog_token = _secret("SOCIAL_API_TOKEN") or _secret("BLOG_API_TOKEN")
    url = _secret("LINKEDIN_TOKEN_URL") or f"{base}/social/linkedin/token"
    if not blog_token or not base:
        print("❌ BLOG_API_URL / BLOG_API_TOKEN not loaded (run via the kit or load_env first).")
        return None, None
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {blog_token}", "Accept": "application/json"},
            timeout=20,
        )
    except requests.RequestException as e:
        print(f"❌ token fetch failed: {e}")
        return None, None
    if r.status_code == 404:
        print(f"❌ token endpoint not found ({url}). The server-side route isn't deployed yet.")
        return None, None
    if not r.ok:
        print(f"❌ token endpoint error ({r.status_code}): {r.text[:200]}")
        return None, None
    data = r.json().get("data", r.json())
    token = data.get("access_token")
    author = data.get("author_urn") or ORG_URN_DEFAULT
    if not token:
        print(f"❌ no access_token in endpoint response: {str(data)[:200]}")
        return None, None
    return token, author


def post_org(text, image_path=None, title="", description="", token=None, author=None):
    """Publish a UGC share to the LinkedIn organization page."""
    if token is None:
        token, author = fetch_org_token()
        if not token:
            return None
    author = author or ORG_URN_DEFAULT
    text = strip_markdown(text)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    media = []
    if image_path and os.path.exists(image_path):
        reg = requests.post(
            f"{LI_API}/assets?action=registerUpload",
            json={
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "owner": author,
                    "serviceRelationships": [
                        {"relationshipType": "OWNER",
                         "identifier": "urn:li:userGeneratedContent"}
                    ],
                }
            },
            headers=headers,
            timeout=30,
        )
        if reg.status_code != 200:
            print(f"❌ registerUpload failed ({reg.status_code}): {reg.text[:200]}")
            return None
        val = reg.json()["value"]
        upload_url = val["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        asset_urn = val["asset"]
        with open(image_path, "rb") as img:
            up = requests.post(
                upload_url, data=img,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "image/png"},
                timeout=60,
            )
        if up.status_code not in (200, 201):
            print(f"❌ image upload failed ({up.status_code})")
            return None
        media = [{
            "status": "READY",
            "description": {"text": description or title or ""},
            "media": asset_urn,
            "title": {"text": title or "Build With Abdallah"},
        }]

    share = {"shareCommentary": {"text": text},
             "shareMediaCategory": "IMAGE" if media else "NONE"}
    if media:
        share["media"] = media
    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": share},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = requests.post(f"{LI_API}/ugcPosts", json=payload, headers=headers, timeout=30)
    if resp.status_code == 201:
        post_id = resp.headers.get("x-restli-id") or resp.json().get("id", "")
        print(f"✅ Posted to LinkedIn org page: {post_id}")
        return {"id": post_id}
    print(f"❌ ugcPosts failed ({resp.status_code}): {resp.text[:300]}")
    return None


def main():
    ap = argparse.ArgumentParser(description="Post to the LinkedIn org page")
    ap.add_argument("--text", required=True)
    ap.add_argument("--image")
    ap.add_argument("--title", default="")
    ap.add_argument("--description", default="")
    args = ap.parse_args()
    # Load kit secrets if not already in env.
    try:
        root = Path(os.environ.get("SMKIT_ROOT", Path(__file__).resolve().parents[1]))
        sys.path.insert(0, str(root))
        from agent.config import load_env
        load_env()
    except Exception:
        pass
    r = post_org(args.text, image_path=args.image, title=args.title,
                 description=args.description)
    sys.exit(0 if r else 1)


if __name__ == "__main__":
    main()
