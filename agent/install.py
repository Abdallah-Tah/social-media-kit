"""Install the kit as a permanent, auto-discovered OpenClaw / Claude Code skill.

OpenClaw discovers a skill wherever a ``SKILL.md`` appears under a configured
skills root. This module finds (or is told) that root and links our skill into
it, so the host agent uses the Social Media Agent on every relevant request —
permanently, across sessions — without re-wiring anything.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import ROOT

SKILL_SRC = ROOT / "skills" / "social-media-agent"
SKILL_NAME = "social-media-agent"

# Where different agents look for skills, in priority order. The first whose
# *parent* already exists is used (we create the trailing `skills/` if needed).
def _candidate_roots() -> list[Path]:
    home = Path.home()
    roots: list[Path] = []
    # Explicit override wins.
    for env in ("OPENCLAW_SKILLS_DIR", "SKILLS_DIR"):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]).expanduser())
    if os.environ.get("OPENCLAW_HOME"):
        roots.append(Path(os.environ["OPENCLAW_HOME"]).expanduser() / "skills")
    roots += [
        home / ".openclaw" / "skills",
        home / ".config" / "openclaw" / "skills",
        home / "openclaw" / "skills",
        home / ".claude" / "skills",          # Claude Code
    ]
    return roots


def detect_skills_dir() -> Path | None:
    """Return the best existing skills root, or None if none is present."""
    for root in _candidate_roots():
        # Use it if the skills dir itself exists, or its parent does.
        if root.exists() or root.parent.exists():
            return root
    return None


def install_skill(
    skills_dir: str | None = None, copy: bool = False, force: bool = False
) -> tuple[bool, str]:
    """Link (or copy) the skill into a skills root.

    Returns (ok, message).
    """
    if not SKILL_SRC.exists():
        return False, f"Skill source not found at {SKILL_SRC}."

    target_root = (
        Path(skills_dir).expanduser() if skills_dir else detect_skills_dir()
    )
    if target_root is None:
        return False, (
            "Could not find an OpenClaw skills directory. Pass one explicitly:\n"
            "  smkit install-skill --skills-dir ~/.openclaw/skills"
        )

    # Fail cleanly if the target (or a parent) exists but isn't a directory,
    # instead of letting mkdir raise an uncaught OSError.
    if target_root.exists() and not target_root.is_dir():
        return False, f"{target_root} exists but is not a directory."
    try:
        target_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"Could not create skills directory {target_root}: {exc}"
    dest = target_root / SKILL_NAME

    # Handle an existing destination.
    if dest.is_symlink() or dest.exists():
        already = dest.is_symlink() and dest.resolve() == SKILL_SRC.resolve()
        if already and not copy:
            return True, f"Already installed → {dest} -> {SKILL_SRC}"
        if not force:
            return False, (
                f"{dest} already exists. Re-run with --force to replace it."
            )
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        else:
            shutil.rmtree(dest)

    if copy:
        shutil.copytree(SKILL_SRC, dest)
        how = "Copied"
    else:
        try:
            dest.symlink_to(SKILL_SRC, target_is_directory=True)
            how = "Linked"
        except OSError:
            # Filesystems without symlink support (some Windows setups).
            shutil.copytree(SKILL_SRC, dest)
            how = "Copied (symlink unsupported)"

    return True, f"{how} skill → {dest}\n   source: {SKILL_SRC}"
