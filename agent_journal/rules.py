"""The learned-rules file and PROMPT_VERSION management.

``config/taco_rules.md`` holds one delimited block per rule. Founding
rules (#0001 Verified-source, #0002 vendor-reported) are permanent and
can never be reverted. Applied proposals append new blocks; revert
removes exactly one block by proposal id.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from agent_journal.db import REPO_ROOT

# Founding rules are not proposal-backed and must never be removed.
FOUNDING_RULE_IDS = {1, 2}

_BLOCK_RE = re.compile(
    r"<!-- rule #(?P<rid>\d{4})(?: proposal=(?P<pid>\d+))? -->\n"
    r"(?P<body>.*?)\n"
    r"<!-- /rule #(?P=rid) -->",
    re.S,
)
_VERSION_RE = re.compile(r'^PROMPT_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', re.M)


def default_rules_path() -> str:
    return os.environ.get("TACO_RULES_FILE", str(REPO_ROOT / "config" / "taco_rules.md"))


def default_prompts_path() -> str:
    return str(REPO_ROOT / "agent" / "prompts.py")


def list_rules(path: str | None = None) -> list[dict]:
    """Return [{rule_id, proposal_id, body}] in file order."""
    p = Path(path or default_rules_path())
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    out = []
    for m in _BLOCK_RE.finditer(text):
        out.append({
            "rule_id": int(m.group("rid")),
            "proposal_id": int(m.group("pid")) if m.group("pid") else None,
            "body": m.group("body").strip(),
        })
    return out


def load_rules(path: str | None = None) -> str:
    """Rule bodies only (markers stripped) for system-prompt injection."""
    return "\n".join(f"- {r['body']}" for r in list_rules(path))


def add_rule(body: str, proposal_id: int, path: str | None = None) -> int:
    """Append a new rule block; returns the new rule id."""
    p = Path(path or default_rules_path())
    rules = list_rules(str(p))
    rule_id = max((r["rule_id"] for r in rules), default=0) + 1
    block = (
        f"\n<!-- rule #{rule_id:04d} proposal={proposal_id} -->\n"
        f"{body.strip()}\n"
        f"<!-- /rule #{rule_id:04d} -->\n"
    )
    existing = p.read_text(encoding="utf-8") if p.exists() else "# Taco — learned rules\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(existing.rstrip("\n") + "\n" + block, encoding="utf-8")
    return rule_id


def remove_rule_for_proposal(proposal_id: int, path: str | None = None) -> int:
    """Remove the rule block applied by ``proposal_id``; returns its rule id.

    Founding rules carry no proposal id, so they can never match here.
    Raises ``ValueError`` if no block references the proposal.
    """
    p = Path(path or default_rules_path())
    if not p.exists():
        raise ValueError(f"Rules file not found: {p}")
    text = p.read_text(encoding="utf-8")
    removed_id: int | None = None

    def _strip(m: re.Match) -> str:
        nonlocal removed_id
        if m.group("pid") and int(m.group("pid")) == proposal_id:
            rid = int(m.group("rid"))
            if rid in FOUNDING_RULE_IDS:
                raise ValueError(f"Rule #{rid:04d} is a founding rule and cannot be removed")
            removed_id = rid
            return ""
        return m.group(0)

    new_text = _BLOCK_RE.sub(_strip, text)
    if removed_id is None:
        raise ValueError(f"No applied rule found for proposal {proposal_id}")
    p.write_text(re.sub(r"\n{3,}", "\n\n", new_text), encoding="utf-8")
    return removed_id


def bump_prompt_version(prompts_path: str | None = None) -> str:
    """Bump the PROMPT_VERSION patch number in agent/prompts.py; return it."""
    p = Path(prompts_path or default_prompts_path())
    source = p.read_text(encoding="utf-8")
    m = _VERSION_RE.search(source)
    if not m:
        raise ValueError(f"PROMPT_VERSION constant not found in {p}")
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    new_version = f"{major}.{minor}.{patch + 1}"
    new_source = _VERSION_RE.sub(f'PROMPT_VERSION = "{new_version}"', source, count=1)
    p.write_text(new_source, encoding="utf-8")
    return new_version


def get_prompt_sections() -> set[str]:
    """Section headings (lowercased) of the rendered system prompt.

    Used to validate prompt_edit targets — approving an edit whose target
    section does not exist must fail loudly, not silently append.
    """
    from types import SimpleNamespace
    from agent.prompts import build_system_prompt  # deferred: avoids import cycle

    prompt = build_system_prompt(
        {"name": "probe", "platforms": ["blog"]},
        SimpleNamespace(dry_run=True),
    )
    return {
        line[3:].strip().lower()
        for line in prompt.splitlines()
        if line.startswith("## ")
    }


def git_commit(message: str, paths: list[str], repo_root: str | None = None) -> None:
    """Commit exactly ``paths`` with ``message``. Raises on git failure."""
    root = repo_root or str(REPO_ROOT)
    subprocess.run(["git", "-C", root, "add", "--"] + paths, check=True)
    subprocess.run(["git", "-C", root, "commit", "-m", message, "--"] + paths, check=True)
