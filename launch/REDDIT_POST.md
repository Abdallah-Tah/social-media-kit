# Reddit Post

> Reddit hates ads and loves honesty. Lead with the build, not the sale. Put the
> link in a comment or at the very bottom. Pick ONE subreddit per day, read its
> rules first. Good fits: r/SideProject, r/IndieHackers, r/ClaudeAI, r/selfhosted,
> r/SaaS (Show-off threads), r/Python.

---

## Version A — r/SideProject / r/IndieHackers

**Title:** I built an AI agent that researches, writes, and posts to 13 platforms — self-hosted, runs on your own LLM

**Body:**

I got tired of social tools that still make you write every post, so I built the opposite: an agent you give a topic to, and it researches the web, writes an article in your brand voice, makes a cover image, and publishes native posts to X, LinkedIn, Bluesky, Threads, Reddit, Mastodon, your blog, and more.

The part I think is actually novel: a **repurpose** mode — drop in one existing blog post or transcript and it turns it into native posts for every channel. Schedulers make you write first; this generates from your source.

Some details for the curious:
- Runs on Claude, OpenAI, or Ollama (local/free or cheap cloud) — your keys, self-hosted, no subscription.
- CLI + a small web dashboard + installs as a Claude Code skill.
- Dry-run mode, per-channel allowlist, dedupe, multi-brand profiles. 40+ tests, Docker.

Honest limitations: it needs a working LLM (dry-run still calls the model to write), and it's text + image — no video platforms (YouTube/TikTok) on purpose.

Happy to answer anything about the architecture (it's a tool-using agent loop over a provider-agnostic LLM layer). What would you want it to post to next?

(Link in the comments to respect the no-spam rule.)

---

## Version B — r/ClaudeAI / r/selfhosted (more technical)

**Title:** Self-hosted content agent that plugs into Claude Code and posts to 13 platforms (research → write → cover → publish)

**Body:**

Built a provider-agnostic agent (Claude / OpenAI / Ollama) that runs the full content loop as a tool-using agent: web research → article → cover image → per-platform native posts → publish. Self-hosted, your keys, no SaaS.

It installs as a **Claude Code / OpenClaw skill**, so your agent can publish for you, and there's a stdlib web dashboard (zero extra deps) if you want a UI. Channels: X, LinkedIn, Facebook, Bluesky, Threads, Mastodon, Reddit, Pinterest, Telegram, Slack, Discord, Blog (WordPress/Ghost/Laravel) + webhook.

Newest piece is a "repurpose" command: one source URL/file → native posts everywhere, no fresh research.

Stack is deliberately boring: stdlib + requests + PyYAML + Pillow, plain HTTP to every LLM (no SDKs), 40+ tests + CI, Docker. Honest caveat: it needs a real LLM (dry-run skips publishing, not generation), and it's text/image only — no video.

Would love feedback from people self-hosting their own automation. Link below.
