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

## SearXNG engine suspension (the failure that broke the news lane)

A SearXNG instance answers **HTTP 200 with an empty `results` array** when its
upstream engines refuse it. That reads identically to "nothing was written about
this", and on 2026-07-31 it silently produced two days of ungrounded articles —
14 failed searches per run, one of which was written up from a 250-character
press release.

Check the array that actually tells you:

```bash
curl -s "http://localhost:8888/search?q=test&format=json" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['unresponsive_engines'])"
```

`[["brave","Suspended: too many requests"],["duckduckgo","CAPTCHA"]]` means the
engines are blocked, not that the web is empty. A server making ~70 queries a
day gets there quickly.

The kit pins its own engine list rather than trusting the instance default:

```
SEARXNG_ENGINES=yahoo,bing,mojeek     # the shipped default
```

Order matters more than count. On developer queries Bing and Mojeek return the
brand match — "Next.js security patch" gives the Next plc clothing site — while
Yahoo returns `nextjs.org/blog/CVE-…`. If these get blocked in turn, swap in
others and re-check `unresponsive_engines`.

## Adding a Brave API key securely

Brave is first in the chain and the most reliable for technical queries. The
free tier is 2,000 queries/month; the news lane at 2×/day uses roughly 28/day.

**1. Get the key** — sign up at <https://brave.com/search/api/>, choose the free
"Data for Search" plan, copy the subscription token.

**2. Write it to the secrets file, without it entering your shell history.**
`config/secrets.env` is already gitignored (`.gitignore:2`), untracked, and mode
`600`. Append with a leading space so bash omits the line from history, or use
`read` so the key is never in the command at all:

```bash
cd ~/social-media-kit
read -rs -p "Brave API key: " BRAVE && printf 'BRAVE_API_KEY=%s\n' "$BRAVE" >> config/secrets.env && unset BRAVE
chmod 600 config/secrets.env
```

`read -rs` keeps it off the screen and out of `~/.bash_history`, because the key
is never a command argument.

**3. Verify it loads and works** — note this prints only a length, never the key:

```bash
/usr/bin/python3 -c "
import sys; sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
from agent.config import load_env; load_env()
import os, content_research as CR
print('key length:', len(os.environ.get('BRAVE_API_KEY','')))
print([r['url'] for r in CR._search_brave('kubernetes 1.36 release notes', 3)])
"
```

**4. Restart the dashboard** so the long-running scheduler picks it up. Cron
lanes spawn a fresh interpreter per run and need nothing:

```bash
systemctl --user restart smkit-dashboard.service
```

### What must never happen

- **Never put the key in the systemd unit.** `~/.config/systemd/user/smkit-dashboard.service`
  is plain text and `systemctl --user show smkit-dashboard.service` prints every
  `Environment=` line to anyone who can read the session — including into
  journald. The unit sets only `SMKIT_ENV` and `SMKIT_NOTIFICATIONS_ENABLED`;
  keep credentials in `config/secrets.env`, which `agent.config.load_env()`
  reads at startup.
- **Never `echo`/`print` the key.** `scripts/*.py` log provider *names* and
  result counts, never credentials. Keep it that way — cron output is appended
  to `~/logs/*.log` in the clear and is not rotated aggressively.
- **Never `export BRAVE_API_KEY=…` in a shell you use for git.** It leaks into
  `~/.bash_history` and into any subprocess, including hooks.
- **Confirm it is not staged**, before every commit that touches config:

  ```bash
  git check-ignore -v config/secrets.env   # must print the .gitignore rule
  git diff --cached --name-only | grep -i secret   # must print nothing
  ```

- If a key is ever committed, treat it as burned: **revoke it in the Brave
  dashboard first**, then rewrite history. Rotating is cheap; the free tier
  lets you regenerate.

## Hosting notes

- SearXNG is stateless — run it anywhere (a $5 VPS, a Pi, the same box as the
  agent). Point `SEARXNG_URL` at it.
- Public SearXNG instances exist, but many disable the JSON API or rate-limit
  bots. Self-hosting is the reliable path.
- Keep `limiter: false` for local single-user use; enable it if you expose the
  instance publicly.
