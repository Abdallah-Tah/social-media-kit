"""Pitch Agent — small social media publisher helpers.

Preferred environment names match the main social-media-kit publishers:
``FB_PAGE_ID`` and ``FB_PAGE_TOKEN``. The older ``FACEBOOK_PAGE_ID`` and
``FACEBOOK_ACCESS_TOKEN`` names remain as backward-compatible fallbacks.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

ROOT = Path(os.environ.get("SMKIT_ROOT", Path(__file__).resolve().parents[1]))
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class SocialPublisher:
    def __init__(self):
        self.fb_page_id = os.environ.get("FB_PAGE_ID") or os.environ.get("FACEBOOK_PAGE_ID", "")
        self.fb_token = os.environ.get("FB_PAGE_TOKEN") or os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
        self.telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.telegram_topic = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID", "")

    def publish_facebook(self, image_path, title, pillar):
        """Publish a photo post to Facebook."""
        if not self.fb_token:
            print("[pitch-agent] No FB_PAGE_TOKEN. Skipping Facebook.", file=sys.stderr)
            return None
        if not self.fb_page_id:
            print("[pitch-agent] No FB_PAGE_ID. Skipping Facebook.", file=sys.stderr)
            return None

        message = (
            f"⚽ {title}\n\n"
            "World Cup football analytics from The Pitch Agent.\n\n"
            "Educational predictions from public data, not betting advice.\n"
            "Independent analytics, not affiliated with FIFA.\n\n"
            "#WorldCup2026 #Football #BuildWithAbdallah"
        )

        url = f"https://graph.facebook.com/v21.0/{self.fb_page_id}/photos"
        with open(image_path, "rb") as img:
            files = {"source": img}
            data = {
                "message": message,
                "access_token": self.fb_token,
            }
            r = requests.post(url, files=files, data=data, timeout=60)

        if r.status_code == 200:
            print(f"[pitch-agent] Facebook post published: {r.json().get('id', 'OK')}")
            return r.json()
        print(f"[pitch-agent] Facebook post failed: {r.status_code} {r.text}", file=sys.stderr)
        return None

    def send_telegram_review(self, image_path, pillar, mode, match_count):
        """Send a preview card to Telegram for review."""
        if not self.telegram_token or not self.telegram_chat:
            print("[pitch-agent] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing. Skipping Telegram.", file=sys.stderr)
            return None

        caption = (
            f"⚽ <b>Pitch Agent Review</b>\n\n"
            f"Pillar: <code>{pillar}</code>\n"
            f"Mode: <code>{mode}</code>\n"
            f"Matches: <code>{match_count}</code>\n\n"
            f"Reply with <b>APPROVE</b> to publish, or <b>REJECT</b> to cancel.\n\n"
            f"BuildWithAbdallah.com | Educational predictions | Not betting advice | Not affiliated with FIFA"
        )

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendPhoto"
        with open(image_path, "rb") as img:
            files = {"photo": img}
            data = {
                "chat_id": self.telegram_chat,
                "caption": caption,
                "parse_mode": "HTML",
            }
            if self.telegram_topic:
                data["message_thread_id"] = self.telegram_topic
            r = requests.post(url, files=files, data=data, timeout=60)

        if r.status_code == 200:
            print("[pitch-agent] Telegram review sent.")
            return r.json()
        print(f"[pitch-agent] Telegram review failed: {r.status_code} {r.text}", file=sys.stderr)
        return None

    def send_telegram_notification(self, image_path, pillar, mode, match_count):
        """Send a published notification to Telegram."""
        if not self.telegram_token or not self.telegram_chat:
            return None

        caption = (
            f"⚽ <b>Pitch Agent Published</b>\n\n"
            f"Pillar: <code>{pillar}</code>\n"
            f"Mode: <code>{mode}</code>\n"
            f"Matches: <code>{match_count}</code>\n\n"
            f"Posted to Facebook ✅\n\n"
            f"BuildWithAbdallah.com | Educational predictions | Not betting advice | Not affiliated with FIFA"
        )

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendPhoto"
        with open(image_path, "rb") as img:
            files = {"photo": img}
            data = {
                "chat_id": self.telegram_chat,
                "caption": caption,
                "parse_mode": "HTML",
            }
            if self.telegram_topic:
                data["message_thread_id"] = self.telegram_topic
            r = requests.post(url, files=files, data=data, timeout=60)

        if r.status_code == 200:
            print("[pitch-agent] Telegram notification sent.")
            return r.json()
        print(f"[pitch-agent] Telegram notification failed: {r.status_code}", file=sys.stderr)
        return None
