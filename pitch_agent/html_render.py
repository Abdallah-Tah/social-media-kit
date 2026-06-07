"""Render HTML/CSS cards to PNG with Playwright (headless Chromium).

The :mod:`pitch_agent.html_template` module produces standalone HTML; this module
turns it into a crisp PNG. Chromium must be available — install once with::

    python -m playwright install chromium

If the browser binary is missing (e.g. a restricted CI/sandbox), :func:`html_to_png`
raises a clear ``RuntimeError`` explaining how to install it.
"""
from __future__ import annotations

from pathlib import Path

# Default card geometry — matches the HTML <body> size in html_template.
CARD_WIDTH = 1200
CARD_HEIGHT = 900
SCALE = 2  # device pixel ratio → 2400x1800 output for crisp text


def html_to_png(
    html_str: str,
    output_path: str,
    *,
    width: int = CARD_WIDTH,
    height: int = CARD_HEIGHT,
    scale: int = SCALE,
) -> str:
    """Render *html_str* to a PNG at *output_path*; return the resolved path."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - import-time guard
        raise RuntimeError(
            "Playwright is not installed. Run:\n"
            "    pip install playwright && python -m playwright install chromium"
        ) from exc

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            page.set_content(html_str, wait_until="networkidle")
            page.screenshot(path=str(output), clip={
                "x": 0, "y": 0, "width": width, "height": height,
            })
            browser.close()
    except Exception as exc:  # noqa: BLE001 - surface a actionable message
        msg = str(exc)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            raise RuntimeError(
                "Chromium is not installed for Playwright. Run:\n"
                "    python -m playwright install chromium"
            ) from exc
        raise

    return str(output.resolve())
