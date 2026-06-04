# Gumroad Product Page — copy/paste

## Product title
Social Media Agent — the AI that writes & publishes your content on autopilot

## Tagline (subtitle)
Self-hosted. Runs on your own LLM (Claude, OpenAI, or cheap/free Ollama). It researches a topic, writes the article, designs a cover, and publishes native posts to 13 platforms — from one command or a web dashboard.

## Cover / thumbnail text ideas
- "Describe a topic. Get finished posts on 13 platforms."
- "An AI content agent — not another scheduler."

---

## Description (page body)

**Most "social media tools" still make you write everything. This one writes for you.**

Give it a topic — or an existing blog post — and it does the whole job: researches the web, writes a real article in your brand voice, generates a cover image, adapts a native post for each platform, and publishes everywhere. It's an autonomous content **agent**, not a calendar you have to feed.

### Why it's different
- ♻️ **Repurpose Studio** — drop in one article, transcript, or note and get native posts for every channel, in your voice. *Create once, distribute everywhere.* Schedulers can't do this.
- 🧠 **Your LLM, your infra** — Claude, OpenAI, **Ollama Cloud** (cheap, no big machine), or **local Ollama** (free/offline). Your keys, your data, no monthly tax.
- 🧬 **Learns your brand** — point it at your website and it writes a voice/audience profile for you.
- 🖥️ **Dashboard *and* CLI** — a browser control panel for the casual path, automation + a Claude Code / OpenClaw skill for power users.
- 🎭 **Multi-brand** — run it for unlimited clients, each with its own voice and channels.
- ✅ **Safe by default** — dry-run mode, per-channel allowlist, and dedupe so you never double-post.

### Publishes to 13 channels + anything
X · LinkedIn · Facebook · Bluesky · Threads · Mastodon · Reddit · Pinterest · Telegram · Slack · Discord · Blog (WordPress / Ghost / Laravel) — plus a generic webhook for everything else (Zapier, Make, n8n).

### What you get
- Full source — clean, documented, **40+ tests + CI**
- 13 publishers + generic webhook + cover-image generator
- Web dashboard, setup wizard, brand profiles, scheduling queue, Docker
- Setup docs + per-platform guides + a launch kit
- **14-day money-back guarantee**

### Requirements (be honest, it builds trust)
- Python 3.10+ (use a virtualenv)
- **One working LLM**: a Claude/OpenAI key, Ollama Cloud, or local Ollama with enough RAM. Note: dry-run skips *publishing*, not *writing* — it still calls your model.
- Optional: Node.js (image cards), Docker (self-hosted search)

### FAQ
**Is this a scheduler?** It can schedule, but the point is it *generates and publishes* for you.
**Do I need to pay for AI?** Bring a Claude/OpenAI key, use cheap Ollama Cloud, or run a local model free. You pay your own model costs — that's why there's no subscription.
**Do you store my data or keys?** No. It's self-hosted; keys live in a local file that's gitignored.
**Can I run it for clients?** Yes — unlimited brand profiles, each with its own voice and channels.
**Refunds?** 14 days, no questions asked.

---

## Pricing
- Launch / intro: **$29** (first buyers)
- After ~10–15 reviews: **$49–59**
- (Optional later) "Pro" tier: priority support + future premium adapters

## Checklist before you hit publish
- [ ] 30s demo GIF uploaded (run `bash scripts/demo.sh` while recording)
- [ ] 3 screenshots (dashboard, a dry-run run, a generated article)
- [ ] 14-day refund enabled in Gumroad settings
- [ ] Support contact (email or Discord) linked in the README and page
