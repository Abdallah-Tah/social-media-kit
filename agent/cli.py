"""Command-line interface for the Social Media Agent.

    smkit run --topic "Laravel 13 new features" --dry-run
    smkit run --goal "Write a comparison of X and Y and post to LinkedIn"
    smkit wizard            # interactive setup
    smkit doctor            # check configuration & credentials
    smkit profiles          # list brand profiles
    smkit queue path.txt    # run the next topic from a queue file
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import AgentConfig, list_profiles, load_env, load_profile
from .orchestrator import run_agent
from .prompts import build_goal

# ── Pretty (but dependency-free) console output ─────────────────────────
ICONS = {
    "thinking": "🤔",
    "tool": "🔧",
    "tool_result": "📎",
    "final": "✅",
    "error": "❌",
}


def _make_printer(verbose: bool):
    def printer(kind: str, text: str) -> None:
        icon = ICONS.get(kind, "•")
        if kind == "tool_result" and not verbose:
            text = text.splitlines()[0][:200]
        if kind == "thinking" and not verbose:
            text = text[:400] + ("…" if len(text) > 400 else "")
        print(f"{icon} {text}\n")

    return printer


def cmd_run(args: argparse.Namespace) -> int:
    config = AgentConfig.load(
        provider=args.provider,
        model=args.model,
        dry_run=args.dry_run,
        max_steps=args.max_steps,
        auto_confirm=args.yes,
    )
    try:
        profile = load_profile(args.profile)
    except FileNotFoundError as exc:
        print(f"❌ {exc}")
        return 1

    try:
        goal = build_goal(args.topic, args.goal, profile)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    _banner(config, profile, goal)

    if not config.dry_run and not config.auto_confirm:
        if not _confirm_live(profile):
            print("Aborted. Re-run with --dry-run to preview safely.")
            return 1

    result = run_agent(goal, config, profile, on_event=_make_printer(args.verbose))

    print("=" * 60)
    if result.ok:
        print(f"🎉 Done in {result.steps} steps.\n{result.summary}")
        return 0
    print(f"Run ended with an error after {result.steps} steps:\n{result.error}")
    return 1


def cmd_queue(args: argparse.Namespace) -> int:
    """Pop the next topic from a queue file and run it (for scheduled jobs)."""
    path = Path(args.file)
    if not path.exists():
        print(f"❌ Queue file not found: {path}")
        return 1

    lines = path.read_text(encoding="utf-8").splitlines()
    topic = None
    remaining: list[str] = []
    for line in lines:
        stripped = line.strip()
        if topic is None and stripped and not stripped.startswith("#"):
            topic = stripped
        else:
            remaining.append(line)

    if topic is None:
        print("✅ Queue is empty — nothing to do.")
        return 0

    args.topic = topic
    args.goal = None
    rc = cmd_run(args)

    # On success, consume the topic and archive it.
    if rc == 0:
        path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        done = path.with_suffix(path.suffix + ".done")
        with done.open("a", encoding="utf-8") as f:
            f.write(topic + "\n")
        print(f"📥 Consumed topic from queue → {done.name}")
    return rc


def cmd_doctor(args: argparse.Namespace) -> int:
    import os

    load_env()
    print("🩺 Social Media Agent — configuration check\n")

    config = AgentConfig.load(provider=args.provider)
    print(f"Provider : {config.provider}")
    print(f"Model    : {config.model}")
    if config.provider == "ollama":
        print(f"Base URL : {config.base_url}  (no API key required)")
        print("LLM key  : n/a (local)\n")
    else:
        print(f"LLM key  : {'✅ set' if config.api_key else '❌ MISSING'}\n")

    checks = {
        "Blog": ["BLOG_API_URL", "BLOG_API_TOKEN"],
        "Facebook": ["FB_PAGE_ID", "FB_PAGE_TOKEN"],
        "X (Twitter)": ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"],
        "LinkedIn": ["LINKEDIN_ACCESS_TOKEN"],
        "Slack": ["SLACK_WEBHOOK_URL", "SLACK_BOT_TOKEN"],
        "Discord": ["DISCORD_WEBHOOK_URL"],
        "Telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
        "Mastodon": ["MASTODON_BASE_URL", "MASTODON_ACCESS_TOKEN"],
        "Webhook": ["WEBHOOK_URL"],
        "Web search": ["BRAVE_API_KEY"],
    }
    print("Channel credentials:")
    for label, keys in checks.items():
        present = [k for k in keys if os.environ.get(k)]
        if label == "Slack":  # either method is fine
            ok = bool(present)
        elif label == "Web search":
            ok = bool(present)  # optional (DuckDuckGo fallback exists)
        else:
            ok = len(present) == len(keys)
        mark = "✅" if ok else ("◻️ " if not present else "⚠️ ")
        detail = "" if ok else f"(missing: {', '.join(k for k in keys if k not in present)})"
        if label == "Web search" and not ok:
            detail = "(optional — falls back to DuckDuckGo)"
        print(f"  {mark} {label} {detail}")

    print(f"\nProfiles : {', '.join(list_profiles()) or '(none — run `smkit wizard`)'}")
    return 0


def cmd_profiles(args: argparse.Namespace) -> int:
    profiles = list_profiles()
    if not profiles:
        print("No profiles yet. Create one with `smkit wizard`.")
        return 0
    print("Brand profiles:")
    for name in profiles:
        try:
            p = load_profile(name)
            platforms = ", ".join(p.get("platforms", []))
            print(f"  • {name} → {p.get('tone', '')[:40]} | channels: {platforms}")
        except Exception:
            print(f"  • {name}")
    return 0


def cmd_wizard(args: argparse.Namespace) -> int:
    from .wizard import run_wizard

    return run_wizard()


def cmd_install_skill(args: argparse.Namespace) -> int:
    """Permanently register the kit as an OpenClaw / Claude Code skill."""
    from .install import detect_skills_dir, install_skill

    if not args.skills_dir:
        detected = detect_skills_dir()
        print(f"🔎 Skills directory: {detected or '(none detected)'}")
    ok, msg = install_skill(
        skills_dir=args.skills_dir, copy=args.copy, force=args.force
    )
    print(("✅ " if ok else "❌ ") + msg)
    if ok:
        print(
            "\nNext: ensure the package is installed so `smkit` is on PATH:\n"
            "   pip install -e .\n"
            "Then your OpenClaw agent will auto-discover 'social-media-agent'\n"
            "on its next start. Verify with:  smkit doctor"
        )
    return 0 if ok else 1


# ── Helpers ─────────────────────────────────────────────────────────────
def _banner(config, profile, goal) -> None:
    mode = "DRY RUN (no posts go live)" if config.dry_run else "LIVE"
    print("=" * 60)
    print(f"📡 Social Media Agent v{__version__}  —  {mode}")
    print(f"Brand    : {profile.get('name')}")
    print(f"Provider : {config.provider} / {config.model}")
    print(f"Channels : {', '.join(profile.get('platforms', []))}")
    print(f"Goal     : {goal}")
    print("=" * 60 + "\n")


def _confirm_live(profile) -> bool:
    channels = ", ".join(profile.get("platforms", []))
    try:
        ans = input(
            f"⚠️  LIVE mode will publish to: {channels}. Continue? [y/N] "
        ).strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smkit",
        description="Orchestrated, provider-agnostic social media content agent.",
    )
    parser.add_argument("--version", action="version", version=f"smkit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # Shared run options reused by `run` and `queue`.
    def add_run_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--profile", "-p", default="default", help="Brand profile name")
        p.add_argument("--provider", choices=["anthropic", "openai", "ollama"],
                       help="Override the LLM provider")
        p.add_argument("--model", help="Override the model id")
        p.add_argument("--max-steps", type=int, help="Max agent steps")
        p.add_argument("--dry-run", action="store_true",
                       help="Simulate publishing (no posts go live)")
        p.add_argument("--yes", "-y", action="store_true",
                       help="Skip the live-mode confirmation prompt")
        p.add_argument("--verbose", "-v", action="store_true", help="Full output")

    p_run = sub.add_parser("run", help="Run the agent on a topic or goal")
    p_run.add_argument("--topic", "-t", help="Topic to research, write, and publish")
    p_run.add_argument("--goal", "-g", help="Explicit free-form goal")
    add_run_opts(p_run)
    p_run.set_defaults(func=cmd_run)

    p_queue = sub.add_parser("queue", help="Run the next topic from a queue file")
    p_queue.add_argument("file", help="Path to a newline-delimited topics file")
    add_run_opts(p_queue)
    p_queue.set_defaults(func=cmd_queue)

    p_doctor = sub.add_parser("doctor", help="Check configuration and credentials")
    p_doctor.add_argument("--provider", choices=["anthropic", "openai", "ollama"])
    p_doctor.set_defaults(func=cmd_doctor)

    p_profiles = sub.add_parser("profiles", help="List brand profiles")
    p_profiles.set_defaults(func=cmd_profiles)

    p_wizard = sub.add_parser("wizard", help="Interactive first-time setup")
    p_wizard.set_defaults(func=cmd_wizard)

    p_install = sub.add_parser(
        "install-skill",
        help="Register as a permanent OpenClaw / Claude Code skill",
    )
    p_install.add_argument(
        "--skills-dir", help="Skills root (auto-detected if omitted)"
    )
    p_install.add_argument(
        "--copy", action="store_true",
        help="Copy the skill instead of symlinking",
    )
    p_install.add_argument(
        "--force", action="store_true", help="Replace an existing install"
    )
    p_install.set_defaults(func=cmd_install_skill)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
