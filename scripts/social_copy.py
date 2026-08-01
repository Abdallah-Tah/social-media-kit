#!/usr/bin/env python3
"""Shared social-copy generator — simple, human, Abdallah's voice.

Build With Abdallah social posts must sound like a developer sharing something
useful, in simple English (Abdallah's second language). No hype, no ad tone, no
AI-polish, few emojis, 3-5 hashtags, and specific about what the tutorial builds.
Used by the LinkedIn, Facebook, and Reel posters so every channel matches.
"""
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content_formats as CF
from agent import llm_ops as LLM

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


_BASE_VOICE = (
    "Write a short social media post for Abdallah, a full-stack developer. English is his second "
    "language, so write in SIMPLE, natural, human English. It should sound like a developer sharing "
    "something useful — not corporate, not an ad, not AI-generated, no big claims.\n\n"
    "Social posts must NOT be article summaries or table-of-contents listings. Never list section "
    "headings like Project Structure, Section 1, Install X, Configure Y. People do not click for headings.\n\n"
)


def _generate(prompt, model, temperature=0.7):
    """One completion, with the banned-phrase guard. None means fall back."""
    if not os.environ.get("OPENAI_API_KEY", ""):
        return None
    result = LLM.chat([{"role": "user", "content": prompt}], model=model,
                      temperature=temperature, max_tokens=500, timeout=60,
                      job_id="social_copy")
    if not result.ok:
        print(f"\u26a0\ufe0f social copy gen failed ({result.error_class}); using template.")
        return None
    text = _strip_md(result.text)
    if any(b in text.lower() for b in BANNED):
        return None
    return text


def _tail(url):
    return (
        "4) The link on its own line:\n" + url + "\n"
        "5) 3 to 5 relevant hashtags on one line, including #BuildWithAbdallah.\n\n"
        f"NEVER use these phrases: {', '.join(BANNED)}. No emojis except at most one. Keep it short. "
        "Be specific and concrete. No markdown formatting (no ** or backticks).\n\n"
    )


def make_social_copy(title, body, url, model="gpt-4o-mini", shape_id=None):
    """Return a short, simple, human social post (plain text) + 3-5 hashtags.

    The post's SHAPE rotates (see content_formats.SOCIAL_SHAPES) so the feed
    doesn't read as the same three-paragraph template every single day.
    """
    topics = _topics_from_body(body)
    shape = CF.social_shape(shape_id or CF.pick_social_shape())
    prompt = (
        _BASE_VOICE
        + f"POST SHAPE — {shape['label']}. Follow this structure:\n{shape['structure']}"
        + _tail(url)
        + f"ARTICLE TITLE: {title}\n"
        f"WHAT THE ARTICLE COVERS (source material for the post, simplified — do not list these): {topics}\n\n"
        "Output ONLY the post text."
    )
    # Record either way — the post goes out in this shape whether the model
    # wrote it or the fallback did, so the rotation must advance regardless.
    CF.record("social", shape["id"], url, title)
    text = _generate(prompt, model)
    if text:
        return text

    # Deterministic fallback, still in this shape's voice.
    value = (f"This one is about {topics[0].lower()} in a practical project." if topics
             else "This one is about getting the setup right without guessing.")
    return (shape["fallback"].format(value=value)
            + f"\n\nRead it here:\n{url}\n\n#coding #webdev #BuildWithAbdallah")


def make_news_social_copy(title, body, url, model="gpt-4o-mini", shape_id=None):
    """Return a short news-analysis social post with the site link.

    Shares the shape rotation with the tutorial lane, so a news post and the
    tutorial posted the same week don't land in the feed reading identically.
    """
    shape = CF.social_shape(shape_id or CF.pick_social_shape())
    prompt = (
        "Write a short social media post for Abdallah, a full-stack developer. English is his second "
        "language, so write in SIMPLE, natural, human English. This is developer news analysis, not a "
        "tutorial. No hype, no ad tone, no AI-polish.\n\n"
        "Social posts must NOT be article summaries or table-of-contents listings.\n"
        "Only state facts that appear in the article excerpt below. Never invent a version number, "
        "benchmark, or date, and attribute vendor figures as vendor-reported.\n\n"
        f"POST SHAPE — {shape['label']}. Follow this structure:\n{shape['structure']}"
        + _tail(url)
        + f"ARTICLE TITLE: {title}\n"
        f"ARTICLE BODY EXCERPT: {(body or '')[:1200]}\n\n"
        "Output ONLY the post text."
    )
    CF.record("social", shape["id"], url, title)
    text = _generate(prompt, model, temperature=0.55)
    if text:
        return text
    value = f"This one breaks down {title} and what it means for people actually shipping code."
    return (shape["fallback"].format(value=value)
            + f"\n\nRead it here:\n{url}\n\n#SoftwareDevelopment #TechNews #BuildWithAbdallah")


def make_x_social_copy(title, body, url, model="gpt-4o-mini"):
    """Return an X post that fits in 280 characters *including* the link.

    X is the one channel with a hard limit, so this does not share the shape
    rotation used by the Facebook/LinkedIn copy — those shapes assume room for
    a multi-paragraph post plus a hashtag line, and truncating one to fit
    produced a post that stopped mid-sentence. The prose budget here is
    whatever is left after the URL, so the link always survives intact.
    """
    budget = 280 - len(url) - 2  # blank line between prose and link
    prompt = (
        "Write ONE short post for X (Twitter) for Abdallah, a full-stack developer. English is his "
        "second language, so write in SIMPLE, natural, human English. This is developer news, not a "
        "tutorial. No hype, no ad tone, no AI-polish.\n\n"
        f"HARD LIMIT: at most {min(budget, 200)} characters. Two sentences maximum.\n"
        "State one concrete, specific fact from the article, then why it matters to someone shipping "
        "code. Only state facts that appear in the excerpt below. Never invent a version number, "
        "benchmark, or date, and attribute vendor figures as vendor-reported.\n"
        "No hashtags. No emojis. No link — the link is added afterwards. No markdown.\n\n"
        f"ARTICLE TITLE: {title}\n"
        f"ARTICLE BODY EXCERPT: {(body or '')[:1200]}\n\n"
        "Output ONLY the post text."
    )
    prose = _generate(prompt, model, temperature=0.55)
    if not prose:
        # Deterministic fallback: the article's own opening, trimmed to budget.
        para = next((p.strip() for p in _strip_md(body or "").split("\n\n")
                     if len(p.strip()) > 120 and not p.strip().startswith("#")), "")
        prose = para or f"New write-up: {title}."
    prose = " ".join(prose.split())
    if len(prose) > budget:
        prose = prose[:budget].rsplit(" ", 1)[0].rstrip(" .,;:—-")
    return f"{prose}\n\n{url}"
