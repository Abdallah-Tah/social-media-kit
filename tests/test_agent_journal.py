"""Tests for agent_journal — the Taco self-improvement loop.

Covers the required acceptance tests:
1. Journal write on success and on error (and journal failure never crashes)
2. Grade flow (valid, invalid outcome, missing run)
3. Reflection JSON parsing (valid, malformed, fence-wrapped, garbage)
4. Gate blocks self-targeting proposals
5. Approve bumps PROMPT_VERSION and writes the rule; revert undoes it
6. Approving a prompt_edit whose target section doesn't exist fails loudly
7. Stats groups by prompt_version correctly
8. Founding rules can never be removed
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_journal.db import init_db, get_meta, set_meta
from agent_journal.journal import grade_run, record_run
from agent_journal.reflect import build_digest, newly_graded_count, parse_proposals
from agent_journal.stats import journal_stats
from agent_journal import proposals as gate
from agent_journal import rules as rules_mod


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "journal.db")


@pytest.fixture
def conn(db_path):
    c = init_db(db_path)
    yield c
    c.close()


@pytest.fixture
def rules_file(tmp_path):
    p = tmp_path / "taco_rules.md"
    p.write_text(
        "# Taco — learned rules\n\n"
        "<!-- rule #0001 -->\n"
        "**Verified-source:** founding rule one.\n"
        "<!-- /rule #0001 -->\n\n"
        "<!-- rule #0002 -->\n"
        "**Vendor-reported:** founding rule two.\n"
        "<!-- /rule #0002 -->\n",
        encoding="utf-8",
    )
    return str(p)


@pytest.fixture
def prompts_file(tmp_path):
    p = tmp_path / "prompts.py"
    p.write_text('PROMPT_VERSION = "1.0.0"\n', encoding="utf-8")
    return str(p)


# ── 1. Journal writes ────────────────────────────────────────────────────


def test_journal_write_on_success(db_path):
    with record_run("generate", pillar="match_recap",
                    input_summary="mode=fan_mode", db_path=db_path) as rec:
        rec.model_used = "claude-test"
        rec.output_ref = "artifacts/chart.png"
    assert rec.run_id is not None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (rec.run_id,)).fetchone()
    assert row["task_type"] == "generate"
    assert row["pillar"] == "match_recap"
    assert row["model_used"] == "claude-test"
    assert row["error"] is None
    assert row["outcome"] is None
    assert row["duration_ms"] >= 0
    conn.close()


def test_journal_write_on_error(db_path):
    with pytest.raises(RuntimeError, match="boom"):
        with record_run("generate", pillar="x", db_path=db_path):
            raise RuntimeError("boom")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM agent_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert row["error"] == "RuntimeError: boom"
    conn.close()


def test_journal_failure_never_crashes_the_run(tmp_path, capsys):
    bad_path = str(tmp_path / "no" / "such" / "dir" / "j.db")
    with record_run("generate", db_path=bad_path) as rec:
        pass  # the step itself succeeds
    assert rec.run_id is None
    assert "WARNING" in capsys.readouterr().err


def test_outcome_written_with_timestamp(db_path):
    with record_run("publish", db_path=db_path) as rec:
        rec.outcome = "published"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT outcome, outcome_at FROM agent_runs WHERE id = ?",
                       (rec.run_id,)).fetchone()
    assert row["outcome"] == "published"
    assert row["outcome_at"] is not None
    conn.close()


# ── 2. Grade flow ────────────────────────────────────────────────────────


def test_grade_flow(conn, db_path):
    with record_run("generate", db_path=db_path) as rec:
        pass
    result = grade_run(conn, rec.run_id, "corrected", "stat was wrong")
    assert result["previous_outcome"] is None
    row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (rec.run_id,)).fetchone()
    assert row["outcome"] == "corrected"
    assert row["outcome_detail"] == "stat was wrong"
    assert row["outcome_at"] is not None


def test_grade_invalid_outcome(conn, db_path):
    with record_run("generate", db_path=db_path) as rec:
        pass
    with pytest.raises(ValueError, match="Invalid outcome"):
        grade_run(conn, rec.run_id, "great-job")


def test_grade_missing_run(conn):
    with pytest.raises(ValueError, match="not found"):
        grade_run(conn, 99999, "approved")


# ── 3. Reflection JSON parsing ───────────────────────────────────────────

_VALID_ITEM = {
    "type": "rule_add",
    "target": "writing style",
    "change": "Always include the data source date in chart captions.",
    "evidence_run_ids": [3, 7],
    "expected_effect": "fewer 'corrected' outcomes for stale-data captions",
}


def test_parse_valid_json():
    valid, warnings = parse_proposals(json.dumps([_VALID_ITEM]))
    assert len(valid) == 1 and not warnings
    assert valid[0]["evidence_run_ids"] == [3, 7]


def test_parse_fence_wrapped():
    text = "```json\n" + json.dumps([_VALID_ITEM]) + "\n```"
    valid, warnings = parse_proposals(text)
    assert len(valid) == 1 and not warnings


def test_parse_malformed_item_skipped():
    bad = {"type": "rule_add", "target": "", "change": "x",
           "evidence_run_ids": [], "expected_effect": "y"}
    wrong_type = dict(_VALID_ITEM, type="self_modify")
    valid, warnings = parse_proposals(json.dumps([_VALID_ITEM, bad, wrong_type, "junk"]))
    assert len(valid) == 1
    assert len(warnings) == 3


def test_parse_garbage_never_crashes():
    for garbage in ("", "not json at all", "{\"a\": 1}", "42", None):
        valid, warnings = parse_proposals(garbage or "")
        assert valid == []
        assert warnings


def test_parse_json_with_commentary_prefix():
    text = "Here are my proposals:\n" + json.dumps([_VALID_ITEM])
    valid, _ = parse_proposals(text)
    assert len(valid) == 1


# ── 4. Gate blocks self-targeting proposals ──────────────────────────────


@pytest.mark.parametrize("target", [
    "agent_journal/proposals.py",
    "the proposal gate",
    "agent_runs schema",
    "reflection rubric",
    "Verified-source rule",
    "vendor-reported attribution rule",
    "config/taco_rules.md",
])
def test_gate_blocks_protected_targets(conn, target):
    pid = gate.insert_proposal(conn, dict(_VALID_ITEM, target=target), [1, 2])
    assert gate.get_proposal(conn, pid)["status"] == "blocked"
    with pytest.raises(ValueError, match="protected"):
        gate.approve_proposal(conn, pid, do_commit=False)


def test_gate_recheck_at_approve_time(conn):
    """Defense in depth: a tampered row is re-blocked at approve time."""
    pid = gate.insert_proposal(conn, dict(_VALID_ITEM), [1])
    conn.execute("UPDATE proposals SET target = 'agent_journal/db.py' WHERE id = ?", (pid,))
    conn.commit()
    with pytest.raises(ValueError, match="protected"):
        gate.approve_proposal(conn, pid, do_commit=False)
    assert gate.get_proposal(conn, pid)["status"] == "blocked"


# ── 5. Approve applies rule + bumps version; revert undoes ───────────────


def test_approve_rule_add(conn, rules_file, prompts_file):
    pid = gate.insert_proposal(conn, dict(_VALID_ITEM), [3, 7])
    result = gate.approve_proposal(
        conn, pid, rules_path=rules_file, prompts_path=prompts_file, do_commit=False,
    )
    assert result["applied"] is True
    assert result["new_version"] == "1.0.1"
    assert result["rule_id"] == 3  # founding rules are #1 and #2

    assert 'PROMPT_VERSION = "1.0.1"' in Path(prompts_file).read_text()
    text = Path(rules_file).read_text()
    assert f"<!-- rule #0003 proposal={pid} -->" in text
    assert _VALID_ITEM["change"] in text

    prop = gate.get_proposal(conn, pid)
    assert prop["status"] == "approved"
    assert prop["applied_rule_id"] == 3


def test_revert_removes_rule_and_bumps(conn, rules_file, prompts_file):
    pid = gate.insert_proposal(conn, dict(_VALID_ITEM), [3])
    gate.approve_proposal(conn, pid, rules_path=rules_file,
                          prompts_path=prompts_file, do_commit=False)
    result = gate.revert_proposal(conn, pid, rules_path=rules_file,
                                  prompts_path=prompts_file, do_commit=False)
    assert result["new_version"] == "1.0.2"
    text = Path(rules_file).read_text()
    assert f"proposal={pid}" not in text
    assert "founding rule one" in text  # founding rules untouched
    assert gate.get_proposal(conn, pid)["status"] == "reverted"


def test_approve_config_change_is_manual(conn, rules_file, prompts_file):
    item = dict(_VALID_ITEM, type="config_change", target="agent/config.py max_steps")
    pid = gate.insert_proposal(conn, item, [1])
    result = gate.approve_proposal(conn, pid, rules_path=rules_file,
                                   prompts_path=prompts_file, do_commit=False)
    assert result["applied"] is False
    assert "MANUAL implementation" in result["instructions"]
    # Nothing was touched
    assert 'PROMPT_VERSION = "1.0.0"' in Path(prompts_file).read_text()
    assert "proposal=" not in Path(rules_file).read_text()


# ── 6. prompt_edit target section must exist ─────────────────────────────


def test_approve_prompt_edit_missing_section_fails_loudly(conn, rules_file, prompts_file):
    item = dict(_VALID_ITEM, type="prompt_edit", target="Nonexistent Section")
    pid = gate.insert_proposal(conn, item, [1])
    with pytest.raises(ValueError, match="not found in the.*system prompt"):
        gate.approve_proposal(
            conn, pid, rules_path=rules_file, prompts_path=prompts_file,
            sections={"writing style (sound like a human developer, not an ai)",
                      "rules", "enabled channels"},
            do_commit=False,
        )
    # Fails BEFORE applying anything
    assert gate.get_proposal(conn, pid)["status"] == "pending"
    assert 'PROMPT_VERSION = "1.0.0"' in Path(prompts_file).read_text()


def test_approve_prompt_edit_valid_section(conn, rules_file, prompts_file):
    item = dict(_VALID_ITEM, type="prompt_edit", target="Rules")
    pid = gate.insert_proposal(conn, item, [1])
    result = gate.approve_proposal(
        conn, pid, rules_path=rules_file, prompts_path=prompts_file,
        sections={"rules", "enabled channels"}, do_commit=False,
    )
    assert result["applied"] is True
    assert "Prompt override — Rules" in Path(rules_file).read_text()


def test_prompt_edit_sections_come_from_real_prompt(conn, rules_file, prompts_file):
    """get_prompt_sections() renders the actual system prompt."""
    sections = rules_mod.get_prompt_sections()
    assert any("rules" in s for s in sections)
    assert any("enabled channels" in s for s in sections)


# ── Founding rules are permanent ─────────────────────────────────────────


def test_founding_rules_cannot_be_removed(rules_file):
    with pytest.raises(ValueError, match="No applied rule"):
        rules_mod.remove_rule_for_proposal(1, rules_file)


def test_load_rules_strips_markers(rules_file):
    text = rules_mod.load_rules(rules_file)
    assert "Verified-source" in text and "Vendor-reported" in text
    assert "<!--" not in text


# ── 7. Stats group by prompt_version ─────────────────────────────────────


def test_stats_groups_by_version(conn, db_path, monkeypatch):
    def seed(version, outcome, error=None):
        conn.execute(
            "INSERT INTO agent_runs (task_type, prompt_version, outcome, error) "
            "VALUES ('generate', ?, ?, ?)",
            (version, outcome, error),
        )
    seed("1.0.0", "approved")
    seed("1.0.0", "approved")
    seed("1.0.0", "corrected")
    seed("1.0.0", None, error="boom")
    seed("1.0.1", "rejected")
    seed("1.0.1", "published")
    conn.commit()

    stats = {s["group"]: s for s in journal_stats(conn, by="prompt_version")}
    v0, v1 = stats["1.0.0"], stats["1.0.1"]
    assert v0["runs"] == 4 and v0["graded"] == 3
    assert v0["approved_pct"] == 66.7
    assert v0["corrected_pct"] == 33.3
    assert v0["error_pct"] == 25.0
    assert v1["rejected_pct"] == 50.0
    assert v1["published"] == 1

    with pytest.raises(ValueError):
        journal_stats(conn, by="id; DROP TABLE agent_runs")


# ── Scheduling gate: newly graded counter ────────────────────────────────


def test_newly_graded_gate(conn):
    for i in range(12):
        conn.execute(
            "INSERT INTO agent_runs (task_type, outcome) VALUES ('generate', 'approved')"
        )
    conn.commit()
    assert newly_graded_count(conn) == 12
    set_meta(conn, "last_reflected_run_id", "12")
    assert newly_graded_count(conn) == 0


def test_build_digest_format():
    rows = [{"id": 5, "task_type": "generate", "pillar": "match_recap",
             "prompt_version": "1.0.0", "model_used": "claude-x",
             "outcome": "corrected", "outcome_detail": "wrong score", "error": None}]
    digest = build_digest(rows)
    assert "run 5" in digest and "corrected" in digest and "wrong score" in digest
