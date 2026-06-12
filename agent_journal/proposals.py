"""The human gate. Proposals are NEVER auto-applied.

Hard rule, enforced in code at insert time *and* approve time: reflection
output can never modify the gate itself, the journal schema, the source
verification rules (Verified-source / vendor-reported), or its own rubric.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from agent_journal import rules as rules_mod

PROPOSAL_TYPES = ("prompt_edit", "rule_add", "config_change", "code_change")

# Self-protection: any proposal whose target mentions one of these is
# blocked outright. Substring match, case-insensitive — errs on the side
# of blocking; a wrongly blocked change can always be made by a human.
BLOCKED_TARGET_PATTERNS = (
    "agent_journal",        # the whole loop: journal, gate, reflection
    "proposal",             # the gate / proposals table
    "journal",              # journal module or schema
    "agent_runs",           # journal schema
    "rubric",               # the reflection rubric
    "reflect",              # reflection pass
    "verified-source",      # founding verification rule #0001
    "vendor-reported",      # founding verification rule #0002
    "verification",         # verification rules generally
    "taco_rules",           # the rules file itself
)


def is_blocked_target(target: str) -> bool:
    t = (target or "").lower()
    return any(pattern in t for pattern in BLOCKED_TARGET_PATTERNS)


def insert_proposal(
    conn: sqlite3.Connection,
    item: dict[str, Any],
    source_run_ids: list[int],
) -> int:
    """Insert a validated reflection proposal; self-targeting ones arrive blocked."""
    status = "blocked" if is_blocked_target(item.get("target", "")) else "pending"
    cur = conn.execute(
        """INSERT INTO proposals
           (source_run_ids, type, target, change, evidence, expected_effect, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            json.dumps(source_run_ids),
            item["type"],
            item.get("target", ""),
            item.get("change", ""),
            json.dumps(item.get("evidence_run_ids", [])),
            item.get("expected_effect", ""),
            status,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_proposal(conn: sqlite3.Connection, proposal_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError(f"Proposal {proposal_id} not found")
    return dict(row)


def list_proposals(conn: sqlite3.Connection, status: str | None = None) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            "SELECT * FROM proposals WHERE status = ? ORDER BY id", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM proposals ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def reject_proposal(conn: sqlite3.Connection, proposal_id: int, note: str | None = None) -> None:
    prop = get_proposal(conn, proposal_id)
    if prop["status"] not in ("pending", "blocked"):
        raise ValueError(f"Proposal {proposal_id} is '{prop['status']}', cannot reject")
    conn.execute(
        "UPDATE proposals SET status = 'rejected', decided_at = datetime('now'), "
        "decision_note = ? WHERE id = ?",
        (note, proposal_id),
    )
    conn.commit()


def approve_proposal(
    conn: sqlite3.Connection,
    proposal_id: int,
    *,
    rules_path: str | None = None,
    prompts_path: str | None = None,
    sections: set[str] | None = None,
    do_commit: bool = True,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Approve a proposal. Applies prompt_edit/rule_add automatically;
    config_change/code_change are approved but must be implemented by hand.

    Returns {applied, new_version, rule_id, instructions}.
    """
    prop = get_proposal(conn, proposal_id)
    if prop["status"] == "blocked":
        raise ValueError(
            f"Proposal {proposal_id} targets a protected component "
            f"('{prop['target']}') and can never be approved."
        )
    if prop["status"] != "pending":
        raise ValueError(f"Proposal {proposal_id} is '{prop['status']}', not pending")
    # Defense in depth: re-check the target even if the row was tampered with.
    if is_blocked_target(prop["target"]):
        conn.execute(
            "UPDATE proposals SET status = 'blocked' WHERE id = ?", (proposal_id,)
        )
        conn.commit()
        raise ValueError(
            f"Proposal {proposal_id} targets a protected component "
            f"('{prop['target']}'); marked blocked."
        )

    ptype = prop["type"]
    result: dict[str, Any] = {"applied": False, "new_version": None,
                              "rule_id": None, "instructions": ""}

    if ptype in ("prompt_edit", "rule_add"):
        if ptype == "prompt_edit":
            known = sections if sections is not None else rules_mod.get_prompt_sections()
            target_norm = prop["target"].strip().lower()
            if not any(target_norm == s or target_norm in s for s in known):
                raise ValueError(
                    f"prompt_edit target section '{prop['target']}' not found in the "
                    f"system prompt. Known sections: {', '.join(sorted(known))}"
                )
            body = (f"**Prompt override — {prop['target'].strip()}** "
                    f"(proposal {proposal_id}): {prop['change'].strip()}")
        else:
            body = f"(proposal {proposal_id}): {prop['change'].strip()}"

        rule_id = rules_mod.add_rule(body, proposal_id, rules_path)
        new_version = rules_mod.bump_prompt_version(prompts_path)
        conn.execute(
            "UPDATE proposals SET status = 'approved', decided_at = datetime('now'), "
            "applied_rule_id = ? WHERE id = ?",
            (rule_id, proposal_id),
        )
        conn.commit()
        if do_commit:
            rules_mod.git_commit(
                f"taco: apply proposal #{proposal_id}",
                [rules_path or rules_mod.default_rules_path(),
                 prompts_path or rules_mod.default_prompts_path()],
                repo_root,
            )
        result.update(applied=True, new_version=new_version, rule_id=rule_id)
    elif ptype in ("config_change", "code_change"):
        conn.execute(
            "UPDATE proposals SET status = 'approved', decided_at = datetime('now') "
            "WHERE id = ?",
            (proposal_id,),
        )
        conn.commit()
        result["instructions"] = (
            f"Proposal #{proposal_id} approved but requires MANUAL implementation "
            f"({ptype}).\n  Target: {prop['target']}\n  Change: {prop['change']}\n"
            f"  Expected effect: {prop['expected_effect']}"
        )
    else:
        raise ValueError(f"Unknown proposal type '{ptype}'")
    return result


def revert_proposal(
    conn: sqlite3.Connection,
    proposal_id: int,
    *,
    rules_path: str | None = None,
    prompts_path: str | None = None,
    do_commit: bool = True,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Rollback: remove the applied rule and bump the version again."""
    prop = get_proposal(conn, proposal_id)
    if prop["status"] != "approved" or prop["applied_rule_id"] is None:
        raise ValueError(
            f"Proposal {proposal_id} has no applied rule to revert "
            f"(status='{prop['status']}', rule={prop['applied_rule_id']})"
        )
    rule_id = rules_mod.remove_rule_for_proposal(proposal_id, rules_path)
    new_version = rules_mod.bump_prompt_version(prompts_path)
    conn.execute(
        "UPDATE proposals SET status = 'reverted', decided_at = datetime('now') "
        "WHERE id = ?",
        (proposal_id,),
    )
    conn.commit()
    if do_commit:
        rules_mod.git_commit(
            f"taco: revert proposal #{proposal_id}",
            [rules_path or rules_mod.default_rules_path(),
             prompts_path or rules_mod.default_prompts_path()],
            repo_root,
        )
    return {"rule_id": rule_id, "new_version": new_version}
