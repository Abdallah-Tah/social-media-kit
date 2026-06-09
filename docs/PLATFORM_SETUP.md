# Platform Setup Guide

## Facebook Page

### Prerequisites
- A Facebook Page (not personal profile)
- A Meta Developer account

### Steps
1. Go to https://developers.facebook.com/
2. Create a new app → Select "Business" type
3. Add "Facebook Login for Business" product
4. Under App Settings → Advanced, add your redirect URL
5. Generate a **long-lived Page Access Token**:
   - Use the Graph API Explorer with `pages_show_list`, `pages_read_engagement`, `pages_manage_posts` permissions
   - Exchange short-lived token: `GET /oauth/access_token?grant_type=fb_exchange_token&...`
6. Set in `secrets.env`:
   ```
   FB_PAGE_ID=your_page_id
   FB_PAGE_TOKEN=your_long_lived_token
   ```

### Token Refresh
Facebook long-lived tokens expire after ~60 days. Set a calendar reminder to refresh them.
Use the Graph API Explorer or run:
```bash
python scripts/fb_poster.py --refresh-token
```

---

## X (Twitter)

### Prerequisites
- X Developer account (https://developer.x.com/)
- A project and app created

### Steps
1. Create a project → Create an app under it
2. Go to "Keys and tokens" → Generate:
   - API Key + Secret
   - Access Token + Secret (set permissions to Read and Write)
3. Run the OAuth flow:
   ```bash
   python scripts/x_oauth_exchange.py --setup
   ```
4. Follow the browser prompts → Enter the PIN

### Credentials
All stored in `secrets.env`:
```
X_API_KEY=***
X_API_SECRET=***
X_ACCESS_TOKEN=***
X_ACCESS_TOKEN_SECRET=***
```

---

## LinkedIn

### Prerequisites
- LinkedIn Developer account (https://www.linkedin.com/developers/)
- A LinkedIn Page (for company posts) or personal profile

### Steps
1. Create an app at https://www.linkedin.com/developers/
2. Add "Share on LinkedIn" product
3. Set the redirect URL in auth settings
4. Run the OAuth flow:
   ```bash
   python scripts/linkedin_oauth.py
   ```
5. Authorize in browser → Paste the code → Token saved automatically

### Token Refresh
LinkedIn access tokens expire after 60 days. Re-run `linkedin_oauth.py` when needed.

---

## Blog API (Generic REST)

The blog publisher works with any REST API that accepts a POST to `/posts` with a JSON body.

### Supported Platforms
- **Laravel** (BuildWithAbdallah uses this)
- **WordPress** (with REST API plugin)
- **Ghost**
- Any custom REST API

### Setup
Set in `secrets.env`:
```
BLOG_API_URL=https://yourblog.com/api/v1
BLOG_API_TOKEN=your_token_here
```

### Usage
```bash
# Publish from a markdown file
python scripts/blog_publisher.py --title "My Article" --file article.md

# Save as draft
python scripts/blog_publisher.py --title "Draft" --file draft.md --draft

# With metadata
python scripts/blog_publisher.py --title "My Article" --file article.md \
  --category 3 --tags "2,5,7" --featured --meta-title "SEO Title" --meta-desc "Description"
```

---

## Asset Generation

### Logo & Banner
```bash
python scripts/make_assets.py --logo --brand "B"
python scripts/make_assets.py --banner --name "BuildWithAbdallah" --tagline "Tech • AI • Innovation"
```

### Social Cards (HTML → PNG)
```bash
# First install Playwright
npm install playwright

# Render a card
node scripts/render_card.mjs card.html card.png 1080 1080
```

---

## Slack

Two options — pick one:

**Incoming Webhook (simplest)**
1. https://api.slack.com/apps → Create App → "Incoming Webhooks" → enable.
2. "Add New Webhook to Workspace", pick a channel, copy the URL.
3. `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...`

**Bot token**
1. Create an app → OAuth & Permissions → add `chat:write` scope → install.
2. Copy the Bot User OAuth Token (`xoxb-...`) and set:
   ```
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_CHANNEL=#general
   ```

---

## Discord

1. Server Settings → Integrations → Webhooks → New Webhook.
2. Pick a channel, "Copy Webhook URL".
3. `DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...`

---

## Telegram

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Add the bot to your channel/group as an admin.
3. Set:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=@yourchannel   # or a numeric id
   ```

---

## Mastodon

1. On your instance: Preferences → Development → New application.
2. Grant `write:statuses`, create it, copy "Your access token".
3. Set:
   ```
   MASTODON_BASE_URL=https://mastodon.social
   MASTODON_ACCESS_TOKEN=...
   ```

---

## Bluesky

1. In the Bluesky app: **Settings → App Passwords → Add App Password** (do NOT
   use your main login password).
2. Set:
   ```
   BLUESKY_HANDLE=you.bsky.social
   BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
   ```
   Supports text + one image (≤ 300 chars). Self-hosted PDS? Set `BLUESKY_PDS`.

---

## Threads

1. At https://developers.facebook.com/ add the **Threads API** product and get
   a long-lived user token + your Threads user id.
2. Set:
   ```
   THREADS_USER_ID=
   THREADS_ACCESS_TOKEN=
   ```
   Text posts work directly; image posts need a **public image URL** (the agent
   passes the blog cover URL automatically).

---

## Reddit

1. Create a **script** app at https://www.reddit.com/prefs/apps (type: *script*).
2. Set:
   ```
   REDDIT_CLIENT_ID=
   REDDIT_CLIENT_SECRET=
   REDDIT_USERNAME=
   REDDIT_PASSWORD=
   REDDIT_SUBREDDIT=test
   REDDIT_USER_AGENT=social-media-agent by u/yourname
   ```
   Posts a self (text) post to the target subreddit. Respect each subreddit's
   self-promotion rules.

---

## Pinterest

1. Create an app and access token at https://developers.pinterest.com/ and grab
   a board id.
2. Set:
   ```
   PINTEREST_ACCESS_TOKEN=
   PINTEREST_BOARD_ID=
   ```
   A Pin needs a **public image URL** — the agent uses the generated cover URL.

---

## Any other platform (Generic Webhook)

For Zapier, Make, n8n, Buffer, a custom CMS, or an internal service:
```
WEBHOOK_URL=https://your-endpoint.example.com/post
# Optional: match your endpoint's expected JSON key (default "text")
WEBHOOK_TEXT_KEY=message
# Optional: auth header
WEBHOOK_AUTH_HEADER=Bearer your_token
```
The poster sends `{"<WEBHOOK_TEXT_KEY>": "<message>"}` as JSON.

---

## LLM Providers

The agent needs ONE of these (set in `config/secrets.env`):

```
# Claude
BWA_ANTHROPIC_API_KEY=sk-ant-...
# OpenAI / OpenRouter / compatible
OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://openrouter.ai/api/v1
NVIDIA_API_KEY=nvapi-...
# NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
# Ollama (local) needs no key — just run `ollama serve`
```
Set the active provider in `config/agent.yaml` (`provider: anthropic|openai|nvidia|ollama`).

---

## Cover Images (optional)

The agent generates a hero image per article. It tries FAL.ai → OpenAI Images
→ a free branded Pillow card (no key). Configure whichever you want:

```
# FAL.ai (flux-pro) — get a key at https://fal.ai/dashboard/keys
FAL_KEY=your_fal_key
# Or reuse OpenAI for images (uses OPENAI_API_KEY above)
# Force a provider:
# IMAGE_PROVIDER=fal        # fal | openai | card
```

No key set? You still get a branded title card automatically — nothing breaks.
