"""CLI for the self-improvement loop.

Usage:
    python -m agent_journal journal grade RUN_ID OUTCOME --note "..."
    python -m agent_journal journal stats [--by prompt_version]
    python -m agent_journal journal list [--last 20]
    python -m agent_journal reflect [--last 25] [--force] [--min-graded 10]
    python -m agent_journal proposals list [--status pending]
    python -m agent_journal proposals show ID
    python -m agent_journal proposals approve ID [--no-commit]
    python -m agent_journal proposals reject ID --note "..."
    python -m agent_journal proposals revert ID
"""
from __future__ import annotations

import argparse
import json
import sys

from agent_journal.db import default_db_path, get_connection
from agent_journal.journal import VALID_OUTCOMES, grade_run, list_runs
from agent_journal.reflect import MIN_NEWLY_GRADED, run_reflection
from agent_journal.stats import format_stats, journal_stats
from agent_journal import proposals as gate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent_journal", description=__doc__)
    parser.add_argument("--db", default=None,
                        help=f"Journal DB path (default: {default_db_path()})")
    sub = parser.add_subparsers(dest="command", required=True)

    # journal grade / stats / list
    p_journal = sub.add_parser("journal", help="Run journal: grade, stats, list")
    jsub = p_journal.add_subparsers(dest="journal_command", required=True)

    p_grade = jsub.add_parser("grade", help="Grade a run manually")
    p_grade.add_argument("run_id", type=int)
    p_grade.add_argument("outcome", choices=VALID_OUTCOMES)
    p_grade.add_argument("--note", default=None)
    p_grade.set_defaults(func=cmd_grade)

    p_stats = jsub.add_parser("stats", help="Outcome rates per group")
    p_stats.add_argument("--by", default="prompt_version",
                         choices=("prompt_version", "task_type", "pillar", "model_used"))
    p_stats.set_defaults(func=cmd_stats)

    p_list = jsub.add_parser("list", help="Recent runs")
    p_list.add_argument("--last", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    # reflect
    p_reflect = sub.add_parser("reflect", help="One reflection pass over graded runs")
    p_reflect.add_argument("--last", type=int, default=25)
    p_reflect.add_argument("--model", default=None,
                           help="Override ANTHROPIC_REFLECT_MODEL")
    p_reflect.add_argument("--force", action="store_true",
                           help="Skip the newly-graded-runs gate")
    p_reflect.add_argument("--min-graded", type=int, default=MIN_NEWLY_GRADED)
    p_reflect.set_defaults(func=cmd_reflect)

    # proposals
    p_prop = sub.add_parser("proposals", help="Human gate: list/show/approve/reject/revert")
    psub = p_prop.add_subparsers(dest="proposals_command", required=True)

    pp = psub.add_parser("list")
    pp.add_argument("--status", default=None)
    pp.set_defaults(func=cmd_proposals_list)

    pp = psub.add_parser("show")
    pp.add_argument("id", type=int)
    pp.set_defaults(func=cmd_proposals_show)

    pp = psub.add_parser("approve")
    pp.add_argument("id", type=int)
    pp.add_argument("--no-commit", action="store_true",
                    help="Apply without a git commit")
    pp.set_defaults(func=cmd_proposals_approve)

    pp = psub.add_parser("reject")
    pp.add_argument("id", type=int)
    pp.add_argument("--note", required=True)
    pp.set_defaults(func=cmd_proposals_reject)

    pp = psub.add_parser("revert")
    pp.add_argument("id", type=int)
    pp.add_argument("--no-commit", action="store_true")
    pp.set_defaults(func=cmd_proposals_revert)

    return parser


def cmd_grade(args: argparse.Namespace) -> int:
    conn = get_connection(args.db)
    try:
        result = grade_run(conn, args.run_id, args.outcome, args.note)
    finally:
        conn.close()
    prev = f" (was: {result['previous_outcome']})" if result["previous_outcome"] else ""
    print(f"Run {args.run_id} graded '{args.outcome}'{prev}.")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = get_connection(args.db)
    try:
        print(format_stats(journal_stats(conn, by=args.by), args.by))
    finally:
        conn.close()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    conn = get_connection(args.db)
    try:
        runs = list_runs(conn, last=args.last)
    finally:
        conn.close()
    if not runs:
        print("No runs in the journal yet.")
        return 0
    for r in runs:
        err = " ERROR" if r["error"] else ""
        print(f"#{r['id']:>4} {r['started_at']} {r['task_type']:<9} "
              f"{(r['pillar'] or '-'):<22} v{r['prompt_version'] or '?':<7} "
              f"{r['outcome'] or 'ungraded'}{err}")
    return 0


def cmd_reflect(args: argparse.Namespace) -> int:
    """Reflection failures warn and exit 0 — cron must never break on this."""
    conn = get_connection(args.db)
    try:
        summary = run_reflection(
            conn, last=args.last, model=args.model,
            force=args.force, min_graded=args.min_graded,
        )
    except Exception as exc:  # noqa: BLE001 — warn-and-continue by design
        print(f"[reflect] WARNING: reflection failed: {exc}", file=sys.stderr)
        return 0
    finally:
        conn.close()

    if summary.get("skipped"):
        print(f"Reflection skipped: {summary['skipped']}")
        return 0
    print(f"Reflected over {summary['runs']} graded runs "
          f"(requested {summary['model']}, answered by {summary['responded_model']}).")
    if summary["proposals"]:
        print(f"Created {summary['proposals']} proposal(s): "
              f"{', '.join(f'#{i}' for i in summary['proposal_ids'])}")
        print("Review with: python -m agent_journal proposals list")
    else:
        print("No proposals met the evidence bar.")
    return 0


def cmd_proposals_list(args: argparse.Namespace) -> int:
    conn = get_connection(args.db)
    try:
        props = gate.list_proposals(conn, status=args.status)
    finally:
        conn.close()
    if not props:
        print("No proposals.")
        return 0
    for p in props:
        print(f"#{p['id']:>3} [{p['status']:<8}] {p['type']:<13} "
              f"target={p['target'][:40]:<40} {p['change'][:60]}")
    return 0


def cmd_proposals_show(args: argparse.Namespace) -> int:
    conn = get_connection(args.db)
    try:
        p = gate.get_proposal(conn, args.id)
    finally:
        conn.close()
    for key in ("id", "created_at", "status", "type", "target", "change",
                "expected_effect", "evidence", "source_run_ids",
                "decided_at", "decision_note", "applied_rule_id"):
        print(f"{key:>16}: {p[key]}")
    return 0


def cmd_proposals_approve(args: argparse.Namespace) -> int:
    conn = get_connection(args.db)
    try:
        result = gate.approve_proposal(conn, args.id, do_commit=not args.no_commit)
    finally:
        conn.close()
    if result["applied"]:
        print(f"Proposal #{args.id} applied as rule #{result['rule_id']:04d}; "
              f"PROMPT_VERSION bumped to {result['new_version']}.")
    else:
        print(result["instructions"])
    return 0


def cmd_proposals_reject(args: argparse.Namespace) -> int:
    conn = get_connection(args.db)
    try:
        gate.reject_proposal(conn, args.id, args.note)
    finally:
        conn.close()
    print(f"Proposal #{args.id} rejected.")
    return 0


def cmd_proposals_revert(args: argparse.Namespace) -> int:
    conn = get_connection(args.db)
    try:
        result = gate.revert_proposal(conn, args.id, do_commit=not args.no_commit)
    finally:
        conn.close()
    print(f"Proposal #{args.id} reverted (removed rule #{result['rule_id']:04d}); "
          f"PROMPT_VERSION bumped to {result['new_version']}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
