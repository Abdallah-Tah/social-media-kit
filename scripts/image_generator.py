#!/usr/bin/env python3
"""Cover image generation — provider-agnostic, with a free local fallback.

Generates a cover/hero image for an article or post. Tries, in order:

  1. FAL.ai      — flux-pro/v1.1-ultra (set FAL_KEY) — photoreal, high quality
  2. OpenAI      — gpt-image-1 (set OPENAI_API_KEY)
  3. Local card  — a branded Pillow card with the title (no key, always works)

Force one with IMAGE_PROVIDER=fal|openai|card. Returns the local file path
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


def _fal_key():
    return os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY", "")


def _auto_provider():
    if _fal_key():
        return "fal"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "card"


def _default_prompt(title):
    return (
        f"Professional, modern blog cover illustration for an article titled "
        f"\"{title}\". Clean, high-contrast, editorial tech aesthetic, no text, "
        f"no watermark, 16:9 composition."
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


def generate_cover(title, prompt=None, out_path=None, provider=None,
                   branding=None):
    """Generate a cover image, falling back to a local card on failure."""
    provider = (provider or os.environ.get("IMAGE_PROVIDER") or _auto_provider()).lower()
    prompt = prompt or _default_prompt(title)
    if not out_path:
        slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:60].strip("-")
        out_path = os.path.join(ASSETS_DIR, f"{date.today().isoformat()}_{slug or 'cover'}.png")

    order = {
        "fal": [_g_fal, _g_openai, _g_card],
        "openai": [_g_openai, _g_fal, _g_card],
        "card": [_g_card],
    }.get(provider, [_g_fal, _g_openai, _g_card])

    for fn in order:
        result = fn(title, prompt, out_path, branding)
        if result:
            return result
    return None


# Thin adapters so the fallback chain can call all providers uniformly.
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
    parser.add_argument("--provider", choices=["fal", "openai", "card"])
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
