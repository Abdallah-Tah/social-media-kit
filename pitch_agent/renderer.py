"""Pitch Agent — branded card renderer matching the Build With Abdallah template.

Renders fixture lists with:
- Blue polygon accent top-left
- Build With Abdallah logo text
- "Software • Automation • APIs • Solutions" tagline
- Clean fixture list (bullet, match, group, date)
- Footer: "The Pitch Agent by BuildWithAbdallah | Independent analytics | Not affiliated with FIFA"
- Blue polygon accent bottom-right
"""
import os
from PIL import Image, ImageDraw, ImageFont

# Brand colors
BRAND_BLUE = "#2563eb"
BRAND_DARK = "#0f172a"
BRAND_TEXT = "#334155"
BRAND_LIGHT = "#f1f5f9"
BRAND_WHITE = "#ffffff"

# Canvas size options
SIZES = {
    "landscape": (1920, 1080),
    "square": (1080, 1080),
    "portrait": (1080, 1920),
}


class BrandedCardRenderer:
    def __init__(self, mode="fan_mode", size="landscape"):
        self.mode = mode
        self.size = size
        self.W, self.H = SIZES.get(size, SIZES["landscape"])

    def render(self, matches, out_path, title="Upcoming World Cup Matches"):
        """Render a branded fixture card."""
        from pitch_agent.fixtures import format_match
        fixtures = [format_match(m) for m in matches[:12]]

        img = Image.new("RGB", (self.W, self.H), BRAND_WHITE)
        draw = ImageDraw.Draw(img)

        # Load fonts
        fonts = self._load_fonts()

        # Blue polygon accent top-left
        self._draw_top_left_accent(draw)

        # Logo text
        self._draw_logo(draw, fonts)

        # Title
        self._draw_title(draw, fonts, title)

        # Subtitle
        self._draw_subtitle(draw, fonts)

        # Fixture list
        self._draw_fixtures(draw, fonts, fixtures)

        # Footer
        self._draw_footer(draw, fonts)

        # Blue polygon accent bottom-right
        self._draw_bottom_right_accent(draw)

        img.save(out_path, "PNG")
        return out_path

    def _load_fonts(self):
        """Load fonts with fallbacks."""
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

        def find_font(bold=False):
            for p in font_paths:
                if os.path.exists(p):
                    if bold and "Bold" in p:
                        return p
                    if not bold and "Bold" not in p:
                        return p
            return font_paths[0] if font_paths else None

        try:
            return {
                "title": ImageFont.truetype(find_font(bold=True), 72),
                "subtitle": ImageFont.truetype(find_font(), 32),
                "logo": ImageFont.truetype(find_font(bold=True), 40),
                "tagline": ImageFont.truetype(find_font(), 20),
                "item": ImageFont.truetype(find_font(), 32),
                "item_bold": ImageFont.truetype(find_font(bold=True), 32),
                "header": ImageFont.truetype(find_font(bold=True), 28),
                "footer": ImageFont.truetype(find_font(), 22),
                "small": ImageFont.truetype(find_font(), 18),
            }
        except Exception:
            default = ImageFont.load_default()
            return {k: default for k in ["title", "subtitle", "logo", "tagline", "item", "item_bold", "header", "footer", "small"]}

    def _draw_top_left_accent(self, draw):
        """Blue polygon in top-left corner."""
        draw.polygon([(0, 0), (380, 0), (0, 320)], fill=BRAND_BLUE)

    def _draw_bottom_right_accent(self, draw):
        """Blue polygon in bottom-right corner."""
        draw.polygon([(self.W, self.H), (self.W - 220, self.H), (self.W, self.H - 220)], fill=BRAND_BLUE)

    def _draw_logo(self, draw, fonts):
        """Draw Build With Abdallah logo text inside the blue polygon."""
        draw.text((50, 50), "Build With Abdallah", fill=BRAND_WHITE, font=fonts["logo"])
        draw.text((50, 100), "SOFTWARE  •  AUTOMATION  •  APIs  •  SOLUTIONS", fill=BRAND_WHITE, font=fonts["tagline"])

    def _draw_title(self, draw, fonts, title):
        """Main title below the logo area."""
        draw.text((60, 240), title, fill=BRAND_DARK, font=fonts["title"])

    def _draw_subtitle(self, draw, fonts):
        """Subtitle line."""
        draw.text((60, 330), "World Cup 2026 • Fixture data • football-data.org", fill=BRAND_TEXT, font=fonts["subtitle"])

    def _draw_fixtures(self, draw, fonts, fixtures):
        """Fixture list with columns."""
        y = 420
        x_bullet = 80
        x_match = 100
        x_group = 1100
        x_date = 1450

        # Column headers
        draw.text((x_match, y), "Fixture", fill=BRAND_BLUE, font=fonts["header"])
        draw.text((x_group, y), "Group", fill=BRAND_BLUE, font=fonts["header"])
        draw.text((x_date, y), "Date", fill=BRAND_BLUE, font=fonts["header"])
        y += 45

        # Separator line
        draw.line([(x_match, y), (1600, y)], fill=BRAND_LIGHT, width=2)
        y += 25

        for fx in fixtures:
            # Bullet
            draw.ellipse([(x_bullet, y + 12), (x_bullet + 10, y + 22)], fill=BRAND_BLUE)

            # Match text
            match_text = fx["match"]
            draw.text((x_match, y), match_text, fill=BRAND_DARK, font=fonts["item"])

            # Group
            draw.text((x_group, y), fx["group"], fill=BRAND_BLUE, font=fonts["item_bold"])

            # Date
            draw.text((x_date, y), fx["date"], fill=BRAND_TEXT, font=fonts["item"])

            y += 55

            # Stop if we're getting too close to footer
            if y > self.H - 150:
                break

    def _draw_footer(self, draw, fonts):
        """Footer text."""
        footer_y = self.H - 70
        draw.text((60, footer_y), "The Pitch Agent by BuildWithAbdallah | Independent analytics | Not affiliated with FIFA",
                  fill=BRAND_TEXT, font=fonts["footer"])

        # Small "Branded content" label
        draw.text((60, footer_y + 30), "Generated by Pitch Agent — Build With Abdallah",
                  fill=BRAND_LIGHT, font=fonts["small"])
