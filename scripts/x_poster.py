#!/usr/bin/env python3
"""X (Twitter) posting script — OAuth 2.0 edition.

Posts tweets via the X API v2 using OAuth 2.0 bearer tokens.
Automatically refreshes access tokens when expired.

Setup: https://developer.x.com/
"""
import os
import sys
import json
import base64
import argparse
import requests

SECRETS_PATH = os.path.expanduser("~/.config/social-media-kit/secrets.env")


def _load_secrets():
    """Load the secrets file as a dict."""
    secrets = {}
    if os.path.exists(SECRETS_PATH):
        with open(SECRETS_PATH) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    secrets[key.strip()] = value.strip()
    return secrets


def _save_secrets(secrets):
    """Write the secrets file back preserving existing entries."""
    with open(SECRETS_PATH, "w") as f:
        for key, value in secrets.items():
            f.write(f"{key}={value}\n")


def _get_env_or_secrets(keys, prefer_secrets=True):
    """Fetch keys; prefer secrets.env over stale environment variables."""
    secrets = _load_secrets()
    result = {}
    for key in keys:
        if prefer_secrets:
            value = secrets.get(key, "") or os.environ.get(key, "")
        else:
            value = os.environ.get(key, "") or secrets.get(key, "")
        result[key] = value
    return result


def _refresh_access_token(client_id, client_secret, refresh_token):
    """Exchange a refresh token for a new access token."""
    if not client_id or not client_secret:
        print("❌ Missing X_CLIENT_ID or X_CLIENT_SECRET; cannot refresh.")
        return None
    if not refresh_token:
        print("❌ Missing X_OAUTH2_REFRESH_TOKEN; cannot refresh.")
        return None

    auth_str = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_str}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    resp = requests.post(
        "https://api.x.com/2/oauth2/token",
        headers=headers,
        data=data,
        timeout=60,
    )

    if resp.status_code not in (200, 201):
        print(f"❌ X token refresh failed ({resp.status_code}): {resp.text}")
        return None

    payload = resp.json()
    new_access = payload.get("access_token", "")
    new_refresh = payload.get("refresh_token", refresh_token)
    if not new_access:
        print("❌ X token refresh response missing access_token.")
        return None

    # Persist updated tokens.
    secrets = _load_secrets()
    secrets["X_OAUTH2_ACCESS_TOKEN"] = new_access
    if new_refresh:
        secrets["X_OAUTH2_REFRESH_TOKEN"] = new_refresh
    _save_secrets(secrets)
    print("🔁 X OAuth 2 access token refreshed and saved.")
    return new_access


def get_credentials(attempt_refresh=True):
    """Load OAuth 2.0 credentials, refreshing access token if necessary."""
    keys = [
        "X_OAUTH2_ACCESS_TOKEN",
        "X_OAUTH2_REFRESH_TOKEN",
        "X_CLIENT_ID",
        "X_CLIENT_SECRET",
    ]
    creds = _get_env_or_secrets(keys)

    missing = [k for k in keys if not creds[k]]
    if missing:
        print(f"❌ Missing X OAuth 2.0 credentials: {', '.join(missing)}")
        return None

    return {
        "access_token": creds["X_OAUTH2_ACCESS_TOKEN"],
        "refresh_token": creds["X_OAUTH2_REFRESH_TOKEN"],
        "client_id": creds["X_CLIENT_ID"],
        "client_secret": creds["X_CLIENT_SECRET"],
    }


def _api_call(method, url, credentials, json_payload=None, params=None, files=None, refresh_once=True):
    """Make an X API v2 call with bearer auth and auto-refresh on 401."""
    headers = {"Authorization": f"Bearer {credentials['access_token']}"}
    if json_payload is not None:
        headers["Content-Type"] = "application/json"

    if method == "GET":
        resp = requests.get(url, headers=headers, params=params, timeout=60)
    elif method == "POST":
        if files:
            resp = requests.post(url, headers=headers, files=files, data=params, timeout=120)
        else:
            resp = requests.post(url, headers=headers, json=json_payload, params=params, timeout=60)
    elif method == "DELETE":
        resp = requests.delete(url, headers=headers, timeout=60)
    else:
        raise ValueError(f"Unsupported method: {method}")

    # Token expired? Try refreshing once and retry.
    if resp.status_code == 401 and refresh_once:
        new_token = _refresh_access_token(
            credentials["client_id"],
            credentials["client_secret"],
            credentials["refresh_token"],
        )
        if new_token:
            credentials["access_token"] = new_token
            # Update in-memory copy so callers see the new token.
            os.environ["X_OAUTH2_ACCESS_TOKEN"] = new_token
            return _api_call(method, url, credentials, json_payload, params, files, refresh_once=False)

    return resp


def _upload_media(credentials, media_path):
    """Upload media to X and return media_id."""
    with open(media_path, "rb") as f:
        files = {"media": (os.path.basename(media_path), f)}
        resp = _api_call(
            "POST",
            "https://api.x.com/2/media/upload",
            credentials,
            params={"media_category": "tweet_image"},
            files=files,
        )

    if resp.status_code in (200, 201):
        data = resp.json()
        return data.get("media_id_string") or data.get("id")

    print(f"❌ X media upload error ({resp.status_code}): {resp.text[:400]}")
    return None


def post_tweet(text, credentials=None, media_path=None, reply_to=None):
    """Post a tweet via X API v2 using OAuth 2.0.

    Returns {"id", "url", "raw"} on success, {"error", "status_code"} on an API
    rejection, or None when credentials are missing. The failure dict is TRUTHY —
    callers must check for an "id", never `if result:`, or a rejected post gets
    reported as live.

    `reply_to` chains this post under an existing tweet id, which is how a
    thread is built; see `post_thread`.
    """
    if not credentials:
        credentials = get_credentials()
    if not credentials:
        return None

    payload = {"text": text}
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": str(reply_to)}
    if media_path:
        media_id = _upload_media(credentials, media_path)
        if media_id:
            payload["media"] = {"media_ids": [str(media_id)]}

    resp = _api_call(
        "POST",
        "https://api.x.com/2/tweets",
        credentials,
        json_payload=payload,
    )

    if resp.status_code in (200, 201):
        data = resp.json()
        tweet_id = data.get("data", {}).get("id", "unknown")
        url = f"https://x.com/user/status/{tweet_id}"
        print(f"✅ Tweet posted: {url}")
        return {"id": tweet_id, "url": url, "raw": data}
    else:
        detail = resp.text[:800]
        print(f"❌ X API error ({resp.status_code}): {detail}")
        return {"error": detail, "status_code": resp.status_code}


def post_thread(posts, credentials=None, media_path=None):
    """Post a list of texts as a chained thread.

    Returns {"ids", "url", "posted", "error"}. Every post is billed separately,
    so a 6-post thread costs six times a single tweet — callers should decide
    deliberately (see MAX_THREAD_POSTS in github_roundup).

    A mid-thread failure stops immediately and reports what did go out. It does
    not roll back: the earlier posts are already public, and deleting them would
    destroy a partially-useful thread that can be finished by hand.
    """
    if not posts:
        return {"ids": [], "posted": 0, "error": "no posts"}
    if not credentials:
        credentials = get_credentials()
    if not credentials:
        return None

    ids, root_url = [], ""
    for i, text in enumerate(posts):
        result = post_tweet(
            text,
            credentials=credentials,
            media_path=media_path if i == 0 else None,
            reply_to=ids[-1] if ids else None,
        )
        if not result or not result.get("id"):
            detail = (result or {}).get("error", "no credentials")
            print(f"❌ thread stopped at post {i + 1}/{len(posts)}: {detail}")
            return {"ids": ids, "url": root_url, "posted": len(ids), "error": detail}
        ids.append(result["id"])
        if i == 0:
            root_url = result.get("url", "")

    return {"ids": ids, "url": root_url, "posted": len(ids), "error": None}


def delete_tweet(tweet_id, credentials=None):
    """Delete a tweet by ID."""
    if not credentials:
        credentials = get_credentials()
    if not credentials:
        return None

    resp = _api_call(
        "DELETE",
        f"https://api.x.com/2/tweets/{tweet_id}",
        credentials,
    )

    if resp.ok:
        print(f"✅ Tweet deleted: {tweet_id}")
        return True
    else:
        print(f"❌ Delete error ({resp.status_code}): {resp.text}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Post to X (Twitter)")
    parser.add_argument("text", nargs="?", help="Tweet text")
    parser.add_argument("--delete", "-d", help="Tweet ID to delete")
    args = parser.parse_args()

    if args.delete:
        delete_tweet(args.delete)
    elif args.text:
        post_tweet(args.text)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
