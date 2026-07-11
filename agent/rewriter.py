"""AI-powered draft rewriting via the configured LLM provider."""
from __future__ import annotations

from .config import AgentConfig
from .llm import LLMClient

REWRITE_MODES: dict[str, str] = {
    "shorter": (
        "You are an expert editor. Rewrite the following markdown blog draft to be about "
        "30% shorter. Preserve all key information, code examples, and technical accuracy. "
        "Cut repetition, tighten prose, eliminate filler. Return ONLY the rewritten "
        "markdown — no preamble or explanation."
    ),
    "hook": (
        "You are an expert copywriter. Rewrite only the opening of the following markdown "
        "blog draft (the first 2-3 paragraphs or H2 section) to be a more compelling hook "
        "that creates immediate curiosity and makes the reader feel they must continue. "
        "Keep the rest of the draft unchanged. Return ONLY the full rewritten markdown body."
    ),
    "technical": (
        "You are a senior software engineer and technical writer. Rewrite the following "
        "markdown blog draft to be more technical and precise. Use specific terminology, "
        "add concrete implementation detail where the current text is vague, and reference "
        "real tools, APIs, and patterns by name. Return ONLY the rewritten markdown body."
    ),
    "casual": (
        "You are a developer educator known for approachable, conversational writing. "
        "Rewrite the following markdown blog draft in a casual, friendly tone — like "
        "explaining to a developer colleague. Use shorter sentences, contractions, and "
        "simpler language. Keep the same information. Return ONLY the rewritten markdown body."
    ),
}


def rewrite_draft(draft_id: str, mode: str) -> dict:
    """Rewrite a draft body with the configured LLM. Returns {ok, body, error}."""
    from .drafts import load_draft
    from .config import AgentConfig

    if mode not in REWRITE_MODES:
        return {"ok": False, "error": f"unknown mode '{mode}'. Valid: {', '.join(REWRITE_MODES)}"}

    from .drafts import load_draft
    draft = load_draft(draft_id)
    if draft is None:
        return {"ok": False, "error": "draft not found"}
    if not draft.body.strip():
        return {"ok": False, "error": "draft has no body to rewrite"}

    try:
        config = AgentConfig.load(dry_run=True)
        client = LLMClient(
            provider=config.provider,
            model=config.model,
            api_key=config.api_key,
            max_tokens=4096,
            temperature=0.4,
        )
        response = client.complete(
            system=REWRITE_MODES[mode],
            messages=[{"role": "user", "content": [{"type": "text", "text": draft.body}]}],
        )
        rewritten = response.text
        if not rewritten:
            return {"ok": False, "error": "LLM returned empty response"}
        return {"ok": True, "body": rewritten, "mode": mode}
    except Exception as exc:
        return {"ok": False, "error": f"Rewrite failed: {exc}"}
