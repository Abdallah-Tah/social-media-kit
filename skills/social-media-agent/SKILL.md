---
name: social-media-agent
description: Research a topic on the web, write a high-quality article, and publish it plus native social posts across blog, X, LinkedIn, Facebook, Slack, Discord, Telegram, Mastodon, or any webhook. Use when the user wants to create and distribute content, run a content routine, or publish to social media.
homepage: https://github.com/Abdallah-Tah/social-media-kit
user-invocable: true
metadata:
  {
    "openclaw":
      {
        "emoji": "📡",
        "requires":
          {
            "bins": ["python3"]
          },
        "install":
          [
            {
              "id": "pip",
              "kind": "shell",
              "command": "pip install -r {baseDir}/../../requirements.txt && pip install -e {baseDir}/../..",
              "label": "Install Social Media Agent dependencies"
            }
          ]
      }
  }
---

# Social Media Agent

This skill turns the host agent into an autonomous social-media content
operator. It runs the same disciplined routine every time: **research →
write → adapt per platform → publish → report.**

The kit lives at `{baseDir}/../..` (the repository root). All commands below
assume you run from there, or pass absolute paths.

## When to use this skill

Use it whenever the user wants to:
- "research and publish" something, or "write a tutorial/article about X",
- post or cross-post to social media,
- run a recurring content job.

## Preferred path — the orchestrated CLI

The kit ships a self-contained agent CLI (`smkit`). Prefer it; it handles the
full routine and respects the active brand profile and channel allowlist.

```bash
# Always rehearse first — nothing goes live in dry-run:
smkit run --topic "<topic>" --profile default --dry-run

# Go live (only after the user confirms intent):
smkit run --topic "<topic>" --profile default --yes

# Free-form goal instead of a topic:
smkit run --goal "Compare Postgres and SQLite for small apps; post to LinkedIn and X" --yes

# Provider override (local, no API key):
smkit run --topic "<topic>" --provider ollama --dry-run
```

`smkit doctor` reports which provider and channel credentials are configured.
`smkit profiles` lists available brand voices.

## Direct tools (when you need a single action)

If the user only wants one step, call the underlying scripts at
`{baseDir}/../../scripts/`:

| Action | Command |
|--------|---------|
| Web research | `python3 scripts/content_research.py "<query>" --extract --save` |
| Publish to blog | `python3 scripts/blog_publisher.py --title "<t>" --file <md>` |
| Post to X | `python3 scripts/x_poster.py "<text ≤280 chars>"` |
| Post to LinkedIn | `python3 scripts/linkedin_poster.py "<text>"` |
| Post to Facebook | `python3 scripts/fb_poster.py --message "<text>"` |
| Post to Slack | `python3 scripts/slack_poster.py "<text>"` |
| Post to Discord | `python3 scripts/discord_poster.py "<text>"` |
| Post to Telegram | `python3 scripts/telegram_poster.py "<text>"` |
| Post to Mastodon | `python3 scripts/mastodon_poster.py "<text>"` |
| Post anywhere else | `python3 scripts/webhook_poster.py "<text>"` |
| Generate a card | `python3 scripts/make_assets.py --card --title "<t>"` |

## Rules

1. **Never fabricate facts.** Ground every claim in a fetched source and
   include a Sources section in articles.
2. **Adapt per platform.** X ≤ 280 chars; LinkedIn/Facebook = a few short
   paragraphs with a CTA; Slack/Discord/Telegram = concise + link.
3. **Respect the brand profile** at `{baseDir}/../../config/profiles/`. Only
   post to the channels it enables.
4. **Default to dry-run.** Only publish live after the user confirms.
5. If a channel isn't configured, skip it and report it — partial success is
   fine.

Credentials are read from `{baseDir}/../../config/secrets.env`. See
`config/secrets.env.example` for the full list of supported channels.
