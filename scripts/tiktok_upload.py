#!/usr/bin/env python3
"""TikTok Content Posting API helper — OAuth + Direct Post (FILE_UPLOAD).

You have TIKTOK_CLIENT_KEY + TIKTOK_CLIENT_SECRET (the APP creds). To actually
post you need a per-USER access token via OAuth. This script does both:

  1. Authorize (one time, needs a browser):
         python scripts/tiktok_upload.py auth-url
     Open the printed URL, approve, copy the `code` from the redirect, then:
         python scripts/tiktok_upload.py exchange --code <CODE>
     That saves TIKTOK_ACCESS_TOKEN / TIKTOK_REFRESH_TOKEN / TIKTOK_OPEN_ID
     into ~/.config/social-media-kit/secrets.env.

  2. Post a video:
         python scripts/tiktok_upload.py post --video path/to.mp4 \
             --title "Group A decided ⚽ #worldcup" --privacy SELF_ONLY

IMPORTANT — TikTok audit: until your app is approved for Content Posting, the
API forces privacy_level=SELF_ONLY (the video is private, visible only to you).
Public posting unlocks after TikTok reviews the app. Keep --privacy SELF_ONLY
until then or the call is rejected.

Redirect URI must EXACTLY match one registered in your TikTok developer app.
Set TIKTOK_REDIRECT_URI in secrets.env (default below).
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS_FILES = [
    Path.home() / ".config" / "social-media-kit" / "secrets.env",
    ROOT / "config" / "secrets.env",
]
TOKEN_STORE = Path.home() / ".config" / "social-media-kit" / "secrets.env"

API = "https://open.tiktokapis.com"
DEFAULT_REDIRECT = "https://buildwithabdallah.com/tiktok/callback"
SCOPES = "user.info.basic,video.publish"


def load_env() -> None:
    for f in SECRETS_FILES:
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _require(var: str) -> str:
    val = os.environ.get(var, "")
    if not val:
        sys.exit(f"❌ {var} not set. See script header for setup.")
    return val


def _post_json(url: str, payload: dict, bearer: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _post_form(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(payload).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _save_tokens(tok: dict) -> None:
    """Upsert token values into the token store secrets.env."""
    mapping = {
        "TIKTOK_ACCESS_TOKEN": tok.get("access_token", ""),
        "TIKTOK_REFRESH_TOKEN": tok.get("refresh_token", ""),
        "TIKTOK_OPEN_ID": tok.get("open_id", ""),
    }
    TOKEN_STORE.parent.mkdir(parents=True, exist_ok=True)
    lines = TOKEN_STORE.read_text().splitlines() if TOKEN_STORE.exists() else []
    out, seen = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in mapping:
            out.append(f"{key}={mapping[key]}"); seen.add(key)
        else:
            out.append(line)
    for key, val in mapping.items():
        if key not in seen:
            out.append(f"{key}={val}")
    TOKEN_STORE.write_text("\n".join(out) + "\n")
    print(f"💾 Saved access/refresh/open_id → {TOKEN_STORE}")


# ── Commands ──────────────────────────────────────────────────────────────

def cmd_auth_url(_args) -> None:
    client_key = _require("TIKTOK_CLIENT_KEY")
    redirect = os.environ.get("TIKTOK_REDIRECT_URI", DEFAULT_REDIRECT)
    params = {
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": redirect,
        "state": "bwa" + str(int(time.time())),
    }
    print("Open this URL in a browser, approve, then copy the `code` query param "
          "from the redirect:\n")
    print("https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(params))
    print(f"\nRedirect URI in use: {redirect}")
    print("(It must EXACTLY match a redirect URI registered in your TikTok app.)")


def cmd_exchange(args) -> None:
    tok = _post_form(f"{API}/v2/oauth/token/", {
        "client_key": _require("TIKTOK_CLIENT_KEY"),
        "client_secret": _require("TIKTOK_CLIENT_SECRET"),
        "code": args.code,
        "grant_type": "authorization_code",
        "redirect_uri": os.environ.get("TIKTOK_REDIRECT_URI", DEFAULT_REDIRECT),
    })
    if "access_token" not in tok:
        sys.exit(f"❌ Token exchange failed: {tok}")
    _save_tokens(tok)
    print(f"✅ open_id {tok.get('open_id','')[:10]}… · expires in {tok.get('expires_in')}s")


def cmd_refresh(_args) -> None:
    tok = _post_form(f"{API}/v2/oauth/token/", {
        "client_key": _require("TIKTOK_CLIENT_KEY"),
        "client_secret": _require("TIKTOK_CLIENT_SECRET"),
        "grant_type": "refresh_token",
        "refresh_token": _require("TIKTOK_REFRESH_TOKEN"),
    })
    if "access_token" not in tok:
        sys.exit(f"❌ Refresh failed: {tok}")
    _save_tokens(tok)
    print("✅ Access token refreshed")


def post_video(video_path: str, title: str, privacy: str = "SELF_ONLY") -> dict:
    access = _require("TIKTOK_ACCESS_TOKEN")
    path = Path(video_path)
    if not path.exists():
        sys.exit(f"❌ video not found: {path}")
    size = path.stat().st_size

    # 1. Initialise a FILE_UPLOAD direct post (single chunk).
    init = _post_json(f"{API}/v2/post/publish/video/init/", {
        "post_info": {
            "title": title,
            "privacy_level": privacy,            # SELF_ONLY until app is audited
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": size,
            "total_chunk_count": 1,
        },
    }, bearer=access)

    data = init.get("data", {})
    upload_url, publish_id = data.get("upload_url"), data.get("publish_id")
    if not upload_url:
        sys.exit(f"❌ init failed: {json.dumps(init, indent=2)}")
    print(f"→ init ok · publish_id {publish_id}")

    # 2. PUT the raw bytes to the signed upload URL.
    body = path.read_bytes()
    put = urllib.request.Request(upload_url, data=body, method="PUT", headers={
        "Content-Type": "video/mp4",
        "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}",
    })
    with urllib.request.urlopen(put) as r:
        print(f"→ upload HTTP {r.status}")

    # 3. Poll publish status.
    for _ in range(10):
        time.sleep(3)
        st = _post_json(f"{API}/v2/post/publish/status/fetch/", {"publish_id": publish_id}, bearer=access)
        status = st.get("data", {}).get("status")
        print(f"   status: {status}")
        if status in ("PUBLISH_COMPLETE", "FAILED"):
            return st
    return {"publish_id": publish_id, "note": "still processing — check the TikTok app"}


def cmd_post(args) -> None:
    res = post_video(args.video, args.title, args.privacy)
    print(json.dumps(res, indent=2))


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="TikTok Content Posting helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth-url", help="Print the OAuth authorize URL").set_defaults(func=cmd_auth_url)
    ex = sub.add_parser("exchange", help="Exchange an OAuth code for tokens"); ex.add_argument("--code", required=True); ex.set_defaults(func=cmd_exchange)
    sub.add_parser("refresh", help="Refresh the access token").set_defaults(func=cmd_refresh)
    po = sub.add_parser("post", help="Post a video")
    po.add_argument("--video", required=True)
    po.add_argument("--title", required=True)
    po.add_argument("--privacy", default="SELF_ONLY", choices=["SELF_ONLY", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"])
    po.set_defaults(func=cmd_post)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
