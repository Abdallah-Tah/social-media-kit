#!/usr/bin/env python3
"""Cover image generation — provider-agnostic, with a free local fallback.

Generates a cover/hero image for an article or post. Tries, in order:

  1. Gemini      — gemini-2.5-flash-image (set GEMINI_API_KEY) — free daily quota
  2. FAL.ai      — flux-pro/v1.1-ultra (set FAL_KEY) — photoreal, high quality
  3. OpenAI      — gpt-image-1 (set OPENAI_API_KEY)
  4. Local card  — a branded Pillow card with the title (no key, always works)

Force one with IMAGE_PROVIDER=gemini|fal|openai|card. Returns the local file path
(remote images are downloaded into content/assets/) plus the source URL when
the provider hosts one.

Standalone:
    python scripts/image_generator.py "Laravel 13 AI SDK" --out cover.png
"""
import os
import sys
import base64
import argparse
from datetime import date

import requests

ASSETS_DIR = os.path.join("content", "assets")
_UA = "social-media-agent/1.0"

FAL_MODEL = os.environ.get("FAL_MODEL", "fal-ai/flux-pro/v1.1-ultra")
OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")


def _fal_key():
    return os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY", "")


def _gemini_key():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")


def _auto_provider():
    # Free Gemini quota first, then paid FAL/OpenAI, then offline card.
    if _gemini_key():
        return "gemini"
    if _fal_key():
        return "fal"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "card"


def _default_prompt(title):
    # Purely abstract background: anything resembling screens/code/UI makes the
    # model render garbled gibberish "text". Force atmosphere-only imagery.
    return (
        f"Minimal abstract editorial tech background, dark navy gradient with soft glowing "
        f"geometric shapes, faint flowing circuit-line patterns, gentle bokeh light, blue and "
        f"orange accents, lots of clean negative space, cinematic and premium. "
        f"PURELY ABSTRACT AND ATMOSPHERIC — absolutely NO screens, NO code, NO user interface, "
        f"NO panels, NO windows, NO browsers, NO dashboards, NO devices, NO phones, NO laptops, "
        f"NO keyboards, NO icons, NO logos, NO charts, NO diagrams, NO text, NO letters, NO "
        f"numbers, NO symbols, NO words, NO writing, no watermark. 16:9 composition."
    )


def _save_bytes(data, out_path):
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


def _download(url, out_path):
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=60)
    resp.raise_for_status()
    return _save_bytes(resp.content, out_path)


# ── Providers ────────────────────────────────────────────────────────────
def _generate_gemini(prompt, out_path):
    """Google Gemini image generation (free daily quota). Returns inline PNG."""
    key = _gemini_key()
    if not key:
        return None
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_IMAGE_MODEL}:generateContent"
    )
    try:
        resp = requests.post(
            url,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            },
            timeout=120,
        )
        if not resp.ok:
            print(f"❌ Gemini image error ({resp.status_code}): {resp.text[:200]}")
            return None
        parts = (
            (resp.json().get("candidates") or [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                path = _save_bytes(base64.b64decode(inline["data"]), out_path)
                print(f"✅ Cover generated via Gemini: {path}")
                return {"path": path, "url": None, "provider": "gemini"}
        print("❌ Gemini returned no image (likely quota or modality); falling back.")
        return None
    except requests.RequestException as e:
        print(f"❌ Gemini request failed: {e}")
        return None


def _generate_fal(prompt, out_path, aspect_ratio="16:9"):
    key = _fal_key()
    if not key:
        return None
    try:
        resp = requests.post(
            f"https://fal.run/{FAL_MODEL}",
            headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
            json={"prompt": prompt, "aspect_ratio": aspect_ratio, "num_images": 1},
            timeout=120,
        )
        if not resp.ok:
            print(f"❌ FAL error ({resp.status_code}): {resp.text[:200]}")
            return None
        images = resp.json().get("images", [])
        if not images:
            return None
        url = images[0].get("url")
        path = _download(url, out_path)
        print(f"✅ Cover generated via FAL.ai: {path}")
        return {"path": path, "url": url, "provider": "fal"}
    except requests.RequestException as e:
        print(f"❌ FAL request failed: {e}")
        return None


def _generate_openai(prompt, out_path, size="1536x1024"):
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return None
    try:
        resp = requests.post(
            f"{os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')}/images/generations",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": OPENAI_IMAGE_MODEL, "prompt": prompt, "size": size, "n": 1},
            timeout=120,
        )
        if not resp.ok:
            print(f"❌ OpenAI image error ({resp.status_code}): {resp.text[:200]}")
            return None
        item = (resp.json().get("data") or [{}])[0]
        if item.get("b64_json"):
            path = _save_bytes(base64.b64decode(item["b64_json"]), out_path)
            url = None
        elif item.get("url"):
            url = item["url"]
            path = _download(url, out_path)
        else:
            return None
        print(f"✅ Cover generated via OpenAI: {path}")
        return {"path": path, "url": url, "provider": "openai"}
    except requests.RequestException as e:
        print(f"❌ OpenAI image request failed: {e}")
        return None


def _generate_card(title, out_path, branding=None):
    """Free, no-key fallback: render a branded title card with Pillow."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import make_assets

    branding = branding or {}
    out_dir = os.path.dirname(out_path) or ASSETS_DIR
    path = make_assets.generate_card(
        title,
        subtitle=branding.get("subtitle", ""),
        bg_color=branding.get("bg_color", "#0f172a"),
        accent_color=branding.get("accent_color", "#2563eb"),
        output_dir=out_dir,
    )
    # make_assets writes card.png; align with requested out_path if different.
    if os.path.abspath(path) != os.path.abspath(out_path):
        try:
            os.replace(path, out_path)
            path = out_path
        except OSError:
            pass
    print(f"✅ Cover card generated locally: {path}")
    return {"path": path, "url": None, "provider": "card"}


def _add_title_overlay(image_path, title, branding=None):
    """Composite a clean, readable title + gradient scrim onto an AI image.

    AI image models can't render real text, so we never trust them for the
    title — we lay it on afterward with Pillow for a professional result.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return
    branding = branding or {}
    accent = branding.get("accent_color", "#2563eb")

    def _font(sz, bold=True):
        base = "/usr/share/fonts/truetype/dejavu/"
        p = base + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
        return ImageFont.truetype(p, sz) if os.path.exists(p) else ImageFont.load_default()

    try:
        img = Image.open(image_path).convert("RGBA")
    except Exception:
        return
    W, H = img.size

    # Bottom-up dark gradient scrim for text contrast (transparent up top).
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for y in range(H):
        t = max(0.0, (y - H * 0.40) / (H * 0.60))
        sd.line([(0, y), (W, y)], fill=(8, 16, 32, int(235 * min(1.0, t))))
    img = Image.alpha_composite(img, scrim)
    d = ImageDraw.Draw(img)

    pad = int(W * 0.06)
    max_w = W - 2 * pad
    size = int(H * 0.090)

    def wrap(text, fnt):
        words, lines, cur = text.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=fnt) <= max_w:
                cur = t
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        return lines

    f = _font(size)
    lines = wrap(title, f)
    while len(lines) > 3 and size > int(H * 0.05):
        size = int(size * 0.9); f = _font(size); lines = wrap(title, f)
    lh = int(size * 1.16)
    y = H - pad - lh * len(lines)

    # brand accent bar above the title
    d.rounded_rectangle([pad, y - int(H * 0.045), pad + int(W * 0.07), y - int(H * 0.022)],
                        radius=4, fill=accent)
    for ln in lines:
        d.text((pad + 2, y + 2), ln, font=f, fill=(0, 0, 0, 190))   # shadow
        d.text((pad, y), ln, font=f, fill=(255, 255, 255, 255))
        y += lh

    # brand tag, top-right (away from the title), with a shadow for contrast
    bf = _font(int(H * 0.032), bold=True)
    tag = "buildwithabdallah.com"
    tw = d.textlength(tag, font=bf)
    tx, ty = W - pad - tw, int(pad * 0.7)
    d.text((tx + 1, ty + 1), tag, font=bf, fill=(0, 0, 0, 170))
    d.text((tx, ty), tag, font=bf, fill=(255, 255, 255, 225))

    img.convert("RGB").save(image_path)


def _upload_to_blog(local_path):
    """Upload a local image to the blog media endpoint; return the hosted URL.

    The site references cover_image by URL, so the title-overlaid LOCAL image
    must be hosted (the raw AI-provider URL has no overlay). Graceful no-op if
    the blog API isn't configured.
    """
    base = os.environ.get("BLOG_API_URL", "").rstrip("/")
    tok = os.environ.get("SOCIAL_API_TOKEN") or os.environ.get("BLOG_API_TOKEN", "")
    if not base or not tok or not os.path.exists(local_path):
        return None
    try:
        with open(local_path, "rb") as f:
            r = requests.post(
                f"{base}/media/upload",
                headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
                files={"file": (os.path.basename(local_path), f, "image/png")},
                timeout=60,
            )
        if r.status_code in (200, 201):
            url = (r.json().get("data", {}) or {}).get("url")
            if url:
                print(f"✅ Cover uploaded to site: {url}")
                return url
    except requests.RequestException as e:
        print(f"⚠️ cover upload failed ({e}); falling back to provider URL.")
    return None


def generate_cover(title, prompt=None, out_path=None, provider=None,
                   branding=None):
    """Generate a cover image, falling back to a local card on failure."""
    provider = (provider or os.environ.get("IMAGE_PROVIDER") or _auto_provider()).lower()
    prompt = prompt or _default_prompt(title)
    if not out_path:
        slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:60].strip("-")
        out_path = os.path.join(ASSETS_DIR, f"{date.today().isoformat()}_{slug or 'cover'}.png")

    order = {
        "gemini": [_g_gemini, _g_fal, _g_openai, _g_card],
        "fal": [_g_fal, _g_gemini, _g_openai, _g_card],
        "openai": [_g_openai, _g_gemini, _g_fal, _g_card],
        "card": [_g_card],
    }.get(provider, [_g_gemini, _g_fal, _g_openai, _g_card])

    for fn in order:
        result = fn(title, prompt, out_path, branding)
        if result:
            # AI providers can't render real text → overlay a clean, readable title,
            # then host the overlaid image so the site cover uses it (not the raw URL).
            if result.get("provider") in ("fal", "gemini", "openai"):
                _add_title_overlay(result["path"], title, branding)
                hosted = _upload_to_blog(result["path"])
                if hosted:
                    result["url"] = hosted
            return result
    return None


# Thin adapters so the fallback chain can call all providers uniformly.
def _g_gemini(title, prompt, out_path, branding):
    return _generate_gemini(prompt, out_path)


def _g_fal(title, prompt, out_path, branding):
    return _generate_fal(prompt, out_path)


def _g_openai(title, prompt, out_path, branding):
    return _generate_openai(prompt, out_path)


def _g_card(title, prompt, out_path, branding):
    return _generate_card(title, out_path, branding)


def main():
    parser = argparse.ArgumentParser(description="Generate a cover image")
    parser.add_argument("title", help="Article/post title")
    parser.add_argument("--prompt", "-p", help="Override the image prompt")
    parser.add_argument("--out", "-o", help="Output PNG path")
    parser.add_argument("--provider", choices=["gemini", "fal", "openai", "card"])
    args = parser.parse_args()

    result = generate_cover(
        args.title, prompt=args.prompt, out_path=args.out, provider=args.provider
    )
    if not result:
        print("❌ Cover generation failed on all providers.")
        sys.exit(1)
    print(result)


if __name__ == "__main__":
    main()
