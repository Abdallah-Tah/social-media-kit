#!/usr/bin/env python3
"""Turn a published tutorial/news article into an ANIMATED single-voice video.

Same engine and white brand look as the World Cup videos (video-factory),
but ONE narrator (Jarnathan) instead of the two-voice dialogue:
  * ElevenLabs single voice with word-level timestamps (edge-tts fallback)
  * word-by-word karaoke captions
  * animated white-brand scenes (light_brand theme — matches the cards)

Replaces the old still-cover reel for tutorial/news content.

  /usr/bin/python3 scripts/article_to_video.py --latest [--publish]
  /usr/bin/python3 scripts/article_to_video.py --slug <slug> [--publish]
"""
import argparse
import json
import os
import re
import sys

import requests

KIT = os.path.expanduser("~/social-media-kit")
sys.path.insert(0, KIT)
sys.path.insert(0, os.path.join(KIT, "scripts"))
from agent.config import load_env  # noqa: E402
load_env()

# The shared video engine lives in the video-factory repo.
VIDEO_FACTORY = os.path.expanduser("~/video-factory")
sys.path.insert(0, VIDEO_FACTORY)
from engine.builder import build_episode  # noqa: E402

import reel_from_article as RFA  # reuse article fetch  # noqa: E402

NARRATOR = os.environ.get("ELEVENLABS_VOICE_HOST", "c6SfcYrb2t09NHXiT80T")  # Jarnathan


def write_episode_script(title, excerpt, body):
    """LLM → single-voice episode content. Falls back to a template.

    Returns dict: {hook, narration[5-7 lines], cards[2], cta, hashtags}.
    """
    prompt = (
        "You script a 45-60 second vertical video for the developer brand "
        "Build With Abdallah. ONE narrator, conversational and plain — sound "
        "like an experienced developer talking to peers. NO hype words "
        "(no 'unlock', 'dive into', 'supercharge', 'seamless', 'game-changer', "
        "'revolutionize'). For a tutorial: teach the ONE concrete thing. For "
        "news: what changed, why it matters, what to do next.\n\n"
        "Return STRICT JSON:\n"
        "{\n"
        '  "hook_title": "<3-5 word punchy on-screen title, UPPERCASE ok>",\n'
        '  "hook_caption": "<one line under the title>",\n'
        '  "narration": ["<5-7 spoken lines, hook first, max ~16 words each>"],\n'
        '  "cards": [\n'
        '    {"heading": "<short>", "bullets": ["<<=7 words>", "<<=7 words>", "<<=7 words>"]},\n'
        '    {"heading": "<short>", "bullets": ["<<=7 words>", "<<=7 words>"]}\n'
        "  ],\n"
        '  "cta_line": "<spoken CTA ending with a question to spark comments>",\n'
        '  "hashtags": ["<6-9 tags incl #BuildWithAbdallah, each starts with #>"]\n'
        "}\n"
        "The last narration line must BE the cta_line.\n\n"
        f"TITLE: {title}\nEXCERPT: {excerpt}\nARTICLE (start): {(body or '')[:1800]}"
    )

    def _parse(txt):
        s = txt[txt.find("{"): txt.rfind("}") + 1]
        obj = json.loads(s)
        narration = [n.strip() for n in obj.get("narration", []) if n.strip()]
        cards = obj.get("cards", [])
        if not narration or not obj.get("hook_title"):
            return None
        tags = [("#" + h.lstrip("#").strip()) for h in obj.get("hashtags", []) if h.strip()][:9]
        if not any(t.lower() == "#buildwithabdallah" for t in tags):
            tags.append("#BuildWithAbdallah")
        return {
            "hook_title": obj["hook_title"].strip(),
            "hook_caption": (obj.get("hook_caption") or "").strip(),
            "narration": narration,
            "cards": cards,
            "cta_line": (obj.get("cta_line") or narration[-1]).strip(),
            "hashtags": tags,
        }

    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": os.environ.get("REEL_LLM_MODEL", "gpt-4o-mini"),
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.6,
                      "response_format": {"type": "json_object"}},
                timeout=60)
            if r.ok:
                out = _parse(r.json()["choices"][0]["message"]["content"])
                if out:
                    return out
        except Exception as e:
            print(f"⚠️ OpenAI script failed ({e}); using template.", file=sys.stderr)

    # Template fallback
    return {
        "hook_title": title[:32].upper(),
        "hook_caption": excerpt[:80] or "A practical walkthrough.",
        "narration": [
            f"Here's the short version of {title}.",
            excerpt[:120] or "One concrete, production-ready technique.",
            "I'll show you exactly what to do and why it matters.",
            "Full code and sources are in the write-up.",
            "What would you build with this? Tell me in the comments.",
        ],
        "cards": [
            {"heading": "What you get", "bullets": ["Real, working code", "No placeholders", "Production-ready"]},
            {"heading": "Why it matters", "bullets": ["Saves real time", "Fewer bugs"]},
        ],
        "cta_line": "What would you build with this? Tell me in the comments.",
        "hashtags": ["#Programming", "#WebDevelopment", "#BuildWithAbdallah"],
    }


def _bullets_html(bullets):
    rows = []
    for b in bullets:
        rows.append(
            '<div class="arow"><div class="head">'
            f'<span class="match">{_esc(b)}</span></div></div>'
        )
    return "".join(rows)


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_spec(slug, title, script):
    """Map the LLM script onto a video-factory episode spec (single voice)."""
    narration = script["narration"]
    n = len(narration)
    # Scene 1 = hook (line 0). Two content cards split the middle lines.
    # Last scene = CTA (final line).
    mid = narration[1:-1] or narration[1:]
    half = max(1, len(mid) // 2)
    s1_end = 0
    s2_range = (1, half)
    s3_range = (half + 1, n - 2) if n - 2 >= half + 1 else (half + 1, half + 1)
    cards = script.get("cards", [])
    c0 = cards[0] if len(cards) > 0 else {"heading": "Key points", "bullets": []}
    c1 = cards[1] if len(cards) > 1 else {"heading": "Why it matters", "bullets": []}

    scenes = [
        {"segments": [0, s1_end], "title": script["hook_title"],
         "caption": script.get("hook_caption", ""), "rows": "",
         "stat": "⌁ Build With Abdallah · practical dev content"},
        {"segments": list(s2_range), "title": _esc(c0.get("heading", "Key points")),
         "caption": "", "rows": _bullets_html(c0.get("bullets", [])),
         "stat": ""},
        {"segments": list(s3_range), "title": _esc(c1.get("heading", "Why it matters")),
         "caption": "", "rows": _bullets_html(c1.get("bullets", [])),
         "stat": ""},
        {"segments": [n - 1, n - 1], "title": "YOUR TURN",
         "caption": _esc(script["cta_line"]), "rows": "",
         # Audience→revenue: drive to a destination we OWN (email/site),
         # not just a platform follow. NEWSLETTER_URL overrides.
         "stat": "▶ Full code + guide → " +
                 os.environ.get("NEWSLETTER_URL", "buildwithabdallah.com")},
    ]
    return {
        "slug": f"article-{slug[:40]}",
        "title": title,
        "theme": "light_brand",
        "voices": {"host": NARRATOR},
        # Single voice: every line is the narrator.
        "dialogue": [["host", line] for line in narration],
        "scenes": scenes,
    }


# Per-slug video log — prevents re-posting the same article's video on
# every cron run (the "replicable at scale" pattern YouTube demonetizes).
_VIDEO_LOG = os.path.join(KIT, "content", "video_posts.json")


def _already_posted(slug: str) -> bool:
    try:
        with open(_VIDEO_LOG) as f:
            return slug in json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def _mark_posted(slug: str) -> None:
    try:
        with open(_VIDEO_LOG) as f:
            seen = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        seen = []
    if slug not in seen:
        seen.append(slug)
        with open(_VIDEO_LOG, "w") as f:
            json.dump(seen[-200:], f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--publish", action="store_true", help="PUBLISH publicly (default: build only)")
    ap.add_argument("--youtube", action="store_true", help="Also upload to YouTube")
    ap.add_argument("--force", action="store_true", help="Rebuild even if this article already has a video")
    args = ap.parse_args()

    post = RFA.fetch_article(slug=args.slug, latest=args.latest)
    if not post:
        print("❌ article not found", file=sys.stderr)
        return 1
    title, slug = post["title"], post["slug"]
    url = f"{RFA.SITE}/tutorials/{slug}"
    print(f"→ {title}\n  {url}")

    # Dedup: one video per article. Cron runs 3x/weekday — without this it
    # would re-post the same templated video repeatedly (demonetization risk).
    if args.publish and not args.force and _already_posted(slug):
        print(f"⏭  Already posted a video for '{slug}' — skipping (use --force to override).")
        return 0

    script = write_episode_script(title, post.get("excerpt") or "", post.get("body") or "")
    print(f"  narration: {len(script['narration'])} lines · hook: {script['hook_title']}")

    spec = build_spec(slug, title, script)
    video = build_episode(spec)
    print(f"✅ video: {video}")

    if not args.publish:
        print("Built only (use --publish to post the FB Reel, --youtube for YouTube).")
        return 0

    # Publish FB Reel — caption is the social-copy paragraph (hook differs
    # from the YouTube title below so the cross-post isn't byte-for-byte
    # identical metadata).
    import social_copy
    import fb_reels_publisher as FB
    caption_text = social_copy.make_social_copy(title, post.get("body") or "", url)
    caption_text += "\n\n" + " ".join(script["hashtags"])
    res = FB.publish_reel(str(video), description=caption_text, state="PUBLISHED", poll=False)
    print(f"FB reel: {res}")

    if args.youtube:
        import youtube_shorts_publisher as YT
        # Distinct YT hook from the FB caption — uses the script's punchy
        # hook title, not the raw article title, so the platforms diverge.
        yt_title = (f"{script['hook_title'].title()} — {title}")[:90] + " #Shorts"
        yt_desc = (f"{script['hook_caption']}\n\n{title}\n{url}\n\n"
                   + " ".join(script["hashtags"]) + " #Shorts")
        sys.argv = ["yt", "upload", "--video", str(video), "--title", yt_title,
                    "--description", yt_desc, "--privacy", "public",
                    "--tags", "BuildWithAbdallah,Programming,Tutorial,Shorts",
                    "--category-id", "28"]
        YT.main()

    _mark_posted(slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
