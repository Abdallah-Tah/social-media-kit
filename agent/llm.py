"""Provider-agnostic LLM client with tool-calling support.

Speaks to three backends over plain HTTP (no SDK dependency):

* ``anthropic`` — the Claude Messages API
* ``openai``    — any OpenAI-compatible Chat Completions endpoint
                  (OpenAI, OpenRouter, Together, local servers, …)
* ``ollama``    — a local Ollama server (OpenAI-compatible at /v1),
                  so buyers can run the agent fully offline with no API key

The rest of the agent works in a single neutral message format (modeled
on Anthropic's content-block shape). This module converts to/from each
provider's wire format so the orchestrator never has to care which brain
is driving.

Neutral message shape
----------------------
    {"role": "user" | "assistant", "content": [block, ...]}

    block =
        {"type": "text", "text": str}
      | {"type": "tool_use", "id": str, "name": str, "input": dict}
      | {"type": "tool_result", "tool_use_id": str, "content": str}
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import requests


class LLMError(RuntimeError):
    """Raised when the provider returns an unrecoverable error."""


@dataclass
class LLMResponse:
    """Normalized response: neutral content blocks + helpers."""

    blocks: list[dict[str, Any]]
    stop_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.blocks if b.get("type") == "tool_use"]

    @property
    def text(self) -> str:
        return "".join(
            b["text"] for b in self.blocks if b.get("type") == "text"
        ).strip()


class LLMClient:
    """A thin, retrying HTTP client that abstracts over Claude / OpenAI."""

    ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.4,
        timeout: int = 120,
        max_retries: int = 4,
    ) -> None:
        self.provider = provider.lower().strip()
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries

        if self.provider not in ("anthropic", "openai", "ollama"):
            raise LLMError(
                f"Unknown provider '{provider}'. "
                "Use 'anthropic', 'openai', or 'ollama'."
            )

        # Ollama is a local OpenAI-compatible server that needs no API key.
        if self.provider == "ollama":
            self.base_url = (base_url or "http://localhost:11434/v1").rstrip("/")
            self.api_key = api_key or "ollama"  # placeholder; not validated
        else:
            self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
            self.api_key = api_key
            if not self.api_key:
                raise LLMError(
                    f"No API key set for provider '{self.provider}'. "
                    "Run `smkit wizard` or set the key in config/secrets.env."
                )

    # ── Public API ──────────────────────────────────────────────────────
    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send one turn and return a normalized response."""
        if self.provider == "anthropic":
            return self._complete_anthropic(system, messages, tools or [])
        # openai + ollama share the Chat Completions wire format.
        return self._complete_openai(system, messages, tools or [])

    # ── Anthropic ───────────────────────────────────────────────────────
    def _complete_anthropic(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": messages,  # already neutral == anthropic shape
        }
        if tools:
            body["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["input_schema"],
                }
                for t in tools
            ]
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        data = self._post(self.ANTHROPIC_URL, headers, body)
        blocks = data.get("content", [])
        # Anthropic blocks are already in our neutral shape.
        return LLMResponse(
            blocks=blocks, stop_reason=data.get("stop_reason", ""), raw=data
        )

    # ── OpenAI-compatible ───────────────────────────────────────────────
    def _complete_openai(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": self._to_openai_messages(system, messages),
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = self._post(f"{self.base_url}/chat/completions", headers, body)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        blocks: list[dict[str, Any]] = []

        # Some "thinking" models (and Ollama cloud) leave `content` empty and
        # put their prose in a `reasoning` / `reasoning_content` field. Fall
        # back to it so the orchestrator never sees a totally empty turn.
        text = msg.get("content") or msg.get("reasoning") or msg.get(
            "reasoning_content"
        )
        if text:
            blocks.append({"type": "text", "text": text})

        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments")
            # OpenAI sends a JSON *string*; Ollama often sends a JSON *object*.
            if isinstance(raw_args, dict):
                args = raw_args
            elif isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args or "{}")
                except json.JSONDecodeError:
                    args = {}
            else:
                args = {}
            blocks.append(
                {
                    "type": "tool_use",
                    "id": tc.get("id") or f"call_{len(blocks)}",
                    "name": fn.get("name", ""),
                    "input": args,
                }
            )
        return LLMResponse(
            blocks=blocks, stop_reason=choice.get("finish_reason", ""), raw=data
        )

    @staticmethod
    def _to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
        """Convert neutral (Anthropic-style) messages to OpenAI chat shape."""
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if isinstance(content, str):
                out.append({"role": role, "content": content})
                continue

            text_parts: list[str] = []
            tool_calls: list[dict] = []
            tool_results: list[dict] = []
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block["text"])
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        }
                    )
                elif btype == "tool_result":
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": str(block.get("content", "")),
                        }
                    )

            if role == "assistant":
                entry: dict[str, Any] = {"role": "assistant"}
                entry["content"] = "\n".join(text_parts) if text_parts else None
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                out.append(entry)
            else:  # user
                if text_parts:
                    out.append(
                        {"role": "user", "content": "\n".join(text_parts)}
                    )
                # Tool results must follow the assistant call that requested
                # them; emit each as its own `tool` message.
                out.extend(tool_results)
        return out

    # ── HTTP with backoff ───────────────────────────────────────────────
    def _post(self, url: str, headers: dict, body: dict) -> dict:
        last_err = ""
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    url, headers=headers, json=body, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_err = f"network error: {exc}"
            else:
                if resp.status_code == 200:
                    return resp.json()
                # Retry on rate limit / transient server errors.
                if resp.status_code in (429, 500, 502, 503, 529):
                    last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                else:
                    raise LLMError(
                        f"{self.provider} API error "
                        f"(HTTP {resp.status_code}): {resp.text[:500]}"
                    )
            sleep = 2 ** attempt
            time.sleep(sleep)
        raise LLMError(
            f"{self.provider} request failed after {self.max_retries} "
            f"retries. Last error: {last_err}"
        )
