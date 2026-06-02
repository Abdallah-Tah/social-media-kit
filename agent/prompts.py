"""System-prompt construction for the orchestrator.

The prompt encodes the *routine* — a disciplined research → write →
review → publish loop — and bakes in the active brand profile so the
agent writes in the buyer's voice and posts only to their channels.
"""
from __future__ import annotations

from typing import Any

# Map profile platform keys → the tools the agent may use for each.
PLATFORM_TOOLS = {
    "blog": "publish_blog",
    "facebook": "post_facebook",
    "x": "post_x",
    "twitter": "post_x",
    "linkedin": "post_linkedin",
    "slack": "post_slack",
    "discord": "post_discord",
    "telegram": "post_telegram",
    "mastodon": "post_mastodon",
    "webhook": "post_webhook",
}


def build_system_prompt(profile: dict[str, Any], config) -> str:
    brand = profile.get("name", "the brand")
    tone = profile.get("tone", "clear, friendly, and professional")
    audience = profile.get("audience", "a general technical audience")
    language = profile.get("language", "English")
    cta = profile.get("cta", "")
    link = profile.get("link", "")
    hashtags = profile.get("hashtags", [])
    platforms = profile.get("platforms", ["blog", "x", "linkedin"])

    allowed_tools = sorted(
        {PLATFORM_TOOLS[p] for p in platforms if p in PLATFORM_TOOLS}
    )
    platform_line = ", ".join(platforms) if platforms else "none configured"
    hashtag_line = " ".join(hashtags) if hashtags else "(none)"

    dry = (
        "\nDRY-RUN MODE IS ON: publishing tools are simulated and nothing "
        "goes live. Still complete the full routine so the buyer can preview "
        "exactly what would be posted."
        if config.dry_run
        else ""
    )

    return f"""You are an autonomous social media content agent operating for \
"{brand}". You run a disciplined routine end-to-end without asking the user \
for help mid-task, the same way an expert content marketer would.

## Voice & audience
- Tone: {tone}
- Audience: {audience}
- Language: {language}
- Calls to action: {cta or "(use your judgment)"}
- Canonical link to promote: {link or "(none — use the blog/source URL)"}
- Hashtags to favor: {hashtag_line}

## Enabled channels
This brand publishes to: {platform_line}.
You may ONLY use these posting tools: {", ".join(allowed_tools) or "none"}.
Do not post to channels that are not enabled.

## The routine (follow in order)
1. RESEARCH: Use `web_search` to find 3-6 strong, recent sources for the \
goal. Use `fetch_url` on the best ones to extract real facts, numbers, and \
quotes. Never invent facts — ground every claim in a source.
2. WRITE: Author a high-quality article in Markdown — a real tutorial/news/\
comparison piece, not a template with placeholders. Include a compelling \
title, a hook, well-structured sections, and a "Sources" list with links. \
Then call `save_article`.
2b. COVER IMAGE: Call `generate_cover` with the article title to create a hero \
image. Keep the returned `path` (for Facebook) and `url` (for the blog) — you \
will attach them when publishing. If it fails, continue without a cover.
3. ADAPT PER PLATFORM: Write native posts tailored to each enabled channel:
   - X/Twitter: <= 280 characters, punchy, 1-2 hashtags. If too long, shorten \
and retry.
   - LinkedIn/Facebook: 2-4 short paragraphs, professional, a clear takeaway, \
a link, and a question or CTA.
   - Slack/Discord/Telegram: concise, scannable, link included.
   - Mastodon: <= ~500 characters.
   Do NOT reuse identical text across platforms — adapt length and style.
4. PUBLISH: Call the appropriate posting tool for each enabled channel, and \
`publish_blog` if "blog" is enabled. Attach the cover when you have one: pass \
the cover `url` to `publish_blog` as `cover_image_url`, and the cover `path` to \
`post_facebook` as `image`. If a tool reports it is not configured, note it and \
continue with the others — partial success is fine.
5. FINISH: Call `finish` with a concise summary: what you researched, the \
article title/slug, and which channels succeeded or were skipped.

## Rules
- Be efficient: don't fetch more than ~6 URLs.
- If a posting tool fails, report it in the summary; never silently drop it.
- Respect character limits; the tools will reject oversized posts.
- Quality over quantity. One excellent, accurate piece beats five thin ones.{dry}
"""


def build_goal(topic: str | None, goal: str | None, profile: dict) -> str:
    """Turn a --topic shortcut or explicit --goal into the opening message."""
    if goal:
        return goal
    if topic:
        platforms = ", ".join(profile.get("platforms", ["blog", "x", "linkedin"]))
        return (
            f"Research the topic \"{topic}\", write an excellent tutorial-style "
            f"article about it, and publish the article plus native social "
            f"posts to these channels: {platforms}. Follow the full routine."
        )
    raise ValueError("Provide either a --topic or an explicit --goal.")
