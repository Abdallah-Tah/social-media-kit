#!/usr/bin/env python3
"""Generate social media assets — logos, banners, and cards with Pillow.

Customize colors, text, and sizes via command-line arguments.
"""
import argparse
import math
import os

from PIL import Image, ImageDraw, ImageFont

# ── Defaults ──────────────────────────────────────────────────────────────
DEFAULT_BG = "#0f172a"      # Dark navy
DEFAULT_ACCENT = "#2563eb"  # Electric blue
DEFAULT_TEXT = "#ffffff"    # White
DEFAULT_SUBTEXT = "#93c5fd" # Light blue
OUTPUT_DIR = "assets"


def hex_to_rgb(hex_color):
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def get_font(size, bold=False):
    """Try to load a nice font, fall back to default."""
    font_paths = []
    if bold:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ]
    else:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
        ]

    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def generate_logo(brand_letter="B", size=1024, bg_color=DEFAULT_BG,
                  accent_color=DEFAULT_ACCENT, output_dir=OUTPUT_DIR):
    """Generate a circular logo with a brand letter."""
    img = Image.new("RGBA", (size, size), hex_to_rgb(bg_color) + (255,))
    draw = ImageDraw.Draw(img)

    # Circle background
    cx, cy = size // 2, size // 2
    radius = int(size * 0.37)
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=hex_to_rgb(accent_color) + (255,)
    )

    # Brand letter
    font = get_font(int(size * 0.5), bold=True)
    bbox = draw.textbbox((0, 0), brand_letter, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (size - text_w) // 2 - bbox[0]
    text_y = (size - text_h) // 2 - bbox[1] - int(size * 0.02)
    draw.text((text_x, text_y), brand_letter, fill=(255, 255, 255, 255), font=font)

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "logo.png")
    img.convert("RGB").save(path, "PNG")
    print(f"✅ Logo saved: {path} ({size}x{size})")
    return path


def generate_banner(brand_name="BrandName", tagline="Tagline Here",
                   width=1640, height=660, bg_color=DEFAULT_BG,
                   accent_color=DEFAULT_ACCENT, output_dir=OUTPUT_DIR):
    """Generate a social media banner."""
    img = Image.new("RGBA", (width, height), hex_to_rgb(bg_color) + (255,))
    draw = ImageDraw.Draw(img)

    # Diagonal stripes
    accent_rgb = hex_to_rgb(accent_color)
    for i in range(0, width + height, 40):
        draw.polygon([
            (i, height), (i + 200, 0), (i + 240, 0), (i + 40, height)
        ], fill=accent_rgb + (30,))

    # Brand name
    font = get_font(72, bold=True)
    bbox = draw.textbbox((0, 0), brand_name, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (width - tw) // 2
    ty = (height - th) // 2 - 30

    draw.text((tx + 3, ty + 3), brand_name, fill=(0, 0, 0, 128), font=font)
    draw.text((tx, ty), brand_name, fill=(255, 255, 255, 255), font=font)

    # Tagline
    sub_font = get_font(28)
    bbox2 = draw.textbbox((0, 0), tagline, font=sub_font)
    sw = bbox2[2] - bbox2[0]
    sx = (width - sw) // 2
    sy = ty + th + 20
    draw.text((sx, sy), tagline, fill=hex_to_rgb(DEFAULT_SUBTEXT) + (255,), font=sub_font)

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "banner.png")
    img.convert("RGB").save(path, "PNG")
    print(f"✅ Banner saved: {path} ({width}x{height})")
    return path


def generate_card(title, subtitle="", width=1080, height=1080,
                  bg_color=DEFAULT_BG, accent_color=DEFAULT_ACCENT,
                  output_dir=OUTPUT_DIR):
    """Generate a social media card (square)."""
    img = Image.new("RGBA", (width, height), hex_to_rgb(bg_color) + (255,))
    draw = ImageDraw.Draw(img)

    # Accent bar at top
    draw.rectangle([0, 0, width, 8], fill=hex_to_rgb(accent_color) + (255,))

    def wrap_text(text, font, max_width):
        words = text.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            box = draw.textbbox((0, 0), test, font=font)
            if box[2] - box[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    # Title. Long technical titles are common, so wrap and shrink until the
    # text fits inside the card instead of cropping off-canvas.
    max_text_width = int(width * 0.82)
    title_size = 64
    title_font = get_font(title_size, bold=True)
    title_lines = wrap_text(title, title_font, max_text_width)
    while (len(title_lines) > 4 or title_size * 1.18 * len(title_lines) > height * 0.34) and title_size > 38:
        title_size -= 4
        title_font = get_font(title_size, bold=True)
        title_lines = wrap_text(title, title_font, max_text_width)

    line_height = int(title_size * 1.18)

    # Subtitle
    sub_lines = []
    sub_font = None
    if subtitle:
        sub_size = 32
        sub_font = get_font(sub_size)
        sub_lines = wrap_text(subtitle, sub_font, max_text_width)
        while len(sub_lines) > 2 and sub_size > 24:
            sub_size -= 2
            sub_font = get_font(sub_size)
            sub_lines = wrap_text(subtitle, sub_font, max_text_width)

    sub_height = (len(sub_lines) * int((sub_font.size if hasattr(sub_font, "size") else 32) * 1.25)) if sub_lines else 0
    total_height = line_height * len(title_lines) + (30 + sub_height if sub_lines else 0)
    y = (height - total_height) // 2

    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        tx = (width - (bbox[2] - bbox[0])) // 2
        draw.text((tx, y), line, fill=(255, 255, 255, 255), font=title_font)
        y += line_height

    if sub_lines and sub_font:
        y += 30
        sub_line_height = int(sub_font.size * 1.25) if hasattr(sub_font, "size") else 40
        for line in sub_lines:
            bbox = draw.textbbox((0, 0), line, font=sub_font)
            sx = (width - (bbox[2] - bbox[0])) // 2
            draw.text((sx, y), line, fill=hex_to_rgb(DEFAULT_SUBTEXT) + (255,), font=sub_font)
            y += sub_line_height

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "card.png")
    img.convert("RGB").save(path, "PNG")
    print(f"✅ Card saved: {path} ({width}x{height})")
    return path


def main():
    parser = argparse.ArgumentParser(description="Generate social media assets")
    parser.add_argument("--logo", action="store_true", help="Generate logo")
    parser.add_argument("--banner", action="store_true", help="Generate banner")
    parser.add_argument("--card", action="store_true", help="Generate social card")
    parser.add_argument("--all", action="store_true", help="Generate all assets")
    parser.add_argument("--brand", default="B", help="Brand letter for logo")
    parser.add_argument("--name", default="BrandName", help="Brand name for banner")
    parser.add_argument("--tagline", default="Tagline Here", help="Banner tagline")
    parser.add_argument("--title", default="Title", help="Card title")
    parser.add_argument("--subtitle", default="", help="Card subtitle")
    parser.add_argument("--bg", default=DEFAULT_BG, help="Background color (hex)")
    parser.add_argument("--accent", default=DEFAULT_ACCENT, help="Accent color (hex)")
    parser.add_argument("--output", "-o", default=OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    if not any([args.logo, args.banner, args.card, args.all]):
        args.all = True

    if args.logo or args.all:
        generate_logo(args.brand, bg_color=args.bg, accent_color=args.accent, output_dir=args.output)
    if args.banner or args.all:
        generate_banner(args.name, args.tagline, bg_color=args.bg, accent_color=args.accent, output_dir=args.output)
    if args.card or args.all:
        generate_card(args.title, args.subtitle, bg_color=args.bg, accent_color=args.accent, output_dir=args.output)


if __name__ == "__main__":
    main()
