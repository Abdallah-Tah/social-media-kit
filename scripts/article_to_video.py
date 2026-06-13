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
        '  "narration": ["<6-8 spoken lines, hook first, max ~16 words each>"],\n'
        '  "cards": [\n'
        '    {"heading": "<short>", "bullets": ["<<=7 words>", "<<=7 words>", "<<=7 words>"]},\n'
        '    {"heading": "<short>", "bullets": ["<<=7 words>", "<<=7 words>"]}\n'
        "  ],\n"
        '  "take_title": "<2-4 words, e.g. MY TAKE / THE CATCH / WORTH IT?>",\n'
        '  "take": "<the article author\'s OWN strongest opinion, gotcha, or '
        'hard-won lesson — EXTRACTED from the article body, not invented. '
        'The real \'here\'s what actually matters / here\'s the catch\' point. '
        '1 sentence, the author\'s voice>",\n'
        '  "cta_line": "<spoken CTA ending with a question to spark comments>",\n'
        '  "hashtags": ["<6-9 tags incl #BuildWithAbdallah, each starts with #>"]\n'
        "}\n"
        "narration order: line 0 = hook; middle lines = the how; "
        "second-to-last line = speak the `take`; last line = the cta_line.\n"
        "The `take` MUST come from the article's actual content — if the "
        "author warns about something or states an opinion, use THAT.\n\n"
        f"TITLE: {title}\nEXCERPT: {excerpt}\nARTICLE (start): {(body or '')[:2200]}"
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
            "take_title": (obj.get("take_title") or "MY TAKE").strip(),
            "take": (obj.get("take") or "").strip(),
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
        "take_title": "MY TAKE",
        "take": (excerpt[:140] or "Worth it if you ship — skip the hype, read the docs, test it yourself."),
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


# ── Real code on screen (what actually attracts developers) ──────────────
import html as _html  # noqa: E402

_C_LIKE = {"cpp", "c", "c++", "js", "javascript", "ts", "typescript", "java",
           "go", "golang", "php", "rust", "cs", "csharp", "swift", "kotlin", "dart"}
_KEYWORDS = set((
    "auto break case char class const continue default delete do double else "
    "enum extern float for friend goto if inline int long namespace new operator "
    "private protected public return short signed sizeof static struct switch "
    "template this throw try typedef typename union unsigned using virtual void "
    "volatile while bool true false nullptr "
    "function var let def import from export async await yield lambda pass with "
    "as in is not and or echo print None True False null undefined new "
    "func package interface map range chan go defer fn impl let mut pub use"
).split())
_EXT = {"cpp": "main.cpp", "c": "main.c", "js": "app.js", "javascript": "app.js",
        "ts": "app.ts", "typescript": "app.ts", "python": "main.py", "py": "main.py",
        "php": "index.php", "go": "main.go", "rust": "main.rs", "java": "Main.java",
        "bash": "terminal", "sh": "terminal", "json": "config.json", "yaml": "config.yml"}


def _highlight_line(line, lang):
    """Return one syntax-highlighted, HTML-escaped code line."""
    lang = (lang or "").lower()
    clike = lang in _C_LIKE or lang == ""
    holds = []

    def stash(cls, text):
        holds.append((cls, text))
        return chr(0xE000 + len(holds) - 1)  # private-use placeholder

    s = line
    if clike:
        s = re.sub(r"^(\s*)(#\s*\w+)", lambda m: m.group(1) + stash("tk-pp", m.group(2)), s)
        s = re.sub(r"//.*$", lambda m: stash("tk-com", m.group(0)), s)
        s = re.sub(r"/\*.*?\*/", lambda m: stash("tk-com", m.group(0)), s)
    else:
        s = re.sub(r"#.*$", lambda m: stash("tk-com", m.group(0)), s)
    s = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: stash("tk-str", m.group(0)), s)
    s = re.sub(r"'(?:[^'\\]|\\.)*'", lambda m: stash("tk-str", m.group(0)), s)
    s = _html.escape(s)
    s = re.sub(r"[A-Za-z_]\w*",
               lambda m: (f'<span class="tk-kw">{m.group(0)}</span>'
                          if m.group(0) in _KEYWORDS else m.group(0)), s)
    s = re.sub(r"\b\d+\.?\d*\b",
               lambda m: f'<span class="tk-num">{m.group(0)}</span>', s)
    # Restore stashed strings/comments. Placeholders are private-use code
    # points so the keyword/number passes above never touch them.
    s = re.sub("[\ue000-\uf8ff]",
               lambda m: f'<span class="{holds[ord(m.group(0)) - 0xE000][0]}">'
                         f'{_html.escape(holds[ord(m.group(0)) - 0xE000][1])}</span>', s)
    return s or "&nbsp;"


def _extract_code(body):
    """Pick the most illustrative fenced code block. Returns (lang, file, lines) or None."""
    blocks = re.findall(r"```(\w*)\n(.*?)```", body or "", re.S)
    best = None
    for lang, code in blocks:
        if not lang:  # skip language-less blocks (ascii diagrams, output)
            continue
        lines = code.rstrip("\n").split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if len(lines) < 3:
            continue
        score = -abs(9 - len(lines))  # prefer ~9 lines
        if best is None or score > best[0]:
            best = (score, lang, lines[:12])
    if not best:
        return None
    _, lang, lines = best
    fn = _EXT.get(lang.lower(), f"snippet.{lang.lower()}")
    if lang.lower() == "cpp" and any("#ifndef" in l or "Q_OBJECT" in l for l in lines):
        fn = "mainwindow.h"
    return lang, fn, lines


def _editor_html(lang, filename, lines):
    """Build the dark code-editor window with line numbers + staggered reveal."""
    rows = []
    for i, ln in enumerate(lines):
        delay = 0.45 + i * 0.13
        rows.append(
            f'<div class="line" style="animation-delay:{delay:.2f}s">'
            f'<span class="ln">{i + 1}</span>{_highlight_line(ln, lang)}</div>')
    return (
        '<div class="editor"><div class="bar">'
        '<span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>'
        f'<span class="file">{_html.escape(filename)}</span></div>'
        f'<div class="code">{"".join(rows)}</div></div>')


def build_spec(slug, title, script, code=None):
    """Map the LLM script onto a video-factory episode spec (single voice).

    Narration roles (set by the prompt): line 0 = hook, line 1 = the code
    (if any), middle lines = the how, line n-2 = the "my take" editorial,
    line n-1 = the CTA. Scenes partition [0, n-1] CONTIGUOUSLY — the engine
    clips audio to video length, so every line must be covered once.

    ``code`` is (lang, filename, lines) from _extract_code, or None.
    """
    narration = script["narration"]
    n = len(narration)
    cards = script.get("cards", [])
    c0 = cards[0] if len(cards) > 0 else {"heading": "Key points", "bullets": []}
    c1 = cards[1] if len(cards) > 1 else {"heading": "Why it matters", "bullets": []}

    scenes = [
        {"segments": [0, 0], "title": script["hook_title"],
         "caption": script.get("hook_caption", ""), "rows": "",
         "stat": "⌁ Build With Abdallah · practical dev content"},
    ]

    how_lo = 1
    # Real code on screen — line 1 narrates it. Only when there's room for
    # hook+code+take+cta (n>=4) so coverage stays valid.
    if code and n >= 4:
        lang, fn, lines = code
        scenes.append({"segments": [1, 1], "title": "The Code",
                       "caption": script.get("code_caption", "The part that matters"),
                       "rows": _editor_html(lang, fn, lines), "stat": ""})
        how_lo = 2

    # Content card(s) cover the remaining "how" lines [how_lo .. n-3].
    how_hi = n - 3
    if how_hi >= how_lo:
        span = how_hi - how_lo + 1
        if span >= 2 and not code:
            mid = how_lo + span // 2 - 1
            scenes.append({"segments": [how_lo, mid],
                           "title": _esc(c0.get("heading", "Key points")), "caption": "",
                           "rows": _bullets_html(c0.get("bullets", [])), "stat": ""})
            scenes.append({"segments": [mid + 1, how_hi],
                           "title": _esc(c1.get("heading", "Why it matters")), "caption": "",
                           "rows": _bullets_html(c1.get("bullets", [])), "stat": ""})
        else:
            scenes.append({"segments": [how_lo, how_hi],
                           "title": _esc(c0.get("heading", "Key points")), "caption": "",
                           "rows": _bullets_html(c0.get("bullets", [])), "stat": ""})

    # "My take" — the author's real editorial pulled from the article. This
    # is the faceless human-intention signal that keeps the channel out of
    # the "inauthentic content" bucket.
    take = script.get("take", "").strip()
    if take and n >= 3:
        scenes.append({"segments": [n - 2, n - 2],
                       "title": _esc(script.get("take_title", "MY TAKE")),
                       "caption": _esc(take), "rows": "",
                       "stat": "— the honest version"})
    elif n >= 3:
        # No take returned — fold that line into the last content card range
        # so coverage stays contiguous: extend CTA back to n-2.
        pass

    # CTA — drives to a destination we OWN (email/site), not just a follow.
    cta_lo = n - 1 if (take and n >= 3) else max(1, n - 2)
    scenes.append({"segments": [cta_lo, n - 1], "title": "YOUR TURN",
                   "caption": _esc(script["cta_line"]), "rows": "",
                   "stat": "▶ Full code + guide → " +
                           os.environ.get("NEWSLETTER_URL", "buildwithabdallah.com")})
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

    body = post.get("body") or ""
    script = write_episode_script(title, post.get("excerpt") or "", body)
    code = _extract_code(body)
    print(f"  narration: {len(script['narration'])} lines · hook: {script['hook_title']}"
          + (f" · code: {code[1]} ({len(code[2])} lines)" if code else " · no code block"))

    spec = build_spec(slug, title, script, code=code)
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
