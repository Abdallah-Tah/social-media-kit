"""HTML → PNG card rendering for Pitch Agent.

Uses the same light-theme brand templates + Playwright render pipeline
as the matchday preview cards, producing visually consistent social cards
without matplotlib.
"""
from __future__ import annotations

import html
import subprocess
from pathlib import Path

# Resolve paths relative to the social-media-kit root
_SMKIT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _SMKIT_ROOT / "templates" / "shorts"
_SCRIPTS_DIR = _SMKIT_ROOT / "scripts"

# Logo base64 URI — reuse the same logo as worldcup_short.py
_LOGO_URI_PATH = _SMKIT_ROOT / "content" / "assets" / "logo_base64.txt"


def _load_logo_img() -> str:
    """Load the base64 logo URI from the worldcup_short module."""
    try:
        import sys
        sys.path.insert(0, str(_SMKIT_ROOT / "scripts"))
        from worldcup_short import _LOGO_URI
        if _LOGO_URI:
            return f'<img class="logo-mark" src="{_LOGO_URI}">'
    except Exception:
        pass
    return '<div class="logo-fallback">BWA</div>'


def _meta_html(subtitle: str) -> str:
    """Build the subtitle meta HTML with dot separators."""
    parts = [p.strip() for p in subtitle.split("·") if p.strip()]
    if not parts:
        return subtitle
    inner = '<span class="mdot"></span>'.join(f"<span>{html.escape(p)}</span>" for p in parts)
    return inner


def _render_html_to_png(html_src: str, output_path: str | Path, width: int = 1200, height: int = 628) -> Path:
    """Render HTML to PNG via Playwright (render_card.mjs)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write intermediate HTML
    html_path = output_path.with_suffix(".html")
    html_path.write_text(html_src)

    r = subprocess.run(
        ["node", str(_SCRIPTS_DIR / "render_card.mjs"), str(html_path), str(output_path),
         str(width), str(height)],
        capture_output=True, text=True, timeout=90,
    )
    if r.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"HTML card render failed: {r.stderr[-300:]}")
    return output_path


def render_match_recap_html_card(
    matches: list[dict],
    output_path: str | Path | None = None,
    model_record: str = "",
    title: str = "Match Recap",
    subtitle: str = "",
) -> Path:
    """Render a match recap card as HTML → PNG using the light brand template.

    Each match dict has: label, context, prediction (str or None),
    key_factor (str), no_pred (bool).
    """
    import datetime as dt

    if output_path is None:
        output_path = str(_SMKIT_ROOT / "artifacts" / "pitch_agent" / "charts" / "match_recap.png")

    if not subtitle:
        day = dt.date.today()
        subtitle = f"{day.strftime('%B %d, %Y')} · post-match results & model accountability"

    # Load template
    template_name = "match_recap_wide.html"
    html_src = (_TEMPLATES_DIR / template_name).read_text()

    # Build content HTML
    rows_html = []
    for m in matches:
        # Main score row
        ctx = html.escape(m.get("context", ""))
        ctx_html = f'<span class="meta2">{ctx}</span>' if ctx else ''
        rows_html.append(
            f'<div class="row"><span class="dot"></span>'
            f'<span class="label">{html.escape(m["label"])}</span>'
            f'{ctx_html}</div>'
        )
        # Prediction or no-prediction sub-row
        if m.get("prediction"):
            pred_html = html.escape(m["prediction"])
            # ✓ → green, ✗ → red (post-escaping so entities stay)
            pred_html = pred_html.replace("\u2713", '<span class="correct">\u2713</span>')
            pred_html = pred_html.replace("\u2717", '<span class="wrong">\u2717</span>')
            kf = m.get("key_factor", "")
            kf_html = f'<div class="key-factor">{html.escape(kf)}</div>' if kf else ''
            rows_html.append(
                f'<div class="pred-row"><div class="pred-text">{pred_html}</div>{kf_html}</div>'
            )
        elif m.get("no_pred"):
            rows_html.append(
                '<div class="no-pred-row"><span class="no-pred-text">'
                '(No prediction on record)</span></div>'
            )

    # Model record bar
    is_no_data = '0 journaled' in (model_record or '') or not model_record
    rec_cls = 'record-bar no-data' if is_no_data else 'record-bar'
    rows_html.append(f'<div class="{rec_cls}">{html.escape(model_record)}</div>')

    content_html = f'<div class="rows">{chr(10).join(rows_html)}</div>'

    # Replace template placeholders
    html_src = (html_src.replace("{{title}}", html.escape(title))
                        .replace("{{subtitle_meta}}", _meta_html(subtitle))
                        .replace("{{content}}", content_html)
                        .replace("{{logo}}", _load_logo_img()))

    return _render_html_to_png(html_src, output_path)


def render_matchday_preview_html_card(
    fixtures: list[dict],
    output_path: str | Path | None = None,
    title: str = "Matchday Preview",
    subtitle: str = "",
) -> Path:
    """Render an upcoming-fixtures card as HTML → PNG (same brand template
    as the match recap card — replaces the old matplotlib fixtures chart).

    Each fixture dict has: label, context (short date/group), and
    prediction (one-line Poisson string or None).
    """
    import datetime as dt

    if output_path is None:
        output_path = str(_SMKIT_ROOT / "artifacts" / "pitch_agent" / "charts" / "fixtures.png")

    if not subtitle:
        day = dt.date.today()
        subtitle = f"{day.strftime('%B %d, %Y')} · upcoming matches & model predictions"

    html_src = (_TEMPLATES_DIR / "match_recap_wide.html").read_text()
    # Compact rows: four fixtures + prediction sub-rows need tighter spacing
    # than the recap layout to clear the footer.
    html_src = html_src.replace(
        "</head>",
        "<style>"
        ".row { padding: 10px 4px; } .row .label { font-size: 24px; }"
        ".pred-row { padding: 3px 4px 5px 34px; }"
        ".pred-row .pred-text { font-size: 16px; }"
        "</style></head>",
    )

    rows_html = []
    for fx in fixtures:
        ctx = html.escape(fx.get("context", ""))
        ctx_html = f'<span class="meta2">{ctx}</span>' if ctx else ''
        rows_html.append(
            f'<div class="row"><span class="dot"></span>'
            f'<span class="label">{html.escape(fx["label"])}</span>'
            f'{ctx_html}</div>'
        )
        prediction = fx.get("prediction")
        if prediction:
            rows_html.append(
                f'<div class="pred-row"><div class="pred-text">'
                f'{html.escape(prediction)}</div></div>'
            )

    content_html = f'<div class="rows">{chr(10).join(rows_html)}</div>'
    html_src = (html_src.replace("{{title}}", html.escape(title))
                        .replace("{{subtitle_meta}}", _meta_html(subtitle))
                        .replace("{{content}}", content_html)
                        .replace("{{logo}}", _load_logo_img()))

    return _render_html_to_png(html_src, output_path)