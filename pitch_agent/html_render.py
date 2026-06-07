"""Headless-Chromium renderer for HTML/CSS card templates.

The branded card layout lives in ``pitch_agent/templates/list_card.html`` as a
self-contained, data-driven HTML document (it exposes ``renderPitchAgentCard``
and reads ``window.BWA_POST``). This module drives that template with Playwright
to produce a deterministic, high-resolution PNG.

The render is deterministic: a fixed 1600×1000 CSS viewport and a fixed clip
region, so identical input data always yields an identically sized image. Output
resolution is the CSS size × ``device_scale_factor`` — 3200×2000 by default, or
3840×2400 in 4K mode (``fourk=True``).
"""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "list_card.html"

# Logical card size (CSS px). device_scale_factor multiplies the output pixels.
# The design ratio is fixed at 1600×1000 (8:5); higher-resolution output is
# produced purely by raising device_scale_factor, so the layout never changes.
CARD_WIDTH = 1600
CARD_HEIGHT = 1000

# Normal output: 1600×1000 @ 2x → 3200×2000 px (crisp for social media).
DEVICE_SCALE = 2
# 4K output: 1600×1000 @ 2.4x → 3840×2400 px (covers a 3840-wide 4K canvas).
FOURK_SCALE = 2.4


class RendererError(RuntimeError):
    """Raised when the HTML→PNG render cannot complete."""


def logo_data_uri(logo_path: str | Path) -> str | None:
    """Return a base64 ``data:`` URI for *logo_path*, or ``None`` if unusable.

    Embedding the logo as a data URI keeps the render self-contained (no file://
    fetches at screenshot time) and never crashes on a missing/unreadable file.
    """
    if not logo_path:
        return None
    path = Path(logo_path)
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def html_to_png(
    data: dict[str, Any],
    output_path: str | Path,
    *,
    template_path: str | Path = TEMPLATE_PATH,
    width: int = CARD_WIDTH,
    height: int = CARD_HEIGHT,
    scale: float | None = None,
    fourk: bool = False,
) -> str:
    """Render *data* through the card template and save a PNG to *output_path*.

    *data* is the template's card schema (``title``, ``subtitle``, ``brand``,
    ``rows`` with ``values``). Returns the resolved output path as a string.

    Output is always a PNG (lossless) — the right format for crisp social-media
    cards. The pixel resolution is the CSS size × ``scale``; pass ``fourk=True``
    for a 3840-wide 4K export. An explicit ``scale`` overrides both defaults.

    Raises :class:`RendererError` with an actionable message when Playwright or
    its Chromium browser is not available.
    """
    if scale is None:
        scale = FOURK_SCALE if fourk else DEVICE_SCALE
    template = Path(template_path).resolve()
    if not template.is_file():
        raise RendererError(f"Card template not found: {template}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RendererError(
            "Playwright is not installed. Install it with:\n"
            "    python -m pip install playwright\n"
            "    python -m playwright install chromium"
        ) from exc

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(args=["--no-sandbox"])
            except Exception as exc:  # noqa: BLE001 - surface a clear install hint
                raise RendererError(
                    "Could not launch headless Chromium. Install the browser with:\n"
                    "    python -m playwright install chromium\n"
                    f"(underlying error: {exc})"
                ) from exc

            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            page.goto(template.as_uri())
            # Render with the caller's data merged over the template defaults.
            page.evaluate(
                "d => window.renderPitchAgentCard("
                "Object.assign({}, window.BWA_POST || {}, d))",
                data,
            )
            page.wait_for_function("document.body.dataset.rendered === 'true'")
            page.screenshot(
                path=str(out),
                clip={"x": 0, "y": 0, "width": width, "height": height},
            )
            browser.close()
    except RendererError:
        raise
    except Exception as exc:  # noqa: BLE001 - wrap any Playwright runtime failure
        raise RendererError(f"HTML→PNG render failed: {exc}") from exc

    return str(out)


__all__ = ["html_to_png", "logo_data_uri", "RendererError", "TEMPLATE_PATH"]
