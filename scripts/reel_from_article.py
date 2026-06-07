#!/usr/bin/env python3
"""Turn a published Build With Abdallah article into a voiceover reel.

Fetches the article (title/excerpt/body/cover) from the blog API, has the LLM
write a punchy ~25s narration + 4 on-screen caption lines, builds the reel, and
uploads it to the Facebook page as a DRAFT (default) or PUBLISHED (--publish).

  python3 scripts/reel_from_article.py --slug <slug> [--publish]
  python3 scripts/reel_from_article.py --latest          # newest published post
"""
import os
import sys
import json
import argparse
import tempfile
import urllib.request
import requests
from pathlib import Path

ROOT = Path(os.environ.get("SMKIT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
from agent.config import load_env
load_env()
sys.path.insert(0, str(ROOT / "scripts"))
import reel_generator as RG
import fb_reels_publisher as FB

BASE = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
SITE = "https://buildwithabdallah.com"


def _api_headers():
    tok = os.environ.get("BLOG_API_TOKEN", "")
    return {"Authorization": f"Bearer {tok}", "Accept": "application/json"}


def fetch_article(slug=None, latest=False):
    if latest:
        r = requests.get(f"{BASE}/posts", params={"per_page": 1}, headers=_api_headers(), timeout=20)
        data = r.json().get("data", [])
        return data[0] if data else None
    r = requests.get(f"{BASE}/posts", params={"per_page": 50}, headers=_api_headers(), timeout=20)
    for p in r.json().get("data", []):
        if p.get("slug") == slug:
            return p
    return None


def write_script(title, excerpt, body):
    """LLM (free Ollama) -> {narration, captions[]}. Falls back to a template."""
    prompt = (
        "You are scripting a 25-second vertical Reel for a developer brand "
        "(Build With Abdallah). Given the article, return STRICT JSON:\n"
        '{"narration":"<55-80 words, spoken, punchy hook first, ends with '
        '\'Follow Build With Abdallah for the full guide\'>",'
        '"captions":["<4 short on-screen lines, <=6 words each>"],'
        '"hashtags":["<6-9 relevant hashtags incl #BuildWithAbdallah, each starting with #>"]}\n\n'
        f"TITLE: {title}\nEXCERPT: {excerpt}\nARTICLE (start): {(body or '')[:1200]}"
    )

    def _parse(txt):
        s = txt[txt.find("{"): txt.rfind("}") + 1]
        obj = json.loads(s)
        caps = [c.strip() for c in obj.get("captions", []) if c.strip()][:4]
        tags = [("#" + h.lstrip("#").strip()) for h in obj.get("hashtags", []) if h.strip()][:9]
        if not any(t.lower() == "#buildwithabdallah" for t in tags):
            tags.append("#BuildWithAbdallah")
        if obj.get("narration") and caps:
            return obj["narration"].strip(), caps, tags
        return None

    # 1) Fast path: OpenAI gpt-4o-mini (tiny call, a fraction of a cent)
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        try:
            r = requests.post("https://api.openai.com/v1/chat/completions",
                              headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                              json={"model": os.environ.get("REEL_LLM_MODEL", "gpt-4o-mini"),
                                    "messages": [{"role": "user", "content": prompt}],
                                    "temperature": 0.6,
                                    "response_format": {"type": "json_object"}}, timeout=45)
            if r.ok:
                out = _parse(r.json()["choices"][0]["message"]["content"])
                if out:
                    return out
        except Exception as e:
            print(f"⚠️ OpenAI script failed ({e}); trying Ollama.")
    # 2) Free fallback: local Ollama (slower)
    try:
        r = requests.post("http://localhost:11434/v1/chat/completions",
                          json={"model": "qwen3.5:cloud",
                                "messages": [{"role": "user", "content": prompt}],
                                "temperature": 0.6}, timeout=120)
        out = _parse(r.json()["choices"][0]["message"]["content"])
        if out:
            return out
    except Exception as e:
        print(f"⚠️ LLM script failed ({e}); using template.")
    # Fallback
    return (f"{title}. {excerpt} Follow Build With Abdallah for the full guide.",
            [title[:40], "Practical, production-ready", "Real code, real sources",
             "Full guide → buildwithabdallah.com"],
            ["#AI", "#Laravel", "#PHP", "#WebDevelopment", "#BuildWithAbdallah"])


def get_cover(post, work):
    url = post.get("cover_image") or ""
    if url.startswith("http"):
        out = os.path.join(work, "cover.png")
        try:
            urllib.request.urlretrieve(url, out)
            return out
        except Exception:
            pass
    # fall back to the most recent local asset
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--publish", action="store_true", help="PUBLISH publicly (default: DRAFT)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    post = fetch_article(slug=args.slug, latest=args.latest)
    if not post:
        print("❌ article not found"); sys.exit(1)
    title, slug = post["title"], post["slug"]
    url = f"{SITE}/tutorials/{slug}"
    print(f"→ {title}\n  {url}")

    work = tempfile.mkdtemp(prefix="reelart_")
    cover = get_cover(post, work)
    if not cover:
        print("❌ no cover image available for this article"); sys.exit(1)

    narration, captions, hashtags = write_script(title, post.get("excerpt") or "", post.get("body") or "")
    print(f"  narration: {narration[:90]}…\n  captions: {captions}\n  hashtags: {hashtags}")

    out = args.out or os.path.join(str(ROOT),
                                   "content/assets", f"reel_{slug[:40]}.mp4")
    reel = RG.make_reel(title, narration, captions, cover, out)
    if not reel:
        print("❌ reel build failed"); sys.exit(1)

    import social_copy
    caption = social_copy.make_social_copy(title, post.get("body") or "", url)
    state = "PUBLISHED" if args.publish else "DRAFT"
    res = FB.publish_reel(reel["path"], description=caption, state=state, poll=False)
    if not res:
        print(f"⚠️ reel built at {reel['path']} but FB upload failed"); sys.exit(1)
    print(f"✅ Reel {state}: {res.get('permalink')}  (local: {reel['path']})")
    if state == "DRAFT":
        print("   Review in Meta Business Suite → Content → Reels → Drafts, then publish.")


if __name__ == "__main__":
    main()
