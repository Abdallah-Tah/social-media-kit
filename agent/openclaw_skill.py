"""OpenClaw integration adapter.

Two ways to use the Social Media Agent from an OpenClaw agent:

1. Declarative (recommended): the `skills/social-media-agent/SKILL.md` file
   is auto-discovered by OpenClaw when placed under a configured skills root.
   This needs no Python wiring at all.

2. Programmatic (this module): expose the kit's capabilities as plain Python
   callables so they can be registered as tools in a custom OpenClaw runtime
   or any other Python agent framework (LangChain, CrewAI, the openclaw-sdk).

The functions here are framework-neutral: they take simple arguments and
return strings. `register(agent)` opportunistically wires them into an
openclaw-sdk Agent *if* that SDK exposes a tool-registration hook, but it is
written defensively and degrades to a no-op rather than raising if the SDK
shape differs across versions.
"""
from __future__ import annotations

from typing import Any, Callable

from .config import AgentConfig, load_profile
from .orchestrator import run_agent
from .tools import TOOL_SCHEMAS, ToolBox


def _toolbox(profile: str = "default", dry_run: bool = False) -> ToolBox:
    config = AgentConfig.load(dry_run=dry_run)
    return ToolBox(config, load_profile(profile))


# ── High-level capability: run the whole routine ────────────────────────
def run_routine(
    topic: str | None = None,
    goal: str | None = None,
    profile: str = "default",
    dry_run: bool = False,
) -> str:
    """Research, write, and publish content end-to-end. Returns a summary."""
    from .prompts import build_goal

    config = AgentConfig.load(dry_run=dry_run, auto_confirm=True)
    prof = load_profile(profile)
    result = run_agent(build_goal(topic, goal, prof), config, prof)
    return result.summary if result.ok else f"ERROR: {result.error}"


# ── Low-level capabilities (one tool each) ──────────────────────────────
def make_tool_functions(profile: str = "default", dry_run: bool = False):
    """Return {name: callable} for each underlying tool, for tool registration.

    Each callable accepts keyword arguments matching that tool's input schema
    and returns a string result.
    """
    box = _toolbox(profile, dry_run)

    def _bind(name: str) -> Callable[..., str]:
        def _fn(**kwargs: Any) -> str:
            return box.dispatch(name, kwargs)

        _fn.__name__ = name
        schema = next((t for t in TOOL_SCHEMAS if t["name"] == name), {})
        _fn.__doc__ = schema.get("description", "")
        return _fn

    return {t["name"]: _bind(t["name"]) for t in TOOL_SCHEMAS if t["name"] != "finish"}


def tool_specs() -> list[dict]:
    """Return the JSON-schema tool specs (for frameworks that want them)."""
    return [t for t in TOOL_SCHEMAS if t["name"] != "finish"]


# ── Optional: register into an openclaw-sdk Agent if available ──────────
def register(agent: Any, profile: str = "default", dry_run: bool = False) -> bool:
    """Best-effort registration of tools onto an OpenClaw agent object.

    Returns True if anything was registered. Never raises on SDK mismatch.
    """
    fns = make_tool_functions(profile, dry_run)
    specs = {t["name"]: t for t in tool_specs()}

    # Try a few common registration method names across SDK versions.
    for method_name in ("register_tool", "add_tool", "tool", "register"):
        method = getattr(agent, method_name, None)
        if not callable(method):
            continue
        registered = 0
        for name, fn in fns.items():
            try:
                method(
                    name=name,
                    description=specs[name]["description"],
                    parameters=specs[name]["input_schema"],
                    func=fn,
                )
                registered += 1
            except TypeError:
                try:
                    method(fn)  # decorator-style fallback
                    registered += 1
                except Exception:
                    pass
            except Exception:
                pass
        if registered:
            return True
    return False
