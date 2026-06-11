#!/usr/bin/env python3
"""Publish a vertical video to Instagram as a Reel (Graph API, 3 steps).

Unlike Facebook Reels (binary upload), the IG Graph API needs a PUBLIC
video_url, so a local file is first hosted on the site media library
(BLOG_API_URL /media/upload), then:

  1. POST /{ig-user-id}/media  media_type=REELS, video_url, caption  -> creation_id
  2. poll GET /{creation_id}?fields=status_code  until FINISHED
  3. POST /{ig-user-id}/media_publish  creation_id

Credentials (secrets.env):
  IG_USER_ID            Instagram *Business* account id (linked to the FB page)
  IG_ACCESS_TOKEN       token with instagram_content_publish (FB_PAGE_TOKEN works
                        when the IG business account is linked to the page)
  BLOG_API_URL/_TOKEN   site media endpoint used to host the local mp4

  python3 scripts/instagram_reels_publisher.py --video reel.mp4 --caption "..."
"""
import argparse
import os
import sys
import time

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def _ig_user() -> str:
    return (os.environ.get("IG_USER_ID")
            or os.environ.get("INSTAGRAM_USER_ID")
            or os.environ.get("INSTAGRAM_BUSINESS_ID", ""))


def _ig_token() -> str:
    return (os.environ.get("IG_ACCESS_TOKEN")
            or os.environ.get("FB_PAGE_TOKEN")
            or os.environ.get("FB_PAGE_ACCESS_TOKEN", ""))


def host_video(local_path: str) -> str | None:
    """Upload a local mp4 to the site media library; return its public URL."""
    base = os.environ.get("BLOG_API_URL", "").rstrip("/")
    tok = os.environ.get("SOCIAL_API_TOKEN") or os.environ.get("BLOG_API_TOKEN", "")
    if not base or not tok:
        print("❌ BLOG_API_URL / BLOG_API_TOKEN not set — cannot host video for IG")
        return None
    try:
        with open(local_path, "rb") as f:
            r = requests.post(
                f"{base}/media/upload",
                headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
                files={"file": (os.path.basename(local_path), f, "video/mp4")},
                timeout=180,
            )
        if r.status_code in (200, 201):
            url = (r.json().get("data", {}) or {}).get("url")
            if url:
                print(f"✅ hosted video → {url}")
                return url
        print(f"❌ host failed ({r.status_code}): {r.text[:200]}")
    except requests.RequestException as e:
        print(f"❌ host error: {e}")
    return None


def publish_reel(video: str, caption: str = "", share_to_feed: bool = True) -> dict | None:
    ig_user, token = _ig_user(), _ig_token()
    if not ig_user or not token:
        print("❌ IG_USER_ID / IG access token not set — finish IG OAuth first")
        return None

    video_url = video if video.startswith("http") else host_video(video)
    if not video_url:
        return None

    # 1. Create the media container.
    r = requests.post(f"{GRAPH}/{ig_user}/media", data={
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
        "access_token": token,
    }, timeout=60)
    j = r.json()
    creation_id = j.get("id")
    if not creation_id:
        print(f"❌ container create failed ({r.status_code}): {str(j)[:300]}")
        return None
    print(f"→ container {creation_id}; waiting for IG to ingest…")

    # 2. Poll until the container finishes processing (IG fetches the URL).
    for _ in range(20):
        time.sleep(6)
        s = requests.get(f"{GRAPH}/{creation_id}",
                         params={"fields": "status_code,status", "access_token": token}, timeout=30)
        code = s.json().get("status_code")
        print(f"   status: {code}")
        if code == "FINISHED":
            break
        if code == "ERROR":
            print(f"❌ IG processing error: {s.json()}")
            return None
    else:
        print("❌ timed out waiting for IG to process the video")
        return None

    # 3. Publish.
    p = requests.post(f"{GRAPH}/{ig_user}/media_publish",
                      data={"creation_id": creation_id, "access_token": token}, timeout=60)
    pj = p.json()
    if pj.get("id"):
        print(f"✅ Published IG Reel: {pj['id']}")
        return pj
    print(f"❌ publish failed ({p.status_code}): {str(pj)[:300]}")
    return None


def main():
    ap = argparse.ArgumentParser(description="Publish a vertical video as an Instagram Reel")
    ap.add_argument("--video", required=True, help="Local mp4 path or public URL")
    ap.add_argument("--caption", default="")
    ap.add_argument("--no-feed", action="store_true", help="Don't also share to the main feed")
    args = ap.parse_args()
    # Load kit secrets if present.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import blog_publisher  # noqa: F401  (reuses its secrets loader side effects)
    except Exception:
        pass
    res = publish_reel(args.video, args.caption, share_to_feed=not args.no_feed)
    sys.exit(0 if res else 1)


if __name__ == "__main__":
    main()
