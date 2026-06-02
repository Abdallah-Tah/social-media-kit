# API Reference — Social Media Agent

## smkit (the agent CLI)

The orchestrated agent. See [AGENT_GUIDE.md](AGENT_GUIDE.md) for the full picture.

```bash
smkit run --topic "Your topic" --dry-run        # research → write → publish (simulated)
smkit run --goal "Free-form instruction" --yes  # explicit goal, go live
smkit run --topic "..." --provider ollama        # local model, no API key
smkit queue config/topics.txt --yes              # run next queued topic
smkit wizard                                      # interactive setup
smkit doctor                                      # check providers + channels
smkit profiles                                    # list brand profiles
smkit install-skill                               # register as a permanent OpenClaw skill
```

`smkit install-skill [--skills-dir PATH] [--copy] [--force]` links the kit into
your OpenClaw / Claude Code skills root so the agent uses it every session.

| Flag | Description |
|------|-------------|
| `--topic`, `-t` | Topic to research, write, and publish |
| `--goal`, `-g` | Explicit free-form goal (instead of `--topic`) |
| `--profile`, `-p` | Brand profile name (default `default`) |
| `--provider` | `anthropic` \| `openai` \| `ollama` (overrides agent.yaml) |
| `--model` | Override the model id |
| `--dry-run` | Simulate publishing (nothing goes live) |
| `--yes`, `-y` | Skip the live-mode confirmation |
| `--max-steps` | Max agent steps before forced finish |
| `--verbose`, `-v` | Show full reasoning + tool output |

`python -m agent ...` is an exact alias for `smkit ...`.

---

## fb_poster.py

Post to a Facebook Page via the Graph API.

```bash
# Text post
python scripts/fb_poster.py --message "Hello world"

# Post with link
python scripts/fb_poster.py --message "Check this out" --link "https://example.com"

# Photo post
python scripts/fb_poster.py --image photo.png --caption "My photo"

# Delete a post
python scripts/fb_poster.py --delete "post_id_here"
```

| Flag | Description |
|------|-------------|
| `--message`, `-m` | Post message text |
| `--link`, `-l` | URL to include |
| `--image`, `-i` | Image file path (posts as photo) |
| `--delete`, `-d` | Post ID to delete |

---

## x_poster.py

Post tweets via the X API v2.

```bash
# Post a tweet
python scripts/x_poster.py "Tweet text here"

# Delete a tweet
python scripts/x_poster.py --delete "tweet_id"
```

| Flag | Description |
|------|-------------|
| `text` (positional) | Tweet text |
| `--delete`, `-d` | Tweet ID to delete |

---

## x_oauth_exchange.py

Full OAuth 1.0a flow for X API access.

```bash
# Interactive setup (browser-based)
python scripts/x_oauth_exchange.py --setup

# Resume with verifier
python scripts/x_oauth_exchange.py --verifier "PIN_CODE"
```

| Flag | Description |
|------|-------------|
| `--setup` | Run full interactive OAuth flow |
| `--verifier`, `-v` | OAuth verifier PIN from callback |

---

## linkedin_oauth.py

OAuth2 flow to get a LinkedIn access token.

```bash
python scripts/linkedin_oauth.py
```

Opens browser for authorization, then saves token to `secrets.env`.

---

## linkedin_poster.py

Post to LinkedIn using the API.

```bash
# Post a text update
python scripts/linkedin_poster.py "Sharing an update"

# Post with limited visibility
python scripts/linkedin_poster.py "Internal update" --visibility CONNECTIONS
```

| Flag | Description |
|------|-------------|
| `text` (positional) | Post text |
| `--visibility`, `-v` | `PUBLIC` (default) or `CONNECTIONS` |

---

## slack_poster.py / discord_poster.py / telegram_poster.py / mastodon_poster.py / webhook_poster.py

Post a message to the respective channel. All take the text as a positional arg.

```bash
python scripts/slack_poster.py "Shipping a new post 🚀"
python scripts/discord_poster.py "New article is live"
python scripts/telegram_poster.py "New article is live"
python scripts/mastodon_poster.py "New article is live" --visibility public
python scripts/webhook_poster.py "Any platform" --url https://hooks.example.com/x
```

| Script | Required env | Notes |
|--------|--------------|-------|
| `slack_poster.py` | `SLACK_WEBHOOK_URL` **or** `SLACK_BOT_TOKEN`+`SLACK_CHANNEL` | `--channel` override |
| `discord_poster.py` | `DISCORD_WEBHOOK_URL` | ≤ 2000 chars; `--username` override |
| `telegram_poster.py` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `--chat` override |
| `mastodon_poster.py` | `MASTODON_BASE_URL`, `MASTODON_ACCESS_TOKEN` | `--visibility` |
| `webhook_poster.py` | `WEBHOOK_URL` | `--url`, `--extra '{"k":"v"}'` |

---

## image_generator.py

Generate a cover/hero image (FAL.ai → OpenAI Images → free branded card).

```bash
python scripts/image_generator.py "Laravel 13 AI SDK" --out cover.png
python scripts/image_generator.py "My Title" --provider fal
```

| Flag | Description |
|------|-------------|
| `title` (positional) | Article/post title (drives the default prompt) |
| `--prompt`, `-p` | Override the image prompt |
| `--out`, `-o` | Output PNG path |
| `--provider` | `fal` \| `openai` \| `card` |

Env: `FAL_KEY` (FAL.ai), `OPENAI_API_KEY` (OpenAI), `IMAGE_PROVIDER` to force one,
`FAL_MODEL` / `OPENAI_IMAGE_MODEL` to override models. With no key it falls back
to a branded Pillow card.

---

## blog_publisher.py

Push articles to a blog via REST API.

```bash
# Publish from a markdown file
python scripts/blog_publisher.py --title "My Article" --file article.md

# Save as draft
python scripts/blog_publisher.py --title "Draft" --file draft.md --draft

# With full metadata
python scripts/blog_publisher.py \
  --title "Laravel 13 Deep Dive" \
  --file article.md \
  --slug "laravel-13-deep-dive" \
  --excerpt "A deep dive into Laravel 13 features" \
  --category 3 \
  --tags "2,5,7" \
  --featured \
  --meta-title "Laravel 13 — Build With Abdallah" \
  --meta-desc "Laravel 13 AI SDK, vector search, and PHP attributes"
```

| Flag | Description |
|------|-------------|
| `--title`, `-t` | Article title (required) |
| `--slug`, `-s` | URL slug (auto-generated from title) |
| `--file`, `-f` | Markdown file to publish |
| `--excerpt`, `-e` | Article excerpt |
| `--category`, `-c` | Category ID (integer) |
| `--tags` | Comma-separated tag IDs |
| `--draft` | Save as draft (don't publish) |
| `--featured` | Mark as featured |
| `--meta-title` | SEO meta title |
| `--meta-desc` | SEO meta description |

---

## make_assets.py

Generate logos, banners, and social cards.

```bash
# Generate everything
python scripts/make_assets.py --all --brand "B" --name "MyBrand"

# Just a logo
python scripts/make_assets.py --logo --brand "B"

# Just a banner
python scripts/make_assets.py --banner --name "MyBrand" --tagline "Tagline"

# Just a card
python scripts/make_assets.py --card --title "Title" --subtitle "Subtitle"
```

| Flag | Description |
|------|-------------|
| `--logo` | Generate logo |
| `--banner` | Generate banner |
| `--card` | Generate social card |
| `--all` | Generate all assets |
| `--brand` | Brand letter for logo (default: "B") |
| `--name` | Brand name for banner |
| `--tagline` | Banner tagline |
| `--title` | Card title |
| `--subtitle` | Card subtitle |
| `--bg` | Background color hex (default: #0f172a) |
| `--accent` | Accent color hex (default: #2563eb) |
| `--output`, `-o` | Output directory (default: assets/) |

---

## convert_code_blocks.py

Convert Markdown fenced code blocks to HTML `<pre><code>`.

```bash
# Convert in-place
python scripts/convert_code_blocks.py article.md

# Convert to a different file
python scripts/convert_code_blocks.py article.md --output article.html.md
```

| Flag | Description |
|------|-------------|
| `input` (positional) | Input markdown file |
| `--output`, `-o` | Output file (default: overwrite input) |

---

## render_card.mjs

Render HTML templates to retina-quality PNG screenshots using Playwright.

```bash
# Render a 1080x1080 card
node scripts/render_card.mjs card.html card.png

# Custom dimensions
node scripts/render_card.mjs card.html card.png 1640 660
```

| Argument | Description |
|----------|-------------|
| `input.html` | Input HTML file |
| `output.png` | Output PNG file |
| `width` | Width in pixels (default: 1080) |
| `height` | Height in pixels (default: 1080) |