#!/usr/bin/env python3
"""Original World Cup-style thumbnail generator for football Shorts.

Uses SVG plus ImageMagick so the cron path does not depend on Pillow.
"""
from __future__ import annotations

import argparse
import html
import shutil
import subprocess
from pathlib import Path

W, H = 1280, 720


def _wrap(text: str, max_chars: int = 22) -> list[str]:
    words = text.replace("—", "-").split()
    lines: list[str] = []
    line = ""
    for word in words:
        trial = f"{line} {word}".strip()
        if len(trial) <= max_chars:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines[:3]


def _svg(title: str, kicker: str, kind: str, footer: str) -> str:
    title = " ".join(title.split())[:88].upper()
    kicker = kicker.upper()
    kind = kind.upper()
    footer = footer.upper()
    lines = _wrap(title)
    size = 82 if len(lines) <= 2 else 70
    y0 = 250 if len(lines) == 1 else 205 if len(lines) == 2 else 178
    title_spans = "\n".join(
        f'<text x="{W/2}" y="{y0 + i * (size + 12)}" text-anchor="middle" '
        f'font-family="DejaVu Sans Condensed, DejaVu Sans, Arial, sans-serif" font-size="{size}" '
        f'font-weight="900" fill="#ffffff" stroke="#02181c" stroke-width="5" '
        f'paint-order="stroke">{html.escape(line)}</text>'
        for i, line in enumerate(lines)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <linearGradient id="grass" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#075f48"/>
      <stop offset="1" stop-color="#10835f"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#001512" flood-opacity="0.55"/>
    </filter>
  </defs>
  <rect width="1280" height="720" fill="url(#grass)"/>
  <g opacity="0.22">
    <polygon points="-110,0 -40,0 220,720 110,720" fill="#1fb377"/>
    <polygon points="150,0 230,0 500,720 385,720" fill="#1fb377"/>
    <polygon points="430,0 510,0 780,720 665,720" fill="#1fb377"/>
    <polygon points="710,0 790,0 1060,720 945,720" fill="#1fb377"/>
    <polygon points="990,0 1070,0 1340,720 1225,720" fill="#1fb377"/>
  </g>
  <g fill="none" stroke="#d4fff0" stroke-width="5" opacity="0.72">
    <rect x="88" y="70" width="1104" height="580"/>
    <line x1="640" y1="70" x2="640" y2="650"/>
    <circle cx="640" cy="360" r="116"/>
    <rect x="88" y="230" width="150" height="260"/>
    <rect x="1042" y="230" width="150" height="260"/>
  </g>
  <rect width="1280" height="720" fill="#001416" opacity="0.38"/>
  <rect x="68" y="54" width="1144" height="612" rx="34" fill="#02191d" opacity="0.78" stroke="#d4fff0" stroke-width="3"/>

  <g filter="url(#shadow)">
    <rect x="104" y="86" width="382" height="64" rx="22" fill="#f4c430" stroke="#ffffff" stroke-width="2"/>
    <text x="295" y="128" text-anchor="middle" font-family="DejaVu Sans Condensed, DejaVu Sans, Arial, sans-serif" font-size="34" font-weight="900" fill="#062228">{html.escape(kicker)}</text>
    <rect x="794" y="86" width="382" height="64" rx="22" fill="#0d9488" stroke="#ffffff" stroke-width="2"/>
    <text x="985" y="128" text-anchor="middle" font-family="DejaVu Sans Condensed, DejaVu Sans, Arial, sans-serif" font-size="32" font-weight="900" fill="#ffffff">{html.escape(kind)}</text>
  </g>

  {title_spans}

  <g transform="translate(162 548)" filter="url(#shadow)">
    <circle r="55" fill="#f8fafc" stroke="#0f172a" stroke-width="6"/>
    <polygon points="0,-19 18,-6 11,17 -11,17 -18,-6" fill="#0f172a"/>
    <line x1="0" y1="0" x2="-48" y2="-24" stroke="#0f172a" stroke-width="5"/>
    <line x1="0" y1="0" x2="48" y2="-24" stroke="#0f172a" stroke-width="5"/>
    <line x1="0" y1="0" x2="-28" y2="45" stroke="#0f172a" stroke-width="5"/>
    <line x1="0" y1="0" x2="28" y2="45" stroke="#0f172a" stroke-width="5"/>
  </g>

  <g transform="translate(1085 500)" filter="url(#shadow)" fill="#f4c430" stroke="#7d5411" stroke-width="5">
    <path d="M-55,-70 C-58,-20 -42,35 0,42 C42,35 58,-20 55,-70 Z"/>
    <path d="M-105,-48 C-104,18 -72,45 -38,45" fill="none" stroke-width="12"/>
    <path d="M105,-48 C104,18 72,45 38,45" fill="none" stroke-width="12"/>
    <rect x="-37" y="24" width="74" height="70" rx="8"/>
    <rect x="-76" y="88" width="152" height="30" rx="8"/>
  </g>

  <rect x="292" y="548" width="696" height="65" rx="22" fill="#ffffff" opacity="0.92"/>
  <text x="640" y="591" text-anchor="middle" font-family="DejaVu Sans Condensed, DejaVu Sans, Arial, sans-serif" font-size="34" font-weight="900" fill="#053636">DAILY PICKS • RECAPS • RULES</text>
  <text x="640" y="657" text-anchor="middle" font-family="DejaVu Sans Condensed, DejaVu Sans, Arial, sans-serif" font-size="26" font-weight="800" fill="#d9fff0">{html.escape(footer)}</text>
</svg>
"""


def generate_thumbnail(
    out_path: str | Path,
    *,
    title: str,
    kicker: str = "WORLD CUP 2026",
    kind: str = "AI PREDICTION",
    footer: str = "THE PITCH AGENT | BUILD WITH ABDALLAH",
) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    svg_path = out.with_suffix(".svg")
    svg_path.write_text(_svg(title, kicker, kind, footer), encoding="utf-8")
    convert = shutil.which("convert")
    if not convert:
        raise RuntimeError("ImageMagick convert is not installed")
    cmd = [convert, "-background", "white", str(svg_path), "-quality", "92", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--kicker", default="WORLD CUP 2026")
    ap.add_argument("--kind", default="AI PREDICTION")
    args = ap.parse_args()
    print(generate_thumbnail(args.out, title=args.title, kicker=args.kicker, kind=args.kind))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
