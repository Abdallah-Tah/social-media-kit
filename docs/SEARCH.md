# Free, self-hosted web search (SearXNG)

The agent's search chain is **Brave → SearXNG → DuckDuckGo → Wikipedia**. The
best *free, no-per-call-key* option for real web results is a self-hosted
**SearXNG** instance. It takes ~2 minutes with Docker.

## 1. Start SearXNG

From the repo root:

```bash
cd deploy/searxng
# Set a real secret key (any random string)
sed -i "s/change-me-please/$(openssl rand -hex 16)/" searxng/settings.yml
docker compose up -d
```

This runs SearXNG at <http://localhost:8888> with the **JSON API enabled**
(required by the agent).

## 2. Point the agent at it

In `config/secrets.env`:

```
SEARXNG_URL=http://localhost:8888
```

Optionally force it (skip the other providers):

```
SEARCH_PROVIDER=searxng
```

## 3. Verify

```bash
# Raw JSON from SearXNG
curl -s "http://localhost:8888/search?q=laravel+13&format=json" | head -c 300

# Through the kit
python3 -c "import sys; sys.path.insert(0,'scripts'); import content_research as c; \
print([r['url'] for r in c.web_search('laravel 13 features', 3)])"
```

You should see real article URLs (laravel.com, dev.to, etc.) instead of the
Wikipedia fallback.

## Provider comparison

| Provider | Cost | Key | Quality | Notes |
|----------|------|-----|---------|-------|
| Brave | free tier | `BRAVE_API_KEY` | ★★★★ | Best plug-and-play; sign up at brave.com/search/api |
| **SearXNG** | **free** | **none** | ★★★★ | Self-host (this guide) or use any instance via `SEARXNG_URL` |
| DuckDuckGo | free | none | ★★★ | Zero-config but can be rate-limited |
| Wikipedia | free | none | ★★ | Always works; encyclopedic only — best as a fallback |

## Hosting notes

- SearXNG is stateless — run it anywhere (a $5 VPS, a Pi, the same box as the
  agent). Point `SEARXNG_URL` at it.
- Public SearXNG instances exist, but many disable the JSON API or rate-limit
  bots. Self-hosting is the reliable path.
- Keep `limiter: false` for local single-user use; enable it if you expose the
  instance publicly.
