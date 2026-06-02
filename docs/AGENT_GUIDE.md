# Agent Guide

How the Social Media Agent works, and how to drive it.

## The routine

Every run executes the same disciplined loop — the agent decides each step,
the way Claude Code reasons and calls tools:

1. **Research** — `web_search` for 3-6 strong sources, `fetch_url` on the best.
2. **Write** — a full article in Markdown (not a template), grounded in those
   sources, with a Sources section. Saved via `save_article`.
3. **Adapt** — a *native* post per platform (X ≤ 280 chars, LinkedIn/Facebook
   a few paragraphs + CTA, Slack/Discord/Telegram concise, Mastodon ≤ 500).
4. **Publish** — calls the posting tool for each enabled channel + the blog.
5. **Report** — `finish` with a summary of what shipped and what was skipped.

The loop is bounded by `max_steps` (default 20) as a safety stop.

## Architecture (Claude Code-style)

```
agent/
├── cli.py            # smkit entrypoint (run / queue / wizard / doctor / profiles)
├── orchestrator.py   # the agentic tool-use loop
├── llm.py            # provider-agnostic LLM client (anthropic / openai / ollama)
├── tools.py          # tool schemas + dispatch → scripts/ (the "hands")
├── prompts.py        # routine + brand profile → system prompt
├── config.py         # secrets loader, agent.yaml, brand profiles
├── wizard.py         # interactive setup
└── openclaw_skill.py # OpenClaw / framework adapter
scripts/              # the actual platform integrations (importable + standalone)
skills/social-media-agent/SKILL.md  # OpenClaw + Claude Code skill manifest
```

The model never talks to a platform directly. It emits a **tool call**; the
`ToolBox` dispatches it to the matching script and feeds the result back. This
is exactly the tool-use loop Claude Code uses.

## Choosing a provider

`config/agent.yaml`:

```yaml
provider: anthropic   # anthropic | openai | ollama
anthropic: { model: claude-sonnet-4-6 }
openai:    { model: gpt-4o, base_url: https://api.openai.com/v1 }
ollama:    { model: llama3.1, base_url: http://localhost:11434/v1 }
```

Override per-run: `--provider ollama --model qwen2.5`.

- **anthropic** needs `ANTHROPIC_API_KEY`. Use `claude-opus-4-8` for the best
  writing, `claude-sonnet-4-6` for speed/cost.
- **openai** needs `OPENAI_API_KEY`; point `base_url` at OpenRouter or any
  compatible endpoint to use other models.
- **ollama** needs nothing — it runs locally. Use a model that supports tool
  calling (e.g. `llama3.1`, `qwen2.5`, `mistral-nemo`).

## Brand profiles

A profile is the agent's voice + guardrails. `platforms` is an allowlist — the
agent will not post anywhere it doesn't list. Run multiple brands by passing
`--profile <name>`.

## Dry-run vs live

- `--dry-run` simulates every publish/post (and still enforces hard limits like
  the 280-char tweet cap), so you can preview a full run safely.
- Live runs prompt for confirmation unless you pass `--yes`.
- Set `dry_run: true` in `agent.yaml` to make dry-run the default everywhere.

## Scheduling

1. Add topics (one per line) to `config/topics.txt`.
2. `smkit queue config/topics.txt --yes` runs the next topic and, on success,
   moves it to `config/topics.txt.done`.
3. Automate with cron:
   ```cron
   0 9 * * 1-5  cd /path/to/social-media-kit && smkit queue config/topics.txt --yes >> run.log 2>&1
   ```
4. Or use the included GitHub Action (`.github/workflows/scheduled-run.yml`) —
   put your keys in repo Secrets. It dry-runs by default; set the repo variable
   `GO_LIVE=1` (or trigger manually with dry-run off) to publish for real.

## Costs & safety

- One run ≈ a handful of model calls + a few HTTP requests. Local Ollama is free.
- The agent never fabricates facts — it grounds claims in fetched sources.
- If a channel isn't configured, it's skipped and noted, not failed.
- Nothing is committed or pushed by the agent itself except the topic queue in
  the scheduled workflow.
