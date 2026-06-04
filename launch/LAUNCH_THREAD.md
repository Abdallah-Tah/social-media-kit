# Launch Thread — X / Twitter (build-in-public)

> Post as a thread. Tweet 1 is the hook (this is what gets reshared — make it count).
> Add the 30s demo GIF to tweet 3 or 7. Pin the thread after posting.

---

**1/**
I got tired of "social media tools" that still make me write every post.

So I built an AI agent that does the whole job: it researches a topic, writes the article, designs a cover, and publishes native posts to 13 platforms.

On my own LLM. Self-hosted. Here's how 🧵

---

**2/**
Every "scheduler" (Buffer, Postiz, Hypefury…) has the same gap:

YOU still have to write the content. They just queue what you already made.

I wanted the opposite — describe a topic, get finished posts everywhere. An *agent*, not a calendar.

---

**3/**
What it actually does, end to end:

→ Researches the web (reads real sources)
→ Writes a full article in your brand voice
→ Generates a cover image
→ Adapts a native post per platform (length, tone, hashtags)
→ Publishes everywhere

One command. Or a dashboard if you'd rather click.

[ DEMO GIF HERE ]

---

**4/**
The 13 channels it posts to:

X · LinkedIn · Facebook · Bluesky · Threads · Mastodon · Reddit · Pinterest · Telegram · Slack · Discord · your Blog (WordPress / Ghost / Laravel)

+ a generic webhook for anything else (Zapier, Make, n8n).

---

**5/**
The feature I'm proudest of — Repurpose Studio:

Drop in ONE thing you already have (a blog post, a YouTube transcript, your notes) and it rewrites it into native posts for every channel, in your voice.

Create once → distribute everywhere. Schedulers literally can't do this.

---

**6/**
It runs on YOUR brain of choice:

• Claude or OpenAI (bring a key)
• Ollama Cloud (cheap, no big machine)
• Local Ollama (free/offline if you've got the RAM)

Your keys. Your data. No monthly SaaS tax. Self-hosted.

---

**7/**
Two more things devs seem to like:

🧬 `smkit learn yoursite.com` → reads your site and writes a brand-voice profile for you.
🤖 Installs as a skill inside Claude Code / OpenClaw, so your agent can post for you.

---

**8/**
Built it properly, not a weekend hack:

✓ 40+ tests + CI
✓ Docker
✓ dry-run mode (rehearse, publish nothing)
✓ per-channel allowlist + dedupe (never double-post)
✓ multi-brand profiles (run it for clients)

---

**9/**
Why niche, not "the next Buffer"?

Because a focused tool for people who hate writing posts beats a generic dashboard. Lower acquisition cost, higher retention, people actually pay.

I'm building this in public — follow along, tell me what to add.

---

**10/**
It's live today. Intro price for early folks, source included, 14-day refund.

Grab it 👇
[ GUMROAD LINK ]

What platform should it post to next? Reply and I'll build it.

---

## Notes
- Honesty: it needs a working LLM (a key, Ollama Cloud, or local Ollama with enough RAM). Don't claim "no key needed" — dry-run still uses the model to write.
- Best meta-move: generate your NEXT thread with the tool itself and say so.
