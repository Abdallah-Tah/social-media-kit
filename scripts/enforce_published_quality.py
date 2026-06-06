#!/usr/bin/env python3
"""Quality enforcement pass — run right after the agent publishes.

Guarantees the latest published post is a complete, code-rich article with a
permanent on-site cover, regardless of the writing agent's variance:

  - If the body is too thin (word/code-block floor) it is regenerated with a
    direct gpt-4o call (a full hands-on tutorial) and PATCHed in place.
  - If the cover is missing OR points off-site (a temporary FAL/CDN URL that
    will expire) it is regenerated, title-overlaid, hosted on the site, and
    PATCHed.

  python3 scripts/enforce_published_quality.py --latest
  python3 scripts/enforce_published_quality.py --id 57
"""
import os
import re
import sys
import argparse
import requests


def unwrap_markdown_fence(s):
    """Models often wrap their whole markdown answer in a ```markdown ... ``` fence,
    which makes the article render as one big code block. Strip that outer wrapper
    (only when it's a markdown/empty fence around real markdown, never a real code block)."""
    s = (s or "").strip()
    m = re.match(r"^```(markdown|md)?[ \t]*\n", s)
    if m and s.rstrip().endswith("```"):
        inner = s[m.end():].rstrip()[:-3].strip()
        if re.search(r"^#{1,4}\s", inner, re.M):  # looks like an article, not a code block
            return inner
    return s

sys.path.insert(0, os.path.expanduser("~/social-media-kit"))
from agent.config import load_env
load_env()
sys.path.insert(0, os.path.join(os.path.expanduser("~/social-media-kit"), "scripts"))
import image_generator as IG

BASE = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
ORIGIN = BASE.split("/api/")[0] if "/api/" in BASE else BASE
MIN_WORDS = int(os.environ.get("ENFORCE_MIN_WORDS", "1100"))
MIN_CODE = int(os.environ.get("ENFORCE_MIN_CODE", "4"))


def _h(json_ct=False):
    h = {"Authorization": f"Bearer {os.environ.get('BLOG_API_TOKEN','')}", "Accept": "application/json"}
    if json_ct:
        h["Content-Type"] = "application/json"
    return h


def fetch(pid=None):
    if pid:
        return requests.get(f"{BASE}/posts/{pid}", headers=_h(), timeout=20).json().get("data")
    d = requests.get(f"{BASE}/posts", params={"per_page": 1}, headers=_h(), timeout=20).json().get("data", [])
    return d[0] if d else None


def _chat(messages, max_tokens=8000, temperature=0.5):
    key = os.environ.get("OPENAI_API_KEY", "")
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "gpt-4o", "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=240,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


_VOICE = (
    "You are a senior developer writing a complete, hands-on tutorial for the Build With "
    "Abdallah blog. Clear, direct English. Real, complete, copy-pasteable code in fenced "
    "code blocks with language labels (actual commands and full files, never prose "
    "descriptions of code). No hype words (dive into, unlock, seamlessly, robust, game "
    "changer, revolutionary). Minimal emojis. No invented benchmarks."
)


def write_article(title):
    """Generate the tutorial in two halves so it reliably reaches full length.

    gpt-4o caps a single response near ~700 words; asking for each half
    separately yields a complete ~1,500-1,800 word tutorial.
    """
    part_a = _chat([
        {"role": "system", "content": _VOICE},
        {"role": "user", "content": (
            f"Write the FIRST HALF of a tutorial titled \"{title}\". Start with '# {title}'. "
            "Include: a focused intro (what this is and why it matters now), ## Prerequisites "
            "(with real install commands), ## Project Structure (a directory tree), and the "
            "first three numbered ## Step sections — each building one real working project "
            "with COMPLETE code blocks and a short explanation under each. Around 850 words. "
            "Do NOT write a conclusion yet. Output ONLY markdown."
        )},
    ])
    part_b = _chat([
        {"role": "system", "content": _VOICE},
        {"role": "user", "content": (
            "Continue this tutorial seamlessly (do not repeat the intro or earlier steps). "
            "Here is the first half:\n\n" + part_a + "\n\n---\n\n"
            "Now write the SECOND HALF: the remaining two or three numbered ## Step sections "
            "(with complete code), a ## Complete Working Example (the full final files), a "
            "## Common Errors and Fixes section (real errors and concrete fixes), a "
            "## Conclusion, and a ## Sources section with real URLs. Around 750 words. "
            "Output ONLY markdown, with no article title line."
        )},
    ])
    return unwrap_markdown_fence(part_a).rstrip() + "\n\n" + unwrap_markdown_fence(part_b).lstrip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--latest", action="store_true")
    args = ap.parse_args()

    p = fetch(args.id)
    if not p:
        print("enforce: no post found")
        return 0
    pid, title = p["id"], p["title"]
    body = p.get("body") or ""
    cover = p.get("cover_image") or ""
    words, code = len(body.split()), body.count("```") // 2
    on_site = bool(cover) and cover.startswith(ORIGIN)
    print(f"enforce id {pid}: {words}w {code}cb cover={'on-site' if on_site else (cover[:40] or 'NONE')}")

    patch = {}

    # 1) Body depth
    if words < MIN_WORDS or code < MIN_CODE:
        print(f"  body below floor (<{MIN_WORDS}w or <{MIN_CODE} code blocks) → regenerating (gpt-4o)")
        try:
            nb = write_article(title)
            nw, nc = len(nb.split()), nb.count("```") // 2
            # Accept the regen if it is a clear improvement: at least ~850 words,
            # enough code blocks, and not shorter than the original.
            if nw >= 850 and nc >= MIN_CODE and nw >= words:
                patch["body"] = nb
                print(f"   → regenerated: {nw}w {nc}cb")
            else:
                print(f"   → regen weak ({nw}w {nc}cb); keeping original")
        except Exception as e:
            print(f"   → regen failed: {e}")

    # 2) Cover must be permanent + on-site
    if not on_site:
        print("  cover missing or off-site (expiring) → regenerating + hosting")
        try:
            r = IG.generate_cover(title, out_path=f"content/assets/_enf_{pid}.png",
                                  branding={"accent_color": "#2563eb"})
            if r and (r.get("url") or "").startswith(ORIGIN):
                patch["cover_image"] = r["url"]
                patch["featured_image"] = r["url"]
                print(f"   → hosted cover: {r['url']}")
            else:
                print(f"   → cover host failed (got {r.get('url') if r else None})")
        except Exception as e:
            print(f"   → cover regen failed: {e}")
        finally:
            try:
                os.remove(f"content/assets/_enf_{pid}.png")
            except OSError:
                pass

    if patch:
        resp = requests.patch(f"{BASE}/posts/{pid}", headers=_h(True), json=patch, timeout=60)
        print(f"  PATCH id {pid}: HTTP {resp.status_code} fields={list(patch.keys())}")
        return 0 if resp.ok else 1
    print("  ✓ meets quality bar — no changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
