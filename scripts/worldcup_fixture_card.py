#!/usr/bin/env python3
"""World Cup fixture card generator — Build With Abdallah branded.

Fetches fixtures from football-data.org API and renders a branded card
matching the exact template in the reference image.

Usage:
    python scripts/worldcup_fixture_card.py --out content/assets/worldcup_fixtures.png
    python scripts/worldcup_fixture_card.py --days 7 --out /tmp/wc_card.png
"""
import os
import sys
import json
import argparse
import datetime
from urllib.parse import urlencode

import requests
from PIL import Image, ImageDraw, ImageFont

# ── Config ──────────────────────────────────────────────────────
API_BASE = "https://api.football-data.org/v4"
COMPETITION = "WC"  # World Cup
TEAM_COLORS = {
    # Mapping team names to flag emoji or color — optional enhancement
}

# Brand colors (from Build With Abdallah)
BRAND_BLUE = "#2563eb"
BRAND_DARK = "#0f172a"
BRAND_TEXT = "#334155"
BRAND_LIGHT = "#f1f5f9"
BRAND_WHITE = "#ffffff"

# ── API ───────────────────────────────────────────────────────────
def fetch_fixtures(days_ahead=14, api_key=None):
    """Fetch upcoming World Cup fixtures from football-data.org."""
    key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        # Try demo key limit or fail gracefully
        print("Warning: FOOTBALL_DATA_API_KEY not set. Using demo (limited).", file=sys.stderr)
    headers = {"X-Auth-Token": key} if key else {}

    now = datetime.datetime.utcnow()
    date_from = now.strftime("%Y-%m-%d")
    date_to = (now + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    url = f"{API_BASE}/competitions/{COMPETITION}/matches"
    params = {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED"}

    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    matches = data.get("matches", [])

    # Sort by date
    matches.sort(key=lambda m: m.get("utcDate", ""))
    return matches


def group_name(match):
    """Extract group name like 'Group A'."""
    stage = match.get("stage", "")
    if "GROUP" in stage:
        return stage.replace("GROUP_STAGE_", "Group ")
    return stage.replace("_", " ").title()


def format_fixture(match):
    """Format a single match into display components."""
    home = match.get("homeTeam", {}).get("name", "TBD")
    away = match.get("awayTeam", {}).get("name", "TBD")
    date_str = match.get("utcDate", "")
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        display_date = dt.strftime("%Y-%m-%d")
    except Exception:
        display_date = date_str[:10]
    return {
        "match": f"{home} vs {away}",
        "group": group_name(match),
        "date": display_date,
    }


# ── Card Rendering ──────────────────────────────────────────────
def render_card(fixtures, out_path, title="Upcoming World Cup Matches"):
    """Render a branded fixture card using Pillow."""
    # Canvas size (landscape, ~16:9)
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), BRAND_WHITE)
    draw = ImageDraw.Draw(img)

    # Try to load fonts — fall back to defaults
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)
        font_sub = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        font_item = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = font_title
        font_item = font_title
        font_small = font_title

    # Header background shape (blue accent top-left)
    draw.polygon([(0, 0), (400, 0), (0, 300)], fill=BRAND_BLUE)

    # Logo text
    draw.text((60, 40), "Build With Abdallah", fill=BRAND_WHITE, font=font_sub)
    draw.text((60, 80), "SOFTWARE • AUTOMATION • APIs • SOLUTIONS", fill=BRAND_WHITE, font=font_small)

    # Title
    draw.text((60, 200), title, fill=BRAND_DARK, font=font_title)
    draw.text((60, 280), "World Cup 2026 • Fixture data • football-data.org", fill=BRAND_TEXT, font=font_sub)

    # Fixture list
    y = 360
    x_match = 80
    x_group = 1100
    x_date = 1400

    # Column headers
    draw.text((x_match, y), "Fixture", fill=BRAND_BLUE, font=font_item)
    draw.text((x_group, y), "Group", fill=BRAND_BLUE, font=font_item)
    draw.text((x_date, y), "Date", fill=BRAND_BLUE, font=font_item)
    y += 50

    # Separator line
    draw.line([(x_match, y), (1650, y)], fill=BRAND_LIGHT, width=2)
    y += 20

    for fx in fixtures[:10]:  # Max 10 fixtures
        draw.text((x_match, y), f"•  {fx['match']}", fill=BRAND_DARK, font=font_item)
        draw.text((x_group, y), fx["group"], fill=BRAND_BLUE, font=font_item)
        draw.text((x_date, y), fx["date"], fill=BRAND_TEXT, font=font_item)
        y += 60

    # Footer
    footer_y = H - 60
    draw.text((60, footer_y), "The Pitch Agent by BuildWithAbdallah | Independent analytics | Not affiliated with FIFA",
              fill=BRAND_TEXT, font=font_small)

    # Bottom-right blue accent
    draw.polygon([(W, H), (W-200, H), (W, H-200)], fill=BRAND_BLUE)

    img.save(out_path, "PNG")
    return out_path


# ── CLI ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="World Cup fixture card generator")
    parser.add_argument("--out", required=True, help="Output image path")
    parser.add_argument("--days", type=int, default=14, help="Days ahead to fetch")
    parser.add_argument("--api-key", default=os.environ.get("FOOTBALL_DATA_API_KEY", ""),
                        help="football-data.org API key")
    parser.add_argument("--title", default="Upcoming World Cup Matches", help="Card title")
    args = parser.parse_args()

    print("Fetching fixtures...", file=sys.stderr)
    matches = fetch_fixtures(args.days, args.api_key)
    fixtures = [format_fixture(m) for m in matches]
    print(f"Found {len(fixtures)} fixtures", file=sys.stderr)

    if not fixtures:
        print("No fixtures found. Exiting.", file=sys.stderr)
        sys.exit(1)

    print(f"Rendering card to {args.out}...", file=sys.stderr)
    path = render_card(fixtures, args.out, args.title)
    print(path)


if __name__ == "__main__":
    main()
