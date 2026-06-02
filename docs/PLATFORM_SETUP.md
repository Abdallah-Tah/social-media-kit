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