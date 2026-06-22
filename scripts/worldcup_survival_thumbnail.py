#!/usr/bin/env python3
"""Original thumbnail generator for World Cup Survival Lab Shorts."""
from __future__ import annotations

import argparse
import html
import shutil
import subprocess
from pathlib import Path

W, H = 1280, 720


def _wrap(text: str, max_chars: int = 18) -> list[str]:
    words = text.split()
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


def _svg(title: str, badge: str) -> str:
    lines = _wrap(title.upper())
    y0 = 204 if len(lines) == 1 else 166 if len(lines) == 2 else 132
    title_svg = "\n".join(
        f'<text x="640" y="{y0 + i * 88}" text-anchor="middle" '
        f'font-family="DejaVu Sans Condensed, DejaVu Sans, Arial, sans-serif" '
        f'font-size="82" font-weight="900" fill="#ffffff" stroke="#061a44" '
        f'stroke-width="5" paint-order="stroke">{html.escape(line)}</text>'
        for i, line in enumerate(lines)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#071a44"/>
      <stop offset="0.48" stop-color="#0b4d92"/>
      <stop offset="1" stop-color="#0d9488"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="9" stdDeviation="10" flood-color="#00101f" flood-opacity="0.45"/>
    </filter>
  </defs>
  <rect width="1280" height="720" fill="url(#bg)"/>
  <g opacity="0.18" stroke="#d7fbff" stroke-width="4" fill="none">
    <rect x="94" y="104" width="1092" height="512" rx="30"/>
    <line x1="140" y1="480" x2="1140" y2="480"/>
    <line x1="140" y1="556" x2="1140" y2="556"/>
    <line x1="390" y1="430" x2="390" y2="610"/>
    <line x1="640" y1="430" x2="640" y2="610"/>
    <line x1="890" y1="430" x2="890" y2="610"/>
  </g>
  <rect width="1280" height="720" fill="#001622" opacity="0.28"/>
  <g filter="url(#shadow)">
    <rect x="104" y="72" width="370" height="64" rx="22" fill="#ffffff" opacity="0.96"/>
    <text x="289" y="115" text-anchor="middle" font-family="DejaVu Sans Condensed, DejaVu Sans, Arial, sans-serif" font-size="33" font-weight="900" fill="#071a44">WORLD CUP 2026</text>
    <rect x="796" y="72" width="380" height="64" rx="22" fill="#0866ff"/>
    <text x="986" y="115" text-anchor="middle" font-family="DejaVu Sans Condensed, DejaVu Sans, Arial, sans-serif" font-size="32" font-weight="900" fill="#ffffff">{html.escape(badge.upper())}</text>
  </g>
  {title_svg}
  <g filter="url(#shadow)">
    <rect x="244" y="486" width="792" height="72" rx="24" fill="#ffffff" opacity="0.96"/>
    <text x="640" y="534" text-anchor="middle" font-family="DejaVu Sans Condensed, DejaVu Sans, Arial, sans-serif" font-size="38" font-weight="900" fill="#071a44">CAN THEY STILL QUALIFY?</text>
  </g>
  <text x="640" y="654" text-anchor="middle" font-family="DejaVu Sans Condensed, DejaVu Sans, Arial, sans-serif" font-size="27" font-weight="800" fill="#d9fff0">THE PITCH AGENT | BUILD WITH ABDALLAH</text>
</svg>
"""


def generate_thumbnail(out_path: str | Path, *, title: str, badge: str = "SURVIVAL LAB") -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    svg = out.with_suffix(".svg")
    svg.write_text(_svg(title, badge), encoding="utf-8")
    convert = shutil.which("convert")
    if not convert:
        raise RuntimeError("ImageMagick convert is not installed")
    subprocess.run([convert, "-background", "white", str(svg), "-quality", "92", str(out)], check=True, capture_output=True, text=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--badge", default="SURVIVAL LAB")
    args = ap.parse_args()
    print(generate_thumbnail(args.out, title=args.title, badge=args.badge))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
