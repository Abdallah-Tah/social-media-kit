#!/usr/bin/env python3
"""Publish a vertical video to a Facebook Page as a Reel (3-phase Graph upload).

Phases: start (get video_id + upload_url) -> upload (binary to rupload) ->
finish (video_state = PUBLISHED | DRAFT | SCHEDULED).

Reads FB_PAGE_ID + FB_PAGE_TOKEN from the kit secrets.

  python3 scripts/fb_reels_publisher.py --video reel.mp4 --description "..." [--draft]
"""
import os
import sys
import time
import argparse
import requests

GRAPH = "https://graph.facebook.com/v21.0"
RUPLOAD = "https://rupload.facebook.com/video-upload/v21.0"


def _cfg():
    return os.environ.get("FB_PAGE_ID", ""), os.environ.get("FB_PAGE_TOKEN", "")


def publish_reel(video_path, description="", state="PUBLISHED",
                 page_id=None, token=None, poll=True):
    page_id = page_id or os.environ.get("FB_PAGE_ID", "")
    token = token or os.environ.get("FB_PAGE_TOKEN", "")
    if not page_id or not token:
        print("❌ FB_PAGE_ID / FB_PAGE_TOKEN not set")
        return None
    if not os.path.exists(video_path):
        print(f"❌ video not found: {video_path}")
        return None
    size = os.path.getsize(video_path)

    # Phase 1: start
    r = requests.post(f"{GRAPH}/{page_id}/video_reels",
                      data={"upload_phase": "start", "access_token": token}, timeout=30)
    j = r.json()
    if not r.ok or "video_id" not in j:
        print(f"❌ start phase failed ({r.status_code}): {str(j)[:300]}")
        return None
    video_id = j["video_id"]
    upload_url = j.get("upload_url") or f"{RUPLOAD}/{video_id}"

    # Phase 2: upload binary
    with open(video_path, "rb") as f:
        up = requests.post(upload_url,
                           headers={"Authorization": f"OAuth {token}",
                                    "offset": "0", "file_size": str(size)},
                           data=f.read(), timeout=300)
    if not up.ok or not up.json().get("success", True):
        print(f"❌ upload phase failed ({up.status_code}): {up.text[:300]}")
        return None

    # Phase 3: finish/publish
    params = {"upload_phase": "finish", "video_id": video_id,
              "video_state": state, "access_token": token}
    if description:
        params["description"] = description
    fin = requests.post(f"{GRAPH}/{page_id}/video_reels", data=params, timeout=60)
    if not fin.ok or not fin.json().get("success"):
        print(f"❌ finish phase failed ({fin.status_code}): {fin.text[:300]}")
        return None

    print(f"✅ Reel {state}: video_id={video_id}")
    result = {"video_id": video_id, "state": state,
              "permalink": f"https://www.facebook.com/reel/{video_id}"}

    # Phase 4: poll processing status (optional)
    if poll:
        for _ in range(10):
            time.sleep(4)
            st = requests.get(f"{GRAPH}/{video_id}",
                              params={"fields": "status", "access_token": token}, timeout=20)
            s = st.json().get("status", {})
            vs = s.get("video_status") or s.get("processing_phase", {})
            if str(vs).lower() in ("ready", "published", "complete") or \
               s.get("processing_phase", {}).get("status") == "complete":
                break
        result["status"] = st.json().get("status")
    return result


def delete_video(video_id, token=None):
    token = token or os.environ.get("FB_PAGE_TOKEN", "")
    r = requests.delete(f"{GRAPH}/{video_id}", params={"access_token": token}, timeout=30)
    print(f"delete {video_id}: {r.status_code} {r.text[:120]}")
    return r.ok


def main():
    ap = argparse.ArgumentParser(description="Publish a Facebook Reel")
    ap.add_argument("--video", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--draft", action="store_true", help="Upload as DRAFT (not public)")
    ap.add_argument("--delete", help="Delete a video_id instead of publishing")
    args = ap.parse_args()
    try:
        sys.path.insert(0, os.path.expanduser("~/social-media-kit"))
        from agent.config import load_env; load_env()
    except Exception:
        pass
    if args.delete:
        sys.exit(0 if delete_video(args.delete) else 1)
    r = publish_reel(args.video, description=args.description,
                     state="DRAFT" if args.draft else "PUBLISHED")
    print(r)
    sys.exit(0 if r else 1)


if __name__ == "__main__":
    main()
