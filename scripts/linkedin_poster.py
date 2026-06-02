#!/usr/bin/env python3
"""LinkedIn posting script.

Post text updates or article shares to LinkedIn using the API.
Requires LINKEDIN_ACCESS_TOKEN in secrets.env (run linkedin_oauth.py first).
"""
import os
import sys
import json
import argparse
import requests

ACCESS_TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
SECRETS_PATH = os.environ.get(
    "SECRETS_PATH",
    os.path.expanduser("~/.config/social-media-kit/secrets.env"),
)


def load_token():
    """Load LinkedIn access token from secrets.env if not in env."""
    global ACCESS_TOKEN
    if ACCESS_TOKEN:
        return ACCESS_TOKEN

    if os.path.exists(SECRETS_PATH):
        with open(SECRETS_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("LINKEDIN_ACCESS_TOKEN="):
                    ACCESS_TOKEN = line.split("=", 1)[1]
                    return ACCESS_TOKEN

    print("❌ LINKEDIN_ACCESS_TOKEN not found. Run scripts/linkedin_oauth.py first.")
    return None


def get_profile(token):
    """Get the authenticated user's LinkedIn URN."""
    resp = requests.get(
        "https://api.linkedin.com/v2/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.ok:
        data = resp.json()
        return data.get("id", "")
    else:
        print(f"❌ LinkedIn profile error: {resp.text}")
        return None


def _upload_image(token, author, image_path):
    """Register + upload an image, returning its asset URN (or None)."""
    reg = requests.post(
        "https://api.linkedin.com/v2/assets?action=registerUpload",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": author,
                "serviceRelationships": [
                    {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
                ],
            }
        },
        timeout=30,
    )
    if not reg.ok:
        print(f"❌ LinkedIn registerUpload error: {reg.text[:200]}")
        return None
    value = reg.json()["value"]
    upload_url = value["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    asset = value["asset"]
    with open(image_path, "rb") as f:
        up = requests.put(
            upload_url,
            headers={"Authorization": f"Bearer {token}"},
            data=f.read(),
            timeout=60,
        )
    if up.status_code not in (200, 201):
        print(f"❌ LinkedIn image upload error ({up.status_code})")
        return None
    return asset


def post_text(text, visibility="PUBLIC", image_path=None):
    """Post a text (or image) update to LinkedIn."""
    token = load_token()
    if not token:
        return None

    # Get profile URN
    profile_id = get_profile(token)
    if not profile_id:
        return None

    author = f"urn:li:person:{profile_id}"

    content = {"shareCommentary": {"text": text}, "shareMediaCategory": "NONE"}
    if image_path:
        asset = _upload_image(token, author, image_path)
        if asset:
            content["shareMediaCategory"] = "IMAGE"
            content["media"] = [{"status": "READY", "media": asset}]

    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.PostContent": content},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers=headers,
        json=payload,
    )

    if resp.status_code in (200, 201):
        print(f"✅ Posted to LinkedIn")
        return resp.json()
    else:
        print(f"❌ LinkedIn error ({resp.status_code}): {resp.text}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Post to LinkedIn")
    parser.add_argument("text", nargs="?", help="Post text")
    parser.add_argument("--visibility", "-v", default="PUBLIC", choices=["PUBLIC", "CONNECTIONS"])
    args = parser.parse_args()

    if args.text:
        post_text(args.text, visibility=args.visibility)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()