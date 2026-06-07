"""Pitch Agent — social media publisher.

Posts to:
- Facebook (photo post)
- Telegram (review/notification)
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/social-media-kit/scripts"))

import requests


class SocialPublisher:
    def __init__(self):
        self.fb_page_id = os.environ.get("FACEBOOK_PAGE_ID", "")
        self.fb_token = os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
        self.telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "-1003948211258")
        self.telegram_topic = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID", "14119")

    def publish_facebook(self, image_path, title, pillar):
        """Publish a photo post to Facebook."""
        if not self.fb_token:
            print("[pitch-agent] No FACEBOOK_ACCESS_TOKEN. Skipping Facebook.", file=sys.stderr)
            return

        message = f"⚽ {title}\n\nWorld Cup 2026 fixtures and analysis.\n\nData: football-data.org\nFull schedule: https://buildwithabdallah.com/world-cup-fixtures\n\n#WorldCup2026 #Football #BuildWithAbdallah"

        url = f"https://graph.facebook.com/v18.0/{self.fb_page_id}/photos"
        with open(image_path, "rb") as img:
            files = {"file": img}
            data = {
                "message": message,
                "access_token": self.fb_token,
            }
            r = requests.post(url, files=files, data=data, timeout=60)

        if r.status_code == 200:
            print(f"[pitch-agent] Facebook post published: {r.json().get('id', 'OK')}")
        else:
            print(f"[pitch-agent] Facebook post failed: {r.status_code} {r.text}", file=sys.stderr)

    def send_telegram_review(self, image_path, pillar, mode, match_count):
        """Send a preview card to Telegram for review."""
        if not self.telegram_token:
            print("[pitch-agent] No TELEGRAM_BOT_TOKEN. Skipping Telegram.", file=sys.stderr)
            return

        caption = (
            f"🌮 <b>Pitch Agent Review</b>\n\n"
            f"Pillar: <code>{pillar}</code>\n"
            f"Mode: <code>{mode}</code>\n"
            f"Matches: <code>{match_count}</code>\n\n"
            f"Reply with <b>APPROVE</b> to publish, or <b>REJECT</b> to cancel.\n\n"
            f"The Pitch Agent by BuildWithAbdallah"
        )

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendPhoto"
        with open(image_path, "rb") as img:
            files = {"photo": img}
            data = {
                "chat_id": self.telegram_chat,
                "message_thread_id": self.telegram_topic,
                "caption": caption,
                "parse_mode": "HTML",
            }
            r = requests.post(url, files=files, data=data, timeout=60)

        if r.status_code == 200:
            print("[pitch-agent] Telegram review sent.")
        else:
            print(f"[pitch-agent] Telegram review failed: {r.status_code} {r.text}", file=sys.stderr)

    def send_telegram_notification(self, image_path, pillar, mode, match_count):
        """Send a published notification to Telegram."""
        if not self.telegram_token:
            return

        caption = (
            f"🌮 <b>Pitch Agent Published</b>\n\n"
            f"Pillar: <code>{pillar}</code>\n"
            f"Mode: <code>{mode}</code>\n"
            f"Matches: <code>{match_count}</code>\n\n"
            f"Posted to Facebook ✅\n\n"
            f"The Pitch Agent by BuildWithAbdallah"
        )

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendPhoto"
        with open(image_path, "rb") as img:
            files = {"photo": img}
            data = {
                "chat_id": self.telegram_chat,
                "message_thread_id": self.telegram_topic,
                "caption": caption,
                "parse_mode": "HTML",
            }
            r = requests.post(url, files=files, data=data, timeout=60)

        if r.status_code == 200:
            print("[pitch-agent] Telegram notification sent.")
        else:
            print(f"[pitch-agent] Telegram notification failed: {r.status_code}", file=sys.stderr)
