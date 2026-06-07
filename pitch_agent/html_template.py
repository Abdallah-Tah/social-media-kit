"""HTML/CSS card templates for The Pitch Agent.

Pure HTML + CSS + inline SVG — no external image assets and no web fonts, so a
card renders identically offline. The whole BuildWithAbdallah brand system
(logo lockup, geometric corner shapes, dotted-grid accents, faint "A" watermark)
is recreated in CSS/SVG here. Render to PNG with :mod:`pitch_agent.html_render`.
"""
from __future__ import annotations

import html
from typing import Any

# Brand palette (mirrors chart_themes.buildwithabdallah_light).
_BG = "#F7F9FC"
_PRIMARY = "#0B1F44"
_SECONDARY = "#6B7280"
_ACCENT = "#1D6CF2"
_NAVY = "#0B2A6B"
_DIVIDER = "#E2E8F2"


def _esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


def _logo_svg() -> str:
    """The 'A' monogram mark: blue rounded square with an A + </> glyph."""
    return f"""
    <svg class="logo-mark" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="amark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#2D7BFF"/>
          <stop offset="100%" stop-color="{_NAVY}"/>
        </linearGradient>
      </defs>
      <rect x="6" y="6" width="108" height="108" rx="26" fill="url(#amark)"/>
      <path d="M60 24 L86 84 L72 84 L60 54 L48 84 L34 84 Z" fill="#FFFFFF"/>
      <text x="60" y="104" text-anchor="middle" font-family="monospace"
            font-size="20" font-weight="700" fill="#9DC2FF">&lt;/&gt;</text>
    </svg>
    """


def _dot_grid(extra_class: str) -> str:
    """A 6x4 dotted-grid decoration."""
    dots = []
    for r in range(4):
        for c in range(6):
            dots.append(
                f'<circle cx="{6 + c * 16}" cy="{6 + r * 16}" r="3.2"/>'
            )
    return (
        f'<svg class="dotgrid {extra_class}" viewBox="0 0 96 64" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(dots)}</svg>'
    )


def _row_html(row: dict[str, Any], is_last: bool) -> str:
    label = _esc(row.get("label", ""))
    col_a = _esc(row.get("col_a", "")).strip()
    col_b = _esc(row.get("col_b", "")).strip()
    border = "" if is_last else "border-bottom:1px solid " + _DIVIDER + ";"
    col_a_html = f'<div class="col-a">{col_a}</div>' if col_a else "<div></div>"
    col_b_html = f'<div class="col-b">{col_b}</div>' if col_b else "<div></div>"
    return f"""
      <div class="row" style="{border}">
        <div class="bullet">&bull;</div>
        <div class="label">{label}</div>
        {col_a_html}
        {col_b_html}
      </div>"""


def render_list_card_html(
    title: str,
    subtitle: str,
    rows: list[dict[str, Any]],
    *,
    footer_text: str = "",
    parent_brand_a: str = "Build With ",
    parent_brand_b: str = "Abdallah",
    tagline: str = "SOFTWARE • AUTOMATION • APIS • SOLUTIONS",
) -> str:
    """Return a complete standalone HTML document for a branded list card."""
    rows_html = "".join(
        _row_html(r, i == len(rows) - 1) for i, r in enumerate(rows)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:1200px; height:900px; }}
  body {{
    position:relative; overflow:hidden; background:{_BG};
    font-family:"Segoe UI", "Helvetica Neue", Arial, "Liberation Sans", sans-serif;
    color:{_PRIMARY}; -webkit-font-smoothing:antialiased;
  }}

  /* ── Decorative geometric corners ─────────────────────────────── */
  .corner {{ position:absolute; z-index:0; }}
  .corner.tr {{ top:0; right:0; }}
  .corner.bl {{ bottom:0; left:0; }}

  /* ── Dotted grids ─────────────────────────────────────────────── */
  .dotgrid {{ position:absolute; width:96px; height:64px; z-index:0;
             fill:#C7D6F5; opacity:.7; }}
  .dotgrid.tl {{ top:34px; left:34px; }}
  .dotgrid.br {{ bottom:80px; right:48px; }}

  /* ── Faint A watermark ────────────────────────────────────────── */
  .watermark {{
    position:absolute; top:48%; left:54%; transform:translate(-50%,-50%);
    font-size:620px; font-weight:800; color:{_ACCENT}; opacity:.05;
    z-index:0; line-height:1; user-select:none;
  }}

  /* ── Content ──────────────────────────────────────────────────── */
  .page {{ position:relative; z-index:2; padding:48px 60px; }}

  .header {{ display:flex; align-items:center; gap:18px; margin-bottom:8px; }}
  .logo-mark {{ width:78px; height:78px; flex:none; }}
  .brand-text {{ display:flex; flex-direction:column; justify-content:center; }}
  .brand-name {{ font-size:40px; font-weight:800; letter-spacing:-.5px;
                line-height:1; color:{_PRIMARY}; }}
  .brand-name .accent {{ color:{_ACCENT}; }}
  .tagline {{ font-size:12px; font-weight:600; letter-spacing:3px;
             color:{_SECONDARY}; margin-top:8px; }}

  .title {{ font-size:64px; font-weight:800; letter-spacing:-1.5px;
           color:{_PRIMARY}; margin-top:18px; }}
  .subtitle {{ font-size:24px; color:{_SECONDARY}; margin-top:10px; }}

  .list {{ margin-top:26px; }}
  .row {{ display:grid; grid-template-columns:36px 1fr 160px 150px;
         align-items:center; height:62px; }}
  .bullet {{ color:{_ACCENT}; font-size:30px; line-height:1; }}
  .label {{ font-size:26px; font-weight:700; color:{_PRIMARY}; }}
  .col-a {{ font-size:20px; font-weight:700; color:{_ACCENT}; text-align:left; }}
  .col-b {{ font-size:20px; color:{_SECONDARY}; text-align:right; }}

  .footer {{ position:absolute; bottom:28px; left:0; right:0; text-align:center;
            font-size:16px; font-style:italic; color:{_SECONDARY}; z-index:2; }}
</style>
</head>
<body>
  <!-- geometric corners -->
  <svg class="corner tr" width="360" height="300" viewBox="0 0 360 300"
       xmlns="http://www.w3.org/2000/svg">
    <path d="M360 0 H140 L360 240 Z" fill="{_NAVY}"/>
    <path d="M360 0 H230 L360 150 Z" fill="{_ACCENT}"/>
  </svg>
  <svg class="corner bl" width="300" height="320" viewBox="0 0 300 320"
       xmlns="http://www.w3.org/2000/svg">
    <path d="M0 320 V120 L220 320 Z" fill="{_NAVY}"/>
    <path d="M0 320 V200 L150 320 Z" fill="{_ACCENT}"/>
  </svg>

  {_dot_grid("tl")}
  {_dot_grid("br")}

  <div class="watermark">A</div>

  <div class="page">
    <div class="header">
      {_logo_svg()}
      <div class="brand-text">
        <div class="brand-name">{_esc(parent_brand_a)}<span class="accent">{_esc(parent_brand_b)}</span></div>
        <div class="tagline">{_esc(tagline)}</div>
      </div>
    </div>

    <div class="title">{_esc(title)}</div>
    <div class="subtitle">{_esc(subtitle)}</div>

    <div class="list">{rows_html}
    </div>
  </div>

  <div class="footer">{_esc(footer_text)}</div>
</body>
</html>"""
