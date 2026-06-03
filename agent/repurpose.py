"""Repurpose Studio — turn ONE existing piece into native posts everywhere.

`smkit repurpose <url|file>` reads an existing article, blog post, transcript,
or note and rewrites it into platform-native posts for every channel in the
active profile — in your brand voice. This is the "create once, distribute
everywhere" workflow that schedulers (Postiz/Mixpost) don't do: they schedule
what you already wrote; this *generates* the posts from your source.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .config import ROOT, AgentConfig
from .orchestrator import run_agent
from .prompts import build_repurpose_goal

sys.path.insert(0, str(ROOT / "scripts"))


def load_source(source: str) -> tuple[str, str]:
    """Return (text, human_ref) for a URL or local file path."""
    p = Path(source)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8", errors="ignore"), p.name
    if source.startswith(("http://", "https://")):
        import content_research

        text = content_research.extract_article(source, max_chars=8000)
        return text, source
    raise ValueError(f"Source not found: {source} (pass a URL or an existing file path)")


def repurpose(source, config: AgentConfig, profile: dict, on_event=None):
    """Read a source and run the agent in repurpose mode. Returns RunResult."""
    text, ref = load_source(source)
    if not text or text.startswith("[Extraction failed"):
        raise ValueError(f"Could not read source: {text[:120]}")
    goal = build_repurpose_goal(text, ref, profile)
    return run_agent(goal, config, profile, on_event=on_event)
