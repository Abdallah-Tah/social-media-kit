# Using the Agent with OpenClaw (and Claude Code)

This kit is built so your existing agent can call it. It ships in the standard
**`SKILL.md`** format used by both [OpenClaw](https://github.com/openclaw/openclaw)
and Claude Code, plus a Python adapter for custom runtimes.

## 1. Declarative skill (recommended)

The skill lives at:

```
skills/social-media-agent/SKILL.md
```

OpenClaw discovers a skill wherever a `SKILL.md` appears under a configured
skills root. Two ways to wire it up:

**A. Point OpenClaw at this repo's skills folder**

Add the repo's `skills/` directory to your OpenClaw skills roots (see your
OpenClaw config), then restart the agent. It will appear as `social-media-agent`.

**B. Symlink/copy into your workspace skills folder**

```bash
ln -s /path/to/social-media-kit/skills/social-media-agent \
      ~/.openclaw/skills/social-media-agent
```

The skill's frontmatter declares what it needs:

```yaml
metadata:
  openclaw:
    requires:
      bins: ["python3"]
      env:  ["ANTHROPIC_API_KEY"]   # or switch the provider in agent.yaml
    primaryEnv: ANTHROPIC_API_KEY
    install:
      - id: pip
        kind: shell
        command: pip install -r {baseDir}/../../requirements.txt && pip install -e {baseDir}/../..
```

Once installed, your OpenClaw agent can satisfy requests like *"research and
publish a post about X"* by invoking the kit's `smkit` CLI and scripts, exactly
as documented in the skill body.

> The same `SKILL.md` works as a Claude Code skill — drop the repo under a
> Claude Code skills directory and invoke `/social-media-agent`.

## 2. Programmatic adapter (custom runtimes)

If you run a Python agent (the `openclaw-sdk`, LangChain, CrewAI, your own
loop), use `agent/openclaw_skill.py`:

```python
from agent.openclaw_skill import run_routine, make_tool_functions, tool_specs, register

# One-shot: run the whole routine and get a summary back
summary = run_routine(topic="Laravel 13 new features", profile="default", dry_run=True)

# Or expose each capability as an individual tool
tools = make_tool_functions(profile="default")     # {name: callable}
specs = tool_specs()                                # JSON-schema for each tool
result = tools["post_x"](text="Hello from my agent!")

# Best-effort registration onto an openclaw-sdk Agent (no-op if SDK differs)
# register(my_openclaw_agent, profile="default")
```

`make_tool_functions()` returns plain callables (keyword args matching each
tool's schema, string return), so they slot into any framework's tool registry.
`tool_specs()` gives you the matching JSON Schemas.

`register(agent, ...)` tries common registration hooks on an OpenClaw `Agent`
object and degrades gracefully if the SDK's shape differs across versions —
prefer the declarative skill if you want a stable contract.

## 3. Hermes / other agents

Because the integration surface is just **(a) a CLI**, **(b) standalone scripts**,
and **(c) plain Python callables with JSON schemas**, any agent that can run a
shell command or call a Python function can drive this kit — including Hermes
Agent or a bespoke orchestrator. Point it at `smkit run` for the full routine,
or wire individual `scripts/*_poster.py` for single actions.
