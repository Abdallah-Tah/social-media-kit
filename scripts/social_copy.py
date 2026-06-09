#!/usr/bin/env python3
"""Shared social-copy generator — simple, human, Abdallah's voice.

Build With Abdallah social posts must sound like a developer sharing something
useful, in simple English (Abdallah's second language). No hype, no ad tone, no
AI-polish, few emojis, 3-5 hashtags, and specific about what the tutorial builds.
Used by the LinkedIn, Facebook, and Reel posters so every channel matches.
"""
import os
import re
import requests

BANNED = [
    "unlock the power", "unlock", "dive into", "elevate your skills", "elevate",
    "seamlessly", "seamless", "game changer", "game-changer", "packed with features",
    "transform your workflow", "robust", "revolutionize", "revolutionary",
    "supercharge", "harness", "take your", "to the next level", "cutting-edge",
    "transformative", "industry-leading", "next-generation", "groundbreaking",
    "unprecedented", "world-class", "future-proof", "time will tell", "stay tuned",
    "the future looks bright", "this changes everything", "exciting times ahead",
]


def _strip_md(t):
    t = t or ""
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"__([^_]+)__", r"\1", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s+", "", t, flags=re.M)
    return t.strip()


def _topics_from_body(body):
    """Pull the tutorial's real sections so the bullets describe what it builds."""
    skip = re.compile(r"^(introduction|prerequisites|conclusion|sources|common (errors|pitfalls)|"
                      r"putting it together|what you|overview|getting started)\b", re.I)
    heads = re.findall(r"^#{2,3}\s+(.+?)\s*$", body or "", re.M)
    heads = [re.sub(r"^\s*(step\s*\d+[:.)-]*\s*)", "", h, flags=re.I).strip() for h in heads]
    return [h for h in heads if h and not skip.match(h)][:6]


def make_social_copy(title, body, url, model="gpt-4o-mini"):
    """Return a short, simple, human social post (plain text) + 3-5 hashtags."""
    topics = _topics_from_body(body)
    prompt = (
        "Write a short social media post for Abdallah, a full-stack developer. English is his second "
        "language, so write in SIMPLE, natural, human English. It should sound like a developer sharing "
        "something useful — not corporate, not an ad, not AI-generated, no big claims.\n\n"
        "Social posts must NOT be article summaries or table-of-contents listings. Never list section "
        "headings like Project Structure, Section 1, Install X, Configure Y. People do not click for headings.\n\n"
        "Follow this structure:\n"
        "1) Hook: a practical problem, insight, lesson, or observation.\n"
        "2) What the article covers: briefly explain the value, not the table of contents.\n"
        "3) Why it matters: explain practical value for real projects.\n"
        "4) Link:\n" + url + "\n"
        "5) 3 to 5 relevant hashtags on one line, including #BuildWithAbdallah.\n\n"
        f"NEVER use these phrases: {', '.join(BANNED)}. No emojis except at most one. Keep it short. "
        "Be specific and concrete. No markdown formatting (no ** or backticks).\n\n"
        f"ARTICLE TITLE: {title}\n"
        f"WHAT THE TUTORIAL COVERS (use these for the bullets, simplified): {topics}\n\n"
        "Output ONLY the post text."
    )
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.5, "max_tokens": 500},
                timeout=60,
            )
            if r.ok:
                text = _strip_md(r.json()["choices"][0]["message"]["content"])
                # final guard: drop any banned phrase that slipped through
                low = text.lower()
                if not any(b in low for b in BANNED):
                    return text
        except Exception as e:
            print(f"⚠️ social copy gen failed ({e}); using template.")
    # Simple deterministic fallback in the same style.
    value = (topics[0].lower() if topics else "build the feature without guessing through the setup")
    return (f"Many developers can follow a tutorial, but the hard part is knowing when the pattern is worth using.\n\n"
            f"This article shows how to {value} in a practical project.\n\n"
            "The useful part is understanding the tradeoffs before this reaches production.\n\n"
            f"Read it here:\n{url}\n\n#coding #webdev #BuildWithAbdallah")


def make_news_social_copy(title, body, url, model="gpt-4o-mini"):
    """Return a short news-analysis social post with the site link."""
    prompt = (
        "Write a short social media post for Abdallah, a full-stack developer. English is his second "
        "language, so write in SIMPLE, natural, human English. This is developer news analysis, not a "
        "tutorial. No hype, no ad tone, no AI-polish.\n\n"
        "Social posts must NOT be article summaries or table-of-contents listings.\n\n"
        "Follow this structure:\n"
        "1) Hook: a practical problem, insight, lesson, or observation.\n"
        "2) What the article covers: briefly explain the value, not the table of contents.\n"
        "3) Why it matters: explain practical value for real projects.\n"
        "4) Link:\n" + url + "\n"
        "5) 3 to 5 relevant hashtags on one line, including #BuildWithAbdallah.\n\n"
        f"NEVER use these phrases: {', '.join(BANNED)}. No markdown formatting. No clickbait.\n\n"
        f"ARTICLE TITLE: {title}\n"
        f"ARTICLE BODY EXCERPT: {(body or '')[:1200]}\n\n"
        "Output ONLY the post text."
    )
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.45, "max_tokens": 420},
                timeout=60,
            )
            if r.ok:
                text = _strip_md(r.json()["choices"][0]["message"]["content"])
                low = text.lower()
                if not any(b in low for b in BANNED):
                    return text
        except Exception as e:
            print(f"⚠️ news social copy gen failed ({e}); using template.")
    return (f"New developer tools are useful only when they solve a real problem in a real project.\n\n"
            f"This article breaks down {title} and what it could mean for builders.\n\n"
            "The main question is what I would test first before trusting it in production.\n\n"
            f"Read it here:\n{url}\n\n#SoftwareDevelopment #TechNews #BuildWithAbdallah")
