#!/usr/bin/env python3
"""Create original Build With Abdallah tutorial cover images with readable text."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "templates" / "tutorial_cover.html"
RENDERER = ROOT / "scripts" / "render_card.mjs"


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    base = "/usr/share/fonts/truetype/dejavu"
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = os.path.join(base, name)
    return ImageFont.truetype(path, size) if os.path.exists(path) else ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if draw.textlength(test, font=fnt) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def code_lines_for(code_title: str) -> list[dict[str, str]]:
    if "feature" in code_title.lower():
        return [
            {"text": "Feature::define('new-checkout',", "color": "white"},
            {"text": "  fn (User $user) => match (true) {", "color": "white"},
            {"text": "    $user->is_admin => true,", "color": "green"},
            {"text": "    $user->team->beta => true,", "color": "green"},
            {"text": "    default => false,", "color": "green"},
            {"text": "  }", "color": "white"},
            {"text": ");", "color": "muted"},
        ]
    return [
        {"text": "final class UserProfileData", "color": "white"},
        {"text": "{", "color": "muted"},
        {"text": "  public function __construct(", "color": "white"},
        {"text": "    public readonly string $name,", "color": "green"},
        {"text": "    public readonly string $email,", "color": "green"},
        {"text": "    public readonly string $timezone", "color": "green"},
        {"text": "  ) {}", "color": "white"},
        {"text": "}", "color": "muted"},
    ]


def render_html_cover(title: str, subtitle: str, out: str, workflow: list[str] | None,
                      code_title: str, footer: str, keep_html: bool = False) -> bool:
    data = {
        "brand": "Build With Abdallah",
        "title": title,
        "subtitle": subtitle,
        "workflow": workflow or ["HTTP Request", "DTO", "Service Layer", "Clean Laravel Code"],
        "codeTitle": code_title,
        "codeLines": code_lines_for(code_title),
        "footer": footer,
        "domain": "buildwithabdallah.com",
    }
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "__COVER_DATA__",
        json.dumps(data).replace("</", "<\\/"),
    )
    out_path = Path(out)
    if keep_html:
        html_path = out_path.with_suffix(".html")
        html_path.write_text(html, encoding="utf-8")
    else:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
        html_path = Path(tmp.name)
        tmp.write(html)
        tmp.close()

    try:
        result = subprocess.run(
            ["node", str(RENDERER), str(html_path), str(out_path), "1536", "864"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and out_path.exists():
            print(result.stdout.strip())
            return True
        print((result.stderr or result.stdout).strip())
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"HTML cover render unavailable: {exc}")
        return False
    finally:
        if not keep_html:
            try:
                html_path.unlink()
            except OSError:
                pass


def make_cover_pillow(title: str, subtitle: str, out: str, workflow: list[str] | None = None,
                      code_title: str = "Example.php", footer: str = "Composer package | typed objects | tests") -> str:
    width, height = 1536, 864
    navy = (13, 22, 40)
    panel = (18, 30, 54)
    panel_2 = (23, 38, 66)
    blue = (37, 99, 235)
    cyan = (147, 197, 253)
    green = (52, 211, 153)
    red = (239, 68, 68)
    white = (248, 250, 252)
    muted = (148, 163, 184)

    img = Image.new("RGB", (width, height), navy)
    draw = ImageDraw.Draw(img)

    # Background grid and accent.
    for x in range(0, width, 96):
        draw.line([(x, 0), (x, height)], fill=(22, 35, 58), width=1)
    for y in range(0, height, 96):
        draw.line([(0, y), (width, y)], fill=(22, 35, 58), width=1)
    draw.rectangle([0, 0, width, 14], fill=red)
    draw.rectangle([0, 14, width, 22], fill=blue)

    margin = 96
    left_w = 690
    title_font = font(68)
    title_lines = wrap(draw, title, title_font, left_w)
    while len(title_lines) > 3:
        title_font = font(title_font.size - 6)
        title_lines = wrap(draw, title, title_font, left_w)

    y = 126
    draw.text((margin, y), "Build With Abdallah", fill=cyan, font=font(28, False))
    y += 74
    for line in title_lines:
        draw.text((margin + 3, y + 3), line, fill=(0, 0, 0), font=title_font)
        draw.text((margin, y), line, fill=white, font=title_font)
        y += int(title_font.size * 1.12)

    y += 22
    sub_font = font(32, False)
    for line in wrap(draw, subtitle, sub_font, left_w):
        draw.text((margin, y), line, fill=cyan, font=sub_font)
        y += 46

    # Code editor card.
    card_x, card_y, card_w, card_h = 820, 130, 560, 330
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h], radius=18, fill=panel)
    draw.rectangle([card_x, card_y, card_x + card_w, card_y + 48], fill=panel_2)
    for i, color in enumerate([(248, 113, 113), (251, 191, 36), (52, 211, 153)]):
        draw.ellipse([card_x + 22 + i * 34, card_y + 17, card_x + 38 + i * 34, card_y + 33], fill=color)
    draw.text((card_x + 130, card_y + 14), code_title, fill=muted, font=font(20, False))

    code = [(line["text"], {"white": white, "green": green, "muted": muted}[line["color"]]) for line in code_lines_for(code_title)]
    cy = card_y + 76
    code_font = font(22, False)
    for text, color in code:
        draw.text((card_x + 36, cy), text, fill=color, font=code_font)
        cy += 32

    # Workflow.
    flow_y = 570
    labels = workflow or ["HTTP Request", "DTO", "Service Layer", "Clean Laravel Code"]
    box_w = 270
    gap = 28
    start_x = 150
    for i, label in enumerate(labels):
        x = start_x + i * (box_w + gap)
        draw.rounded_rectangle([x, flow_y, x + box_w, flow_y + 104], radius=16, fill=panel_2, outline=blue, width=3)
        label_font = font(25)
        while draw.textlength(label, font=label_font) > box_w - 34 and label_font.size > 18:
            label_font = font(label_font.size - 2)
        tw = draw.textlength(label, font=label_font)
        draw.text((x + (box_w - tw) / 2, flow_y + 36), label, fill=white, font=label_font)
        if i < len(labels) - 1:
            ax = x + box_w + 7
            ay = flow_y + 52
            draw.line([(ax, ay), (ax + gap - 14, ay)], fill=cyan, width=4)
            draw.polygon([(ax + gap - 14, ay - 9), (ax + gap - 14, ay + 9), (ax + gap, ay)], fill=cyan)

    draw.text((margin, height - 78), footer, fill=muted, font=font(25, False))
    tag = "buildwithabdallah.com"
    tag_font = font(25, False)
    tw = draw.textlength(tag, font=tag_font)
    draw.text((width - margin - tw, height - 78), tag, fill=muted, font=tag_font)

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return out


def make_cover(title: str, subtitle: str, out: str, workflow: list[str] | None = None,
               code_title: str = "Example.php", footer: str = "Composer package | typed objects | tests",
               keep_html: bool = False) -> str:
    if render_html_cover(title, subtitle, out, workflow, code_title, footer, keep_html=keep_html):
        return out
    print("Falling back to Pillow cover renderer.")
    return make_cover_pillow(title, subtitle, out, workflow, code_title, footer)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a readable tutorial cover")
    parser.add_argument("--title", required=True)
    parser.add_argument("--subtitle", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workflow", help="Pipe-separated workflow labels")
    parser.add_argument("--code-title", default="Example.php")
    parser.add_argument("--footer", default="Composer package | typed objects | tests")
    parser.add_argument("--keep-html", action="store_true", help="Write the filled HTML next to the PNG")
    args = parser.parse_args()
    workflow = [p.strip() for p in args.workflow.split("|")] if args.workflow else None
    print(make_cover(args.title, args.subtitle, args.out, workflow, args.code_title, args.footer, args.keep_html))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
