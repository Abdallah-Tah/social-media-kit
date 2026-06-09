#!/usr/bin/env python3
"""Upload Build With Abdallah reels to YouTube Shorts.

OAuth setup:
  python3 scripts/youtube_shorts_publisher.py auth-url
  python3 scripts/youtube_shorts_publisher.py exchange-code --code <CODE>

Upload:
  python3 scripts/youtube_shorts_publisher.py upload --video reel.mp4 \
    --title "Short title" --description "Description"
"""
import argparse
import json
import mimetypes
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "config" / "secrets.env"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
WATERMARK_URL = "https://www.googleapis.com/upload/youtube/v3/watermarks/set"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
DEFAULT_REDIRECT_URI = "http://localhost:8090/"


def _load_env():
    sys.path.insert(0, str(ROOT))
    try:
        from agent.config import load_env
        load_env()
    except Exception:
        _load_env_file(SECRETS)


def _load_env_file(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _require(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def _upsert_secret(key, value):
    lines = []
    if SECRETS.exists():
        lines = SECRETS.read_text().splitlines()
    out, done = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
    SECRETS.write_text("\n".join(out) + "\n")
    os.chmod(SECRETS, 0o600)


def auth_url(args):
    client_id = _require("YOUTUBE_CLIENT_ID")
    params = {
        "client_id": client_id,
        "redirect_uri": args.redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    print(f"{AUTH_URL}?{urlencode(params)}")
    print("\nAfter approving, copy the code= value from the failed localhost URL.")


def exchange_code(args):
    data = {
        "client_id": _require("YOUTUBE_CLIENT_ID"),
        "client_secret": _require("YOUTUBE_CLIENT_SECRET"),
        "code": args.code,
        "grant_type": "authorization_code",
        "redirect_uri": args.redirect_uri,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    if not r.ok:
        raise SystemExit(f"token exchange failed ({r.status_code}): {r.text[:400]}")
    token = r.json()
    refresh = token.get("refresh_token")
    if not refresh:
        raise SystemExit("Google did not return a refresh_token; rerun auth-url and approve with prompt=consent.")
    _upsert_secret("YOUTUBE_REFRESH_TOKEN", refresh)
    print("✅ YouTube refresh token saved to config/secrets.env")


def _access_token():
    data = {
        "client_id": _require("YOUTUBE_CLIENT_ID"),
        "client_secret": _require("YOUTUBE_CLIENT_SECRET"),
        "refresh_token": _require("YOUTUBE_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    if not r.ok:
        raise SystemExit(f"refresh failed ({r.status_code}): {r.text[:400]}")
    return r.json()["access_token"]


def upload(args):
    video = Path(args.video)
    if not video.exists():
        raise SystemExit(f"video not found: {video}")
    mime = mimetypes.guess_type(str(video))[0] or "video/mp4"
    body = {
        "snippet": {
            "title": args.title,
            "description": args.description,
            "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
            "categoryId": args.category_id,
        },
        "status": {
            "privacyStatus": args.privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    token = _access_token()
    start = requests.post(
        UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(video.stat().st_size),
            "X-Upload-Content-Type": mime,
        },
        data=json.dumps(body),
        timeout=30,
    )
    if start.status_code not in (200, 201):
        raise SystemExit(f"upload start failed ({start.status_code}): {start.text[:500]}")
    location = start.headers.get("Location")
    if not location:
        raise SystemExit("upload start failed: missing resumable Location header")
    with video.open("rb") as fh:
        finish = requests.put(
            location,
            headers={"Content-Type": mime},
            data=fh,
            timeout=300,
        )
    if finish.status_code not in (200, 201):
        raise SystemExit(f"upload finish failed ({finish.status_code}): {finish.text[:500]}")
    data = finish.json()
    vid = data.get("id", "")
    print(f"✅ YouTube Short uploaded: https://www.youtube.com/shorts/{vid}")
    print(json.dumps({"id": vid, "url": f"https://www.youtube.com/shorts/{vid}"}, indent=2))


def set_watermark(args):
    image = Path(args.image)
    if not image.exists():
        raise SystemExit(f"watermark image not found: {image}")
    mime = mimetypes.guess_type(str(image))[0] or "image/png"
    if mime not in {"image/png", "image/jpeg", "application/octet-stream"}:
        raise SystemExit(f"unsupported watermark MIME type: {mime}")
    metadata = {
        "timing": {
            "type": "offsetFromStart",
            "offsetMs": str(args.offset_ms),
        },
        "targetChannelId": args.target_channel_id or args.channel_id,
    }
    if args.duration_ms > 0:
        metadata["timing"]["durationMs"] = str(args.duration_ms)
    boundary = f"===============youtube-watermark-{uuid.uuid4().hex}=="
    body = b"".join([
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode("utf-8"),
        json.dumps(metadata).encode("utf-8"),
        b"\r\n",
        f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8"),
        image.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ])
    r = requests.post(
        WATERMARK_URL,
        params={"uploadType": "multipart", "channelId": args.channel_id},
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        data=body,
        timeout=60,
    )
    if r.status_code != 204:
        raise SystemExit(f"watermark set failed ({r.status_code}): {r.text[:500]}")
    print(f"✅ YouTube watermark set for channel {args.channel_id}: {image}")


def main():
    _load_env()
    ap = argparse.ArgumentParser(description="YouTube Shorts uploader")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_auth = sub.add_parser("auth-url", help="Print the Google OAuth consent URL")
    p_auth.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    p_auth.set_defaults(func=auth_url)

    p_code = sub.add_parser("exchange-code", help="Exchange copied OAuth code for a refresh token")
    p_code.add_argument("--code", required=True)
    p_code.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    p_code.set_defaults(func=exchange_code)

    p_up = sub.add_parser("upload", help="Upload a vertical reel as a YouTube Short")
    p_up.add_argument("--video", required=True)
    p_up.add_argument("--title", required=True)
    p_up.add_argument("--description", default="")
    p_up.add_argument("--privacy", choices=["public", "unlisted", "private"], default="public")
    p_up.add_argument("--tags", default="BuildWithAbdallah,programming,tutorial,shorts")
    p_up.add_argument("--category-id", default="27", help="27=Education, 28=Science & Technology")
    p_up.set_defaults(func=upload)

    p_wm = sub.add_parser("set-watermark", help="Set the channel video watermark")
    p_wm.add_argument("--channel-id", required=True)
    p_wm.add_argument("--image", required=True)
    p_wm.add_argument("--target-channel-id", default="")
    p_wm.add_argument("--offset-ms", type=int, default=0)
    p_wm.add_argument("--duration-ms", type=int, default=0)
    p_wm.set_defaults(func=set_watermark)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
