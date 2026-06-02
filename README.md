# 📡 Social Media Kit

**Research, process, and publish content across multiple platforms from the command line.**

Self-contained Python + Node scripts for content research, article processing, and multi-platform publishing. No SaaS subscriptions — just clean API calls you control.

## Features

### 🔍 Content Research
- **Web search** — Find articles, tutorials, and news by topic
- **Content extraction** — Pull readable text from any URL
- **Save research** — Export results as JSON for processing

### 📝 Content Processing
- **Article drafts** — Generate news, tutorial, or comparison templates
- **Key point extraction** — Automatically pull factual claims from sources
- **Social post generation** — Create platform-specific post variants

### 📢 Multi-Platform Publishing
- 📘 **Facebook Page** — Text, links, and photos
- 🐦 **X (Twitter)** — Tweets with OAuth 1.0a
- 💼 **LinkedIn** — Text updates with OAuth2
- 🌐 **Blog** — Push articles via REST API (Laravel, WordPress, Ghost)

### 🎨 Asset Generation
- Logos, banners, and social cards with Pillow
- HTML → retina PNG with Playwright
- Customizable colors and branding

## Quick Start

```bash
# Clone the repo
git clone https://github.com/Abdallah-Tah/social-media-kit.git
cd social-media-kit

# Install Python dependencies
pip install -r requirements.txt

# Install Node dependencies (for card rendering)
npm install

# Copy and fill in your API credentials
cp config/secrets.env.example config/secrets.env
nano config/secrets.env
```

## Workflow

### 1. Research a Topic

```bash
# Search for articles + extract content
python scripts/content_research.py "Laravel 13 new features" --count 5 --extract --save

# Search for tutorials
python scripts/content_research.py "Python asyncio tutorial 2026" --count 5 --save

# Search for news
python scripts/content_research.py "AI agents open source" --count 5 --extract --save
```

### 2. Process Into a Draft

```bash
# Generate a tutorial draft
python scripts/content_processor.py content/raw/2026-06-01_laravel-13-new-features.json --template tutorial --social

# Generate a news article
python scripts/content_processor.py content/raw/2026-06-01_ai-agents-open-source.json --template news --social

# Generate a comparison
python scripts/content_processor.py content/raw/2026-06-01_framework-comparison.json --template comparison
```

### 3. Edit & Publish

```bash
# Edit the draft in your editor
nano content/drafts/2026-06-01_laravel-13-new-features.md

# Publish everywhere (dry run first!)
python scripts/publish_all.py --file content/drafts/2026-06-01_laravel-13-new-features.md \
  --title "Laravel 13 Deep Dive" --dry-run

# Publish for real
python scripts/publish_all.py --file content/drafts/2026-06-01_laravel-13-new-features.md \
  --title "Laravel 13 Deep Dive"

# Publish to specific platforms only
python scripts/publish_all.py --file article.md --title "My Article" --blog --facebook
```

### 4. Generate Assets

```bash
# Logo + banner
python scripts/make_assets.py --logo --brand "B"
python scripts/make_assets.py --banner --name "MyBrand" --tagline "Tech • AI • Innovation"

# Social card from HTML template
node scripts/render_card.mjs card.html card.png 1080 1080
```

### Individual Platform Scripts

```bash
# Facebook
python scripts/fb_poster.py --message "Check this out!" --link "https://example.com"
python scripts/fb_poster.py --image photo.png --caption "My photo"

# X (Twitter)
python scripts/x_poster.py "Tweeting from the command line!"
python scripts/x_oauth_exchange.py --setup   # First-time OAuth setup

# LinkedIn
python scripts/linkedin_oauth.py              # First-time OAuth
python scripts/linkedin_poster.py "Sharing an update"

# Blog
python scripts/blog_publisher.py --title "My Article" --file article.md --category 3 --tags "2,5"
```

## Scripts

| Script | Purpose |
|--------|---------|
| `content_research.py` | Search web for articles/tutorials, extract content, save JSON |
| `content_processor.py` | Transform research into article drafts + social posts |
| `publish_all.py` | Publish to blog + all social platforms in one command |
| `fb_poster.py` | Post text, links, or photos to Facebook Page |
| `x_poster.py` | Post tweets via X API v2 |
| `x_oauth_exchange.py` | X OAuth 1.0a setup flow |
| `linkedin_oauth.py` | LinkedIn OAuth2 token generator |
| `linkedin_poster.py` | Post text updates to LinkedIn |
| `blog_publisher.py` | Push articles to blog via REST API |
| `make_assets.py` | Generate logos, banners, social cards |
| `convert_code_blocks.py` | Convert Markdown code blocks to HTML |
| `render_card.mjs` | Render HTML templates to retina PNG |

## Architecture

```
social-media-kit/
├── config/
│   ├── secrets.env.example    # API keys template (gitignored)
│   └── platforms.yaml         # Platform-specific settings
├── content/
│   ├── raw/                   # Research results (JSON)
│   ├── drafts/                # Article drafts (Markdown)
│   │   └── social/           # Social media post variants
│   └── assets/                # Generated logos, banners, cards
├── scripts/
│   ├── content_research.py   # Web search + extraction
│   ├── content_processor.py  # Research → drafts + social posts
│   ├── publish_all.py        # Multi-platform publisher
│   ├── fb_poster.py          # Facebook Page API
│   ├── x_poster.py           # X API v2
│   ├── x_oauth_exchange.py   # X OAuth setup
│   ├── linkedin_oauth.py     # LinkedIn OAuth2
│   ├── linkedin_poster.py    # LinkedIn API
│   ├── blog_publisher.py     # Blog REST API
│   ├── make_assets.py        # Asset generation (Pillow)
│   ├── convert_code_blocks.py # Markdown → HTML code blocks
│   └── render_card.mjs       # HTML → PNG (Playwright)
├── docs/
│   ├── PLATFORM_SETUP.md     # Platform API setup guides
│   └── API_REFERENCE.md      # Script usage docs
├── requirements.txt
├── package.json
├── .gitignore
├── LICENSE
└── README.md
```

## Security

- **Never commit `secrets.env`** — it's gitignored
- API tokens loaded from environment variables or `.env` files only
- OAuth tokens stored locally, never transmitted
- No browser session cookies or session hijacking

## License

MIT — use it, modify it, build on it.

---

Built by [Abdallah Mohamed](https://github.com/Abdallah-Tah) — running social media automation on a Raspberry Pi since 2026.