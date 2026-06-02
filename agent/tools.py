"""The agent's tools — JSON-schema'd capabilities backed by the kit's scripts.

Each tool maps to a function in ``scripts/``. The orchestrator hands the
model ``TOOL_SCHEMAS``; when the model emits a tool call we route it
through ``ToolBox.dispatch`` and feed the textual result back into the
conversation.

Publishing/posting tools honour ``config.dry_run`` so buyers can rehearse
a full run with zero side effects before going live.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .config import ROOT

# Make the standalone scripts importable as plain modules.
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

CONTENT_DIR = ROOT / "content"
DRAFTS_DIR = CONTENT_DIR / "drafts"
ASSETS_DIR = CONTENT_DIR / "assets"

# Hard platform limits the model must respect.
X_LIMIT = 280


# ── Tool schemas (provider-neutral JSON Schema) ─────────────────────────
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "web_search",
        "description": (
            "Search the web for articles, tutorials, and news on a topic. "
            "Returns ranked results with titles, URLs, and snippets. Use this "
            "first to gather sources before writing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "count": {
                    "type": "integer",
                    "description": "How many results to return (1-10).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": (
            "Fetch a URL and return its readable text content. Use on the most "
            "promising search results to extract facts and quotes for the draft."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch."},
                "max_chars": {
                    "type": "integer",
                    "description": "Max characters to return.",
                    "default": 5000,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "save_article",
        "description": (
            "Save a finished article as a Markdown draft. Pass the full article "
            "body you authored (Markdown). Returns the saved file path and slug, "
            "which you can hand to publish_blog."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "markdown": {
                    "type": "string",
                    "description": "Full article body in Markdown.",
                },
                "slug": {
                    "type": "string",
                    "description": "Optional URL slug (auto-generated if omitted).",
                },
                "excerpt": {"type": "string", "description": "Short summary."},
            },
            "required": ["title", "markdown"],
        },
    },
    {
        "name": "publish_blog",
        "description": (
            "Publish an article to the configured blog via REST API. Provide "
            "either draft_path (from save_article) or the markdown directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "draft_path": {
                    "type": "string",
                    "description": "Path returned by save_article.",
                },
                "markdown": {
                    "type": "string",
                    "description": "Article body (if no draft_path).",
                },
                "slug": {"type": "string"},
                "excerpt": {"type": "string"},
                "category_id": {"type": "integer"},
                "tags": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Tag IDs.",
                },
                "draft": {
                    "type": "boolean",
                    "description": "Save as draft instead of publishing.",
                    "default": False,
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "post_facebook",
        "description": "Post a text update (optionally with a link) to the Facebook Page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "link": {"type": "string", "description": "Optional URL to attach."},
            },
            "required": ["message"],
        },
    },
    {
        "name": "post_x",
        "description": (
            f"Post a tweet to X (Twitter). Must be <= {X_LIMIT} characters; "
            "the call is rejected otherwise so you can shorten it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "post_linkedin",
        "description": "Post a text update to LinkedIn.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "visibility": {
                    "type": "string",
                    "enum": ["PUBLIC", "CONNECTIONS"],
                    "default": "PUBLIC",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "post_slack",
        "description": "Post a message to Slack (incoming webhook or bot token).",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "channel": {
                    "type": "string",
                    "description": "Channel override (bot-token mode only).",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "post_discord",
        "description": "Post a message to a Discord channel via webhook (<= 2000 chars).",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "post_telegram",
        "description": "Post a message to a Telegram chat/channel via the Bot API.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "post_mastodon",
        "description": "Post a status to Mastodon (<= ~500 chars on most instances).",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "visibility": {
                    "type": "string",
                    "enum": ["public", "unlisted", "private", "direct"],
                    "default": "public",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "post_webhook",
        "description": (
            "Post to ANY platform via a generic HTTP webhook (Zapier, Make, "
            "n8n, Buffer, a custom CMS, etc.). Use this for channels without a "
            "dedicated tool. Sends {\"text\": <message>} as JSON."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "url": {
                    "type": "string",
                    "description": "Optional URL override (else uses WEBHOOK_URL).",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "generate_card",
        "description": (
            "Generate a branded square social card (PNG) with a title and "
            "subtitle, using the active profile's colors. Returns the image path."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "finish",
        "description": (
            "Call this when the goal is complete. Provide a short summary of "
            "what was researched, written, and published."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]

# Tools that touch the outside world — gated by dry-run.
PUBLISHING_TOOLS = {
    "publish_blog",
    "post_facebook",
    "post_x",
    "post_linkedin",
    "post_slack",
    "post_discord",
    "post_telegram",
    "post_mastodon",
    "post_webhook",
}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:80] or "untitled"


class ToolBox:
    """Stateful dispatcher: holds config + profile, runs tool calls."""

    def __init__(self, config, profile: dict[str, Any]):
        self.config = config
        self.profile = profile or {}
        self._handlers: dict[str, Callable[[dict], str]] = {
            "web_search": self._web_search,
            "fetch_url": self._fetch_url,
            "save_article": self._save_article,
            "publish_blog": self._publish_blog,
            "post_facebook": self._post_facebook,
            "post_x": self._post_x,
            "post_linkedin": self._post_linkedin,
            "post_slack": self._post_slack,
            "post_discord": self._post_discord,
            "post_telegram": self._post_telegram,
            "post_mastodon": self._post_mastodon,
            "post_webhook": self._post_webhook,
            "generate_card": self._generate_card,
        }

    def dispatch(self, name: str, tool_input: dict[str, Any]) -> str:
        """Run a tool call and return a string result for the model."""
        handler = self._handlers.get(name)
        if handler is None:
            return f"ERROR: unknown tool '{name}'."

        # Enforce hard limits even in dry-run, so rehearsals catch problems.
        limit_error = self._check_limits(name, tool_input)
        if limit_error:
            return limit_error

        if name in PUBLISHING_TOOLS and self.config.dry_run:
            return (
                f"[DRY RUN] Would call {name} with: "
                f"{json.dumps(tool_input, ensure_ascii=False)[:500]}. "
                "No content was actually published."
            )
        try:
            return handler(tool_input)
        except Exception as exc:  # surfaced to the model so it can recover
            return f"ERROR running {name}: {exc}"

    @staticmethod
    def _check_limits(name: str, args: dict) -> str | None:
        """Reject obviously-invalid posts before doing any work."""
        if name == "post_x":
            text = args.get("text", "")
            if len(text) > X_LIMIT:
                return (
                    f"ERROR: tweet is {len(text)} chars (limit {X_LIMIT}). "
                    "Shorten it and call post_x again."
                )
        if name == "post_discord" and len(args.get("text", "")) > 2000:
            return "ERROR: Discord message exceeds 2000 chars. Shorten it."
        return None

    # ── Research ────────────────────────────────────────────────────────
    def _web_search(self, args: dict) -> str:
        import content_research

        count = int(args.get("count", 5))
        results = content_research.web_search(args["query"], count=count)
        if not results:
            return "No results found. Try a different query."
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. {r.get('title', '')}\n   {r.get('url', '')}\n"
                f"   {r.get('description', '')[:200]}"
            )
        return "\n".join(lines)

    def _fetch_url(self, args: dict) -> str:
        import content_research

        max_chars = int(args.get("max_chars", 5000))
        text = content_research.extract_article(args["url"], max_chars=max_chars)
        return text or "[No readable content extracted.]"

    # ── Authoring ───────────────────────────────────────────────────────
    def _save_article(self, args: dict) -> str:
        title = args["title"]
        slug = args.get("slug") or _slugify(title)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        path = DRAFTS_DIR / f"{date.today().isoformat()}_{slug}.md"
        path.write_text(args["markdown"], encoding="utf-8")
        return (
            f"Saved draft to {path} (slug: {slug}, "
            f"{len(args['markdown'])} chars)."
        )

    # ── Publishing ──────────────────────────────────────────────────────
    def _publish_blog(self, args: dict) -> str:
        import blog_publisher

        markdown = args.get("markdown")
        if not markdown and args.get("draft_path"):
            markdown = Path(args["draft_path"]).read_text(encoding="utf-8")
        if not markdown:
            return "ERROR: provide either draft_path or markdown."

        blog = self.profile.get("blog", {})
        title = args["title"]
        result = blog_publisher.publish_article(
            title=title,
            slug=args.get("slug") or _slugify(title),
            content=markdown,
            excerpt=args.get("excerpt", ""),
            category_id=args.get("category_id") or blog.get("category_id"),
            tags=args.get("tags") or blog.get("tags"),
            publish=not args.get("draft", False),
        )
        return self._capture(
            "Blog publish", lambda: result, already=result
        )

    def _post_facebook(self, args: dict) -> str:
        import fb_poster

        return self._capture(
            "Facebook", lambda: fb_poster.post_text(args["message"], link=args.get("link"))
        )

    def _post_x(self, args: dict) -> str:
        import x_poster

        text = args["text"]
        if len(text) > X_LIMIT:
            return (
                f"ERROR: tweet is {len(text)} chars (limit {X_LIMIT}). "
                "Shorten it and call post_x again."
            )
        return self._capture("X", lambda: x_poster.post_tweet(text))

    def _post_linkedin(self, args: dict) -> str:
        import linkedin_poster

        return self._capture(
            "LinkedIn",
            lambda: linkedin_poster.post_text(
                args["text"], visibility=args.get("visibility", "PUBLIC")
            ),
        )

    def _post_slack(self, args: dict) -> str:
        import slack_poster

        return self._capture(
            "Slack",
            lambda: slack_poster.post_message(
                args["text"], channel=args.get("channel")
            ),
        )

    def _post_discord(self, args: dict) -> str:
        import discord_poster

        return self._capture(
            "Discord", lambda: discord_poster.post_message(args["text"])
        )

    def _post_telegram(self, args: dict) -> str:
        import telegram_poster

        return self._capture(
            "Telegram", lambda: telegram_poster.post_message(args["text"])
        )

    def _post_mastodon(self, args: dict) -> str:
        import mastodon_poster

        return self._capture(
            "Mastodon",
            lambda: mastodon_poster.post_status(
                args["text"], visibility=args.get("visibility", "public")
            ),
        )

    def _post_webhook(self, args: dict) -> str:
        import webhook_poster

        return self._capture(
            "Webhook",
            lambda: webhook_poster.post(args["text"], url=args.get("url")),
        )

    # ── Assets ──────────────────────────────────────────────────────────
    def _generate_card(self, args: dict) -> str:
        import make_assets

        branding = self.profile.get("branding", {})
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        path = make_assets.generate_card(
            args["title"],
            subtitle=args.get("subtitle", ""),
            bg_color=branding.get("bg_color", "#0f172a"),
            accent_color=branding.get("accent_color", "#2563eb"),
            output_dir=str(ASSETS_DIR),
        )
        return f"Generated social card: {path}"

    # ── Helper: run a posting fn, capture its stdout + return value ──────
    @staticmethod
    def _capture(label: str, fn: Callable[[], Any], already: Any = "__call__") -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = fn() if already == "__call__" else already
        printed = buf.getvalue().strip()
        if result:
            return f"{label}: success. {printed}".strip()
        return (
            f"{label}: failed or not configured. {printed} "
            "Check credentials in config/secrets.env."
        ).strip()
