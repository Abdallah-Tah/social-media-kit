#!/usr/bin/env python3
"""News Short in the SAME format + TTS as the football prediction Shorts.

Same look (the light_brand match_recap_wide card on a white canvas with a
headline + CTA + slow zoom) and the same voiceover path (ElevenLabs first),
but the card lists the story step by step and the narration explains it.

  /usr/bin/python3 scripts/news_short.py            # render + Telegram preview
  /usr/bin/python3 scripts/news_short.py --no-telegram
"""
from __future__ import annotations

import argparse
import html as _html
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "scripts"))
from agent.config import load_env  # noqa: E402

OUT_DIR = KIT / "content" / "assets" / "shorts" / "gpt6-news"
CARD = OUT_DIR / "news_card.png"
VIDEO = OUT_DIR / "gpt6_news_short.mp4"

# ── the GPT-6 story, step by step (card rows: heading -> detail) ──────────────
TITLE = "GPT-6, EXPLAINED"
SUBTITLE = "What is really going on - June 2026"
HEADLINE = "AI NEWS, EXPLAINED"
CTA = "Follow Build With Abdallah"
RECORD = "Build With Abdallah - AI news, explained simply"

STEPS = [
    ("1 - The claim", "GPT-6 is 'launching' everywhere - treat it as a rumor"),
    ("2 - The reality", "OpenAI's latest official model is still GPT-5.5"),
    ("3 - Big Tech moves", "Microsoft Polaris · Apple to Gemini · Claude leads"),
    ("4 - The real shift", "Distribution beats the best benchmark"),
    ("5 - Builder move", "Add a model-swap layer; design multi-model"),
]

VOICEOVER = (
    "Let's break down the GPT-6 story step by step. "
    "Step one, the claim: you're seeing GPT-6 is launching everywhere, but treat that as a rumor, "
    "because OpenAI has not confirmed it. "
    "Step two, the reality: OpenAI's latest official model is still GPT-5.5, which shipped as a stopgap "
    "while GPT-6 slipped. "
    "Step three, watch what Big Tech is doing: Microsoft is leaning on its own Polaris work inside Copilot, "
    "Apple reportedly picked Gemini, and Anthropic's Claude keeps trading the benchmark lead. "
    "Step four, the real shift: the winner is not whoever has the best model, it's whoever controls "
    "distribution, the device and the default that people actually touch. "
    "Step five, the builder move: don't bet your whole product on one model. Put a thin layer between your "
    "app and any provider, so swapping is a config change, not a rewrite, and design for a multi-model future. "
    "That's the whole story - a rumor on top, and a real power shift underneath."
)


def build_card() -> Path:
    """Reuse the football card's exact template (match_recap_wide.html) so the
    visual format matches the prediction Shorts; only the rows + labels change."""
    from pitch_agent import html_cards as HC

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html_src = (HC._TEMPLATES_DIR / "match_recap_wide.html").read_text()
    # tighten density so all 5 steps + details fit above the footer
    html_src = html_src.replace(
        "</head>",
        "<style>"
        ".row { padding: 7px 4px 2px; } .row .label { font-size: 23px; }"
        ".pred-row { padding: 0 4px 7px 34px; } .pred-row .pred-text { font-size: 17px; }"
        ".section-label { margin: 6px 0 4px; font-size: 12px; font-weight: 800;"
        " letter-spacing: 3px; text-transform: uppercase; color: var(--blue); }"
        "</style></head>",
    )
    # swap the football footer + subtitle for the news brand
    html_src = html_src.replace(
        "The Pitch Agent by BuildWithAbdallah | Independent analytics | Not affiliated with FIFA",
        "Build With Abdallah  |  AI news, explained simply",
    ).replace(
        "The Pitch Agent <b>•</b> Independent Football Analytics",
        "Build With Abdallah <b>•</b> AI &amp; Dev News",
    )
    rows = ['<div class="section-label">The story · step by step</div>']
    for head, detail in STEPS:
        rows.append(
            f'<div class="row"><span class="dot"></span>'
            f'<span class="label">{_html.escape(head)}</span></div>'
        )
        rows.append(
            f'<div class="pred-row"><div class="pred-text">{_html.escape(detail)}</div></div>'
        )
    content = f'<div class="rows">{chr(10).join(rows)}</div>'
    html_src = (html_src.replace("{{title}}", _html.escape(TITLE))
                        .replace("{{subtitle_meta}}", HC._meta_html(SUBTITLE))
                        .replace("{{content}}", content)
                        .replace("{{logo}}", HC._load_logo_img()))
    return HC._render_html_to_png(html_src, str(CARD))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-telegram", action="store_true")
    args = ap.parse_args()
    load_env()

    card = build_card()
    print(f"[news-short] card -> {card}")

    import football_youtube_short as FY
    video = FY.make_short(card=card, out=VIDEO, voiceover=VOICEOVER,
                          title=HEADLINE, cta=CTA)
    print(f"[news-short] video -> {video} ({video.stat().st_size // 1024} KB)")

    if not args.no_telegram:
        import os
        tok_file = os.path.expanduser("~/.telegram-bot-token")
        if os.path.exists(tok_file):
            t = open(tok_file).read().strip()
            os.environ["TELEGRAM_BOT_TOKEN"] = t
            os.environ["TELEGRAM_TOKEN"] = t
        os.environ.setdefault("TELEGRAM_CHAT_ID", "-1003948211258")
        os.environ.setdefault("TELEGRAM_MESSAGE_THREAD_ID", "14119")
        import telegram_poster as TG
        cap = ("🎬 PREVIEW - GPT-6 news Short (same format + voice as the football "
               "prediction Shorts). Step-by-step explainer. NOT uploaded yet.")
        TG.post_video(str(video), caption=cap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
