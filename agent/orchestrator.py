"""The orchestrator — the agentic loop that drives the whole routine.

Mirrors the Claude Code style: a model reasons, calls tools, observes
results, and repeats until it decides the goal is done. Provider-agnostic
(Claude / OpenAI / Ollama) via :class:`agent.llm.LLMClient`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import AgentConfig
from .llm import LLMClient, LLMError
from .prompts import build_system_prompt
from .tools import TOOL_SCHEMAS, ToolBox


@dataclass
class RunResult:
    summary: str = ""
    steps: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    transcript_text: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _journal_run(task_type: str, **kwargs):
    """Taco run-journal context. Journaling must never break the run:
    if agent_journal is unavailable, fall back to an inert record."""
    try:
        from agent_journal.journal import record_run
        return record_run(task_type, **kwargs)
    except Exception:
        import contextlib
        from types import SimpleNamespace

        @contextlib.contextmanager
        def _null():
            yield SimpleNamespace(
                model_used="", output_ref="", error=None, outcome=None,
                outcome_detail=None, tool_calls=[], run_id=None,
            )
        return _null()


# Tools whose dispatch counts as an outward-facing publish step.
def _is_publish_tool(name: str) -> bool:
    return name == "publish_blog" or name.startswith("post_")


def _publish_failed(output: str) -> bool:
    """Heuristic: tool outputs are strings; failures start with an error
    marker or report a missing configuration."""
    lowered = (output or "").strip().lower()
    return lowered.startswith(("error", "failed", "⚠")) or "not configured" in lowered


def _log_publish(name: str, tool_input: dict, output: str, config: AgentConfig) -> bool:
    """Journal one publish step; returns True when it looks successful."""
    failed = _publish_failed(output)
    with _journal_run(
        "publish",
        pillar=name,
        model_used=config.model,
        input_summary=("[dry-run] " if config.dry_run else "") + _short(tool_input, 300),
    ) as rec:
        rec.output_ref = (output or "")[:300]
        if failed:
            rec.error = (output or "")[:300]
        elif not config.dry_run:
            rec.outcome = "published"
    return not failed


def run_agent(
    goal: str,
    config: AgentConfig,
    profile: dict[str, Any],
    on_event: Callable[[str, str], None] | None = None,
) -> RunResult:
    """Run the full routine for ``goal``.

    ``on_event(kind, text)`` is called for streaming-style UI updates where
    ``kind`` is one of: 'thinking', 'tool', 'tool_result', 'final', 'error'.
    """
    with _journal_run(
        "generate",
        pillar=profile.get("name", ""),
        model_used=config.model,
        input_summary=goal[:300],
    ) as rec:
        result = _run_agent_impl(goal, config, profile, on_event, rec)
        rec.error = result.error or None
        rec.output_ref = (result.summary or "")[:300]
        rec.tool_calls = [
            {"name": tc["name"], "input": _short(tc.get("input", {}), 200)}
            for tc in result.tool_calls
        ]
        return result


def _run_agent_impl(
    goal: str,
    config: AgentConfig,
    profile: dict[str, Any],
    on_event: Callable[[str, str], None] | None,
    journal_rec,
) -> RunResult:
    emit = on_event or (lambda kind, text: None)

    try:
        client = LLMClient(
            provider=config.provider,
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
    except LLMError as exc:
        emit("error", str(exc))
        return RunResult(error=str(exc))

    toolbox = ToolBox(config, profile)
    system = build_system_prompt(profile, config)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "text", "text": goal}]}
    ]
    result = RunResult()

    for step in range(1, config.max_steps + 1):
        result.steps = step
        try:
            resp = client.complete(system, messages, tools=TOOL_SCHEMAS)
        except LLMError as exc:
            emit("error", str(exc))
            result.error = str(exc)
            return result

        # Record the assistant turn verbatim for the next request.
        messages.append({"role": "assistant", "content": resp.blocks})

        if resp.text:
            emit("thinking", resp.text)
            result.transcript_text.append(resp.text)

        tool_uses = resp.tool_uses
        if not tool_uses:
            # Model produced a final answer with no tool calls.
            result.summary = resp.text or "Done."
            emit("final", result.summary)
            return result

        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            name, tool_input, tu_id = tu["name"], tu.get("input", {}), tu.get("id", "")

            if name == "finish":
                result.summary = tool_input.get("summary", "Done.")
                result.tool_calls.append({"name": name, "input": tool_input})
                emit("final", result.summary)
                return result

            emit("tool", f"{name}({_short(tool_input)})")
            output = toolbox.dispatch(name, tool_input)
            if _is_publish_tool(name):
                # Journal each publish step; a successful live publish also
                # marks the whole generate run as published.
                if _log_publish(name, tool_input, output, config) and not config.dry_run:
                    journal_rec.outcome = "published"
            result.tool_calls.append(
                {"name": name, "input": tool_input, "result": output}
            )
            emit("tool_result", output)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": tu_id, "content": output}
            )

        messages.append({"role": "user", "content": tool_results})

    result.error = (
        f"Reached max steps ({config.max_steps}) without calling finish. "
        "Increase --max-steps or narrow the goal."
    )
    emit("error", result.error)
    return result


def _short(obj: Any, limit: int = 120) -> str:
    text = json.dumps(obj, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"
