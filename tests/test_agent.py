"""Core agent tests — no network required (providers/posters are mocked).

Run:  python -m pytest -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agent.config import AgentConfig, load_profile          # noqa: E402
from agent.llm import LLMClient, LLMResponse                 # noqa: E402
from agent.tools import ToolBox, TOOL_SCHEMAS                # noqa: E402
from agent import orchestrator, cli, install                # noqa: E402


def _cfg(**kw):
    c = AgentConfig.load(dry_run=kw.pop("dry_run", True))
    c.api_key = "test"
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# ── LLM provider abstraction ─────────────────────────────────────────────
def test_openai_message_conversion():
    neutral = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "web_search", "input": {"q": "x"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "results"}]},
    ]
    msgs = LLMClient._to_openai_messages("SYS", neutral)
    assert msgs[0]["role"] == "system"
    assert any(m["role"] == "tool" and m["tool_call_id"] == "t1" for m in msgs)
    assert any(m["role"] == "assistant" and m.get("tool_calls") for m in msgs)


def test_ollama_dict_args_and_reasoning_fallback():
    c = LLMClient(provider="ollama", model="m", api_key="")
    c._post = lambda url, headers, body: {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "content": "",
                "reasoning": "thinking...",
                "tool_calls": [{"id": None, "function": {
                    "name": "web_search", "arguments": {"query": "x"}}}],
            },
        }]
    }
    resp = c.complete("s", [{"role": "user", "content": [{"type": "text", "text": "go"}]}])
    assert resp.text == "thinking..."           # reasoning fallback
    tu = resp.tool_uses[0]
    assert tu["input"] == {"query": "x"}          # dict args pass through
    assert tu["id"]                                # synthesized id


def test_ollama_needs_no_key():
    c = LLMClient(provider="ollama", model="m", api_key="")
    assert c.base_url.endswith(":11434/v1")


def test_unknown_provider_raises():
    from agent.llm import LLMError
    with pytest.raises(LLMError):
        LLMClient(provider="nope", model="m", api_key="k")


# ── Config: base_url is scoped to the active provider ────────────────────
def test_base_url_not_shared_across_providers(monkeypatch):
    # An OpenAI base URL must never leak into an Anthropic run.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://anthropic.example")
    a = AgentConfig.load(provider="anthropic")
    assert a.base_url == "https://anthropic.example"
    assert "openai.example" not in (a.base_url or "")


def test_bwa_anthropic_key_alias_is_preferred(monkeypatch):
    monkeypatch.setenv("BWA_ANTHROPIC_API_KEY", "bwa-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "generic-key")
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)

    config = AgentConfig.load(provider="anthropic")

    assert config.api_key == "bwa-key"


# ── ToolBox: security + limits ───────────────────────────────────────────
def test_profile_allowlist_blocks_disabled_channels():
    prof = load_profile("default")
    prof["platforms"] = ["x"]                      # only X enabled
    box = ToolBox(_cfg(), prof)
    assert "not enabled" in box.dispatch("post_slack", {"text": "hi"})
    assert box.dispatch("post_x", {"text": "hi"}).startswith("[DRY RUN]")


def test_dry_run_gates_publishing():
    prof = load_profile("default")
    prof["platforms"] = ["x", "bluesky"]
    box = ToolBox(_cfg(dry_run=True), prof)
    assert box.dispatch("post_bluesky", {"text": "hi"}).startswith("[DRY RUN]")


@pytest.mark.parametrize("tool,text,limit", [
    ("post_x", "z" * 300, 280),
    ("post_bluesky", "z" * 301, 300),
    ("post_threads", "z" * 600, 500),
])
def test_char_limits_enforced_even_in_dry_run(tool, text, limit):
    prof = load_profile("default")
    prof["platforms"] = ["x", "bluesky", "threads"]
    box = ToolBox(_cfg(dry_run=True), prof)
    out = box.dispatch(tool, {"text": text})
    assert "ERROR" in out and str(limit) in out


def test_draft_path_sandboxed_to_drafts(tmp_path):
    prof = load_profile("default")
    box = ToolBox(_cfg(dry_run=False), prof)
    out = box.dispatch("publish_blog", {"title": "x", "draft_path": "/etc/passwd"})
    assert "must be inside" in out


def test_finish_dispatch_is_clean():
    box = ToolBox(_cfg(), load_profile("default"))
    assert box.dispatch("finish", {"summary": "done"}).startswith("FINISHED")


def test_unknown_tool_errors():
    box = ToolBox(_cfg(), load_profile("default"))
    assert "unknown tool" in box.dispatch("nope", {})


# ── Orchestrator loop (scripted model, dry-run) ──────────────────────────
def test_full_loop_runs_to_finish(monkeypatch):
    script = [
        [{"type": "tool_use", "id": "a", "name": "save_article",
          "input": {"title": "T", "markdown": "# T"}}],
        [{"type": "tool_use", "id": "b", "name": "finish",
          "input": {"summary": "done"}}],
    ]
    state = {"i": 0}

    class Fake(LLMClient):
        def complete(self, system, messages, tools=None):
            blocks = script[state["i"]]
            state["i"] += 1
            return LLMResponse(blocks=blocks, stop_reason="tool_use")

    monkeypatch.setattr(orchestrator, "LLMClient", Fake)
    prof = load_profile("default")
    res = orchestrator.run_agent("goal", _cfg(), prof)
    assert res.ok and res.summary == "done"
    assert any(c["name"] == "save_article" for c in res.tool_calls)


# ── doctor secret-health heuristic ───────────────────────────────────────
@pytest.mark.parametrize("value,flagged", [
    ("sk-abc…", True),          # ellipsis
    ("sk-abcdef...", True),     # trailing dots
    ("short", True),           # too short
    ("sk-a-perfectly-normal-length-key", False),
    ("", False),
])
def test_truncation_detector(value, flagged):
    assert (cli._looks_truncated(value) is not None) == flagged


# ── install_skill rejects a non-directory target ─────────────────────────
def test_install_skill_rejects_file(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    ok, msg = install.install_skill(skills_dir=str(f))
    assert not ok and "not a directory" in msg
