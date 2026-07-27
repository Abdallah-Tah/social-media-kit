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
import json
import subprocess
import sys
from pathlib import Path

from . import __version__, history
from .config import AgentConfig, list_profiles, load_env, load_profile
from .orchestrator import run_agent
from .prompts import build_goal

from .intelligence import run_intelligence

LLM_PROVIDERS = ["anthropic", "openai", "nvidia", "ollama"]

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

    # Dedupe: don't re-publish a topic we've already shipped.
    if args.topic and not args.force and history.has_topic(args.topic):
        print(
            f"⏭️  Already published a run for \"{args.topic}\" "
            "(see `smkit history`). Re-run with --force to do it again."
        )
        return 0

    _banner(config, profile, goal)

    if not config.dry_run and not config.auto_confirm:
        if not _confirm_live(profile):
            print("Aborted. Re-run with --dry-run to preview safely.")
            return 1

    result = run_agent(goal, config, profile, on_event=_make_printer(args.verbose))

    print("=" * 60)
    if result.ok:
        # Record real publishes (not dry-runs) for the track record + dedupe.
        if not config.dry_run:
            history.record({
                "topic": args.topic or args.goal or "",
                "profile": profile.get("name"),
                "provider": config.provider,
                "channels": profile.get("platforms", []),
                "steps": result.steps,
                "summary": result.summary,
            })
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
        if config.base_url:
            print(f"Base URL : {config.base_url}")
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
        "Bluesky": ["BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"],
        "Threads": ["THREADS_USER_ID", "THREADS_ACCESS_TOKEN"],
        "Reddit": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME", "REDDIT_PASSWORD"],
        "Pinterest": ["PINTEREST_ACCESS_TOKEN", "PINTEREST_BOARD_ID"],
        "Webhook": ["WEBHOOK_URL"],
        "Web search": ["BRAVE_API_KEY"],
        "Cover images": ["FAL_KEY"],
    }
    OPTIONAL = {"Web search", "Cover images"}
    # Feed source health
    try:
        from .feed import doctor_feed
        feed_health = doctor_feed()
        print("\nFeed sources:")
        for name, status in feed_health.get("sources", {}).items():
            mark = "✅" if status.get("ok") else "⚠️"
            print(f"  {mark} {name}")
    except Exception as exc:
        print(f"\n⚠️  Feed doctor check failed: {exc}")

    print("Channel credentials:")
    for label, keys in checks.items():
        present = [k for k in keys if os.environ.get(k)]
        if label in ("Slack", "Web search", "Cover images"):
            ok = bool(present)  # any one key (or optional with a free fallback)
        else:
            ok = len(present) == len(keys)
        mark = "✅" if ok else ("◻️ " if not present else "⚠️ ")
        detail = "" if ok else f"(missing: {', '.join(k for k in keys if k not in present)})"
        if label == "Web search" and not ok:
            detail = "(optional — falls back to DuckDuckGo / Wikipedia)"
        if label == "Cover images" and not ok:
            detail = "(optional — falls back to a branded card; or set OPENAI_API_KEY)"
        print(f"  {mark} {label} {detail}")

    # ── Secret health: catch truncated copy-pastes (e.g. a UI '…' elision) ──
    all_keys = {k for keys in checks.values() for k in keys}
    all_keys |= {
        "BWA_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "NVIDIA_API_KEY", "NGC_API_KEY", "FAL_KEY", "SLACK_BOT_TOKEN",
        "MASTODON_ACCESS_TOKEN", "LINKEDIN_ACCESS_TOKEN",
    }
    warnings = []
    for key in sorted(all_keys):
        reason = _looks_truncated(os.environ.get(key, ""))
        if reason:
            warnings.append(f"  ⚠️  {key}: {reason}")
    if warnings:
        print("\nSecret health:")
        print("\n".join(warnings))

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


def cmd_learn(args: argparse.Namespace) -> int:
    """Build a brand profile by reading the buyer's website."""
    from .learn import learn_brand

    config = AgentConfig.load(provider=args.provider, model=args.model)
    platforms = (
        [p.strip() for p in args.platforms.split(",")] if args.platforms else None
    )
    print(f"🧬 Learning brand voice from {args.url} via {config.provider}/{config.model} …")
    ok, msg = learn_brand(args.url, args.profile, platforms, config)
    if ok:
        print(f"✅ Wrote profile → {msg}\n   Review it, then: smkit run --topic \"...\" --profile {args.profile} --dry-run")
        return 0
    print(f"❌ {msg}")
    return 1


def cmd_repurpose(args: argparse.Namespace) -> int:
    """Turn one existing piece (URL or file) into native posts for every channel."""
    from .repurpose import repurpose

    config = AgentConfig.load(
        provider=args.provider, model=args.model,
        dry_run=args.dry_run, max_steps=args.max_steps, auto_confirm=args.yes,
    )
    try:
        profile = load_profile(args.profile)
    except FileNotFoundError as exc:
        print(f"❌ {exc}")
        return 1

    print(f"♻️  Repurposing {args.source} → {', '.join(profile.get('platforms', []))}")
    if not config.dry_run and not config.auto_confirm and not _confirm_live(profile):
        print("Aborted. Re-run with --dry-run to preview safely.")
        return 1

    try:
        result = repurpose(args.source, config, profile,
                           on_event=_make_printer(args.verbose))
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    print("=" * 60)
    if result.ok:
        if not config.dry_run:
            source_label = Path(args.source).name if Path(args.source).exists() else args.source
            history.record({
                "topic": f"Repurpose: {source_label}",
                "profile": profile.get("name"),
                "provider": config.provider,
                "channels": profile.get("platforms", []),
                "steps": result.steps,
                "summary": result.summary,
            })
        print(f"🎉 Repurposed in {result.steps} steps.\n{result.summary}")
        return 0
    print(f"Ended with an error after {result.steps} steps:\n{result.error}")
    return 1


def cmd_dashboard(args: argparse.Namespace) -> int:
    from .dashboard import serve

    serve(host=args.host, port=args.port)
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    entries = history.load()
    if not entries:
        print("No published runs yet.")
        return 0
    print(f"📜 Published runs ({len(entries)}):")
    for e in entries[-args.limit:]:
        date = (e.get("date", "")[:10])
        channels = ", ".join(e.get("channels", []))
        print(f"  • {date}  {e.get('topic','')[:60]}  → [{channels}]")
    return 0


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


def cmd_shorts_plan(args: argparse.Namespace) -> int:
    from .shorts import SHORTS_DIR, ShortsError, find_article, plan_short

    try:
        article = find_article(args.article)
        out = Path(args.out) if args.out else SHORTS_DIR / article.slug / "short_plan.json"
        plan = plan_short(article, out)
    except ShortsError as exc:
        print(f"❌ {exc}")
        return 1
    print(f"✅ Short plan written: {out}")
    print(f"   type: {plan.get('short_type')}")
    print(f"   hook: {plan.get('hook')}")
    return 0


def cmd_shorts_render(args: argparse.Namespace) -> int:
    from .shorts import ShortsError, render_short

    try:
        result = render_short(args.plan, args.out)
    except ShortsError as exc:
        print(f"❌ {exc}")
        return 1
    print(f"✅ Short rendered: {result['video']}")
    print(f"   scenes: {len(result['scenes'])}")
    print(f"   voiceover: {'yes' if result.get('has_voiceover') else 'no'}")
    return 0


def cmd_shorts_preview(args: argparse.Namespace) -> int:
    from .shorts import ShortsError, preview_short

    try:
        preview_short(args.video, args.plan)
    except ShortsError as exc:
        print(f"❌ {exc}")
        return 1
    print("✅ Preview sent to Telegram. Publish only after approval.")
    return 0


def cmd_shorts_publish(args: argparse.Namespace) -> int:
    from .shorts import ShortsError, publish_short

    if not args.yes:
        try:
            ans = input(
                "Approval gate: confirm this preview was approved for public upload. Continue? [y/N] "
            ).strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("Aborted. Send a preview first, get approval, then publish.")
            return 1
    try:
        publish_short(args.provider, args.video, args.plan)
    except ShortsError as exc:
        print(f"❌ {exc}")
        return 1
    print("✅ Short published.")
    return 0


def cmd_intelligence(args: argparse.Namespace) -> int:
    """Run the Content Intelligence Engine (phase 1: no content generation)."""
    sources = args.audience_source if args.audience_source else None
    audience_live = args.audience_live if args.audience_live else None
    audience_text = args.audience_text if args.audience_text else None
    enable_content_gap = args.content_gap if args.content_gap else None
    enable_newsletter_mining = args.newsletter_mining if args.newsletter_mining else None
    report_path = run_intelligence(
        report_path=args.out,
        top_n=args.top,
        dry_run=args.dry_run,
        min_authority_score=args.min_authority,
        audience_live=audience_live,
        audience_text=audience_text,
        audience_sources=sources,
        enable_content_gap=enable_content_gap,
        sitemap_url=args.sitemap_url,
        existing_content_file=args.existing_content_file,
        enable_newsletter_mining=enable_newsletter_mining,
    )
    print(f"\n✅ Content intelligence report: {report_path}")
    return 0


def cmd_calendar(args: argparse.Namespace) -> int:
    """Generate a weekly content opportunity calendar."""
    from .intelligence.opportunity_calendar import run_calendar_pipeline
    path = run_calendar_pipeline(
        days=args.days,
        report_path=args.out,
        include_newsletter=args.include_newsletter,
        include_audience=args.include_audience,
        top_n=args.top,
    )
    print(f"\n✅ Content opportunity calendar: {path}")
    return 0


def cmd_feed(args: argparse.Namespace) -> int:
    """Personalized AI news feed: fetch, rank, save, notify, or post."""
    if args.intelligence:
        return _cmd_feed_intelligence(args)

    from .feed import build_feed, notify_feed, post_feed, print_feed, save_feed

    items = build_feed(
        topic=args.topic,
        profile_name=args.profile,
        limit=args.limit,
        excluded_sources=args.exclude_source or [],
        use_llm=args.llm,
    )

    if args.save:
        path = save_feed(items)
        print(f"💾 Feed snapshot saved: {path}")

    if args.notify:
        result = notify_feed(
            items,
            channel=args.channel,
            profile_name=args.profile,
            dry_run=args.dry_run,
        )
        if result.get("dry_run"):
            print("🔮 Dry-run notification:\n")
            print(result["message"])
        elif result["ok"]:
            print(f"✅ Notified {result['channel']} with {result['sent']} items.")
        else:
            print(f"❌ Notify failed: {result.get('error')}")
            return 1

    if args.post:
        if args.dry_run:
            print("🔮 Dry-run --post: would create social content from top story:")
            print(f"   {items[0].title}\n   {items[0].url}")
        else:
            print(f"🚀 Creating social post from top story: {items[0].title}")
            result = post_feed(items, profile_name=args.profile, dry_run=False)
            if result["ok"]:
                print("✅ Social post pipeline completed.")
            else:
                print(f"❌ Post pipeline failed: {result.get('error') or result.get('stderr')}")
                return 1

    # Always print ranked feed unless --quiet is passed.
    if not args.quiet:
        print_feed(items)

    return 0


def _cmd_feed_intelligence(args: argparse.Namespace) -> int:
    """Run the full six-phase intelligence pipeline."""
    from .feed_intelligence import (
        generate_brief_for_top,
        print_intelligence,
        run_intelligent_feed,
        save_intelligence,
    )

    cards = run_intelligent_feed(
        topic=args.topic,
        profile_name=args.profile,
        limit=args.limit,
        excluded_sources=args.exclude_source or [],
        use_llm=args.llm,
        include_seen=args.include_seen,
    )

    brief = None
    if args.brief:
        brief = generate_brief_for_top(cards)
        if brief:
            print(f"📝 Generated {brief.content_type} brief for top opportunity.")
        else:
            print("⚠️ No non-skip opportunity found for brief generation.")

    if args.save_intelligence:
        path = save_intelligence(cards, brief=brief)
        print(f"💾 Intelligence snapshot saved: {path}")

    if not args.quiet:
        print_intelligence(cards, brief=brief)

    return 0


def cmd_newsletter_report(args: argparse.Namespace) -> int:
    """Generate a standalone newsletter / release mining report."""
    from .intelligence.config import IntelligenceConfig
    from .intelligence.content_gap import load_existing_content
    from .intelligence.knowledge import load_knowledge_base
    from .intelligence.newsletter_mining import (
        collect_newsletter_items,
        generate_newsletter_report,
        score_newsletter_items,
    )
    config = IntelligenceConfig()
    existing_content = load_existing_content(config)
    items = score_newsletter_items(
        collect_newsletter_items(), load_knowledge_base(), existing_content=existing_content
    )
    out = Path(args.out) if args.out else None
    path = generate_newsletter_report(items, report_path=out)
    print(f"\n✅ Newsletter mining report: {path}")
    return 0


# ── Helpers ─────────────────────────────────────────────────────────────
def _looks_truncated(value: str) -> str | None:
    """Heuristics for a credential that was truncated when copied."""
    if not value:
        return None
    if "…" in value:  # the '…' ellipsis a UI inserts when eliding text
        return "contains '…' — looks like a truncated copy; re-paste the full key"
    if value.endswith("...") or value.endswith(".."):
        return "ends with '...' — likely truncated; re-paste the full key"
    if len(value) < 8:
        return f"only {len(value)} chars — looks too short to be a real key"
    return None


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
        p.add_argument("--provider", choices=LLM_PROVIDERS,
                       help="Override the LLM provider")
        p.add_argument("--model", help="Override the model id")
        p.add_argument("--max-steps", type=int, help="Max agent steps")
        p.add_argument("--dry-run", action="store_true",
                       help="Simulate publishing (no posts go live)")
        p.add_argument("--yes", "-y", action="store_true",
                       help="Skip the live-mode confirmation prompt")
        p.add_argument("--force", action="store_true",
                       help="Run even if this topic was already published")
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
    p_doctor.add_argument("--provider", choices=LLM_PROVIDERS)
    p_doctor.set_defaults(func=cmd_doctor)

    p_profiles = sub.add_parser("profiles", help="List brand profiles")
    p_profiles.set_defaults(func=cmd_profiles)

    p_wizard = sub.add_parser("wizard", help="Interactive first-time setup")
    p_wizard.set_defaults(func=cmd_wizard)

    p_learn = sub.add_parser(
        "learn", help="Build a brand profile by reading your website"
    )
    p_learn.add_argument("url", help="Your site/blog URL to learn the brand voice from")
    p_learn.add_argument("--profile", "-p", default="default", help="Profile name to write")
    p_learn.add_argument("--platforms", help="Comma-separated channels for the profile")
    p_learn.add_argument("--provider", choices=LLM_PROVIDERS)
    p_learn.add_argument("--model", help="Override the model id")
    p_learn.set_defaults(func=cmd_learn)

    p_rep = sub.add_parser(
        "repurpose", help="Turn one existing URL/file into native posts everywhere"
    )
    p_rep.add_argument("source", help="A URL or a local file (article, transcript, notes)")
    p_rep.add_argument("--profile", "-p", default="default")
    p_rep.add_argument("--provider", choices=LLM_PROVIDERS)
    p_rep.add_argument("--model")
    p_rep.add_argument("--max-steps", type=int, default=40)
    p_rep.add_argument("--dry-run", action="store_true", help="Preview, publish nothing")
    p_rep.add_argument("--yes", "-y", action="store_true", help="Skip live confirmation")
    p_rep.add_argument("--verbose", "-v", action="store_true")
    p_rep.set_defaults(func=cmd_repurpose)

    p_dash = sub.add_parser("dashboard", help="Launch the local web dashboard")
    p_dash.add_argument("--host", default="127.0.0.1", help="Bind host (default localhost)")
    p_dash.add_argument("--port", type=int, default=8800, help="Port (default 8800)")
    p_dash.set_defaults(func=cmd_dashboard)

    p_history = sub.add_parser("history", help="List previously published runs")
    p_history.add_argument("--limit", "-n", type=int, default=20, help="How many to show")
    p_history.set_defaults(func=cmd_history)

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

    p_shorts = sub.add_parser(
        "shorts",
        help="Plan, render, preview, and publish technical YouTube Shorts",
    )
    shorts_sub = p_shorts.add_subparsers(dest="shorts_command", required=True)

    p_short_plan = shorts_sub.add_parser(
        "plan",
        help="Generate short_plan.json from an article slug or Markdown file",
    )
    p_short_plan.add_argument("--article", required=True, help="Article slug or Markdown path")
    p_short_plan.add_argument("--out", help="Output plan path")
    p_short_plan.set_defaults(func=cmd_shorts_plan)

    p_short_render = shorts_sub.add_parser(
        "render",
        help="Render scene PNGs with Playwright and build an MP4",
    )
    p_short_render.add_argument("--plan", required=True, help="Path to short_plan.json")
    p_short_render.add_argument("--out", help="Output MP4 path")
    p_short_render.set_defaults(func=cmd_shorts_render)

    p_short_preview = shorts_sub.add_parser(
        "preview",
        help="Send an MP4 preview to Telegram for approval",
    )
    p_short_preview.add_argument("--video", required=True, help="Rendered MP4 path")
    p_short_preview.add_argument("--plan", help="Optional short_plan.json for title metadata")
    p_short_preview.set_defaults(func=cmd_shorts_preview)

    p_short_publish = shorts_sub.add_parser(
        "publish",
        help="Publish an approved Short to YouTube",
    )
    p_short_publish.add_argument("--provider", choices=["youtube"], required=True)
    p_short_publish.add_argument("--video", required=True, help="Rendered MP4 path")
    p_short_publish.add_argument("--plan", help="Optional short_plan.json for metadata")
    p_short_publish.add_argument("--yes", "-y", action="store_true", help="Confirm preview approval")
    p_short_publish.set_defaults(func=cmd_shorts_publish)

    # Content Intelligence Engine
    p_intelligence = sub.add_parser(
        "intelligence",
        help="Run the Content Intelligence Engine: discover and score content opportunities",
    )
    intelligence_sub = p_intelligence.add_subparsers(dest="intelligence_command", required=True)

    p_int_run = intelligence_sub.add_parser(
        "run",
        help="Run the full intelligence pipeline and write the report",
    )
    p_int_run.add_argument("--out", help="Report output path")
    p_int_run.add_argument("--top", type=int, default=10, help="Number of opportunities to include")
    p_int_run.add_argument("--min-authority", type=int, default=50, help="Minimum authority score (0-100)")
    p_int_run.add_argument("--dry-run", action="store_true", help="Run without writing the report")
    p_int_run.add_argument("--audience-live", action="store_true", help="Enable live audience data sources")
    p_int_run.add_argument("--audience-text", action="store_true", help="Enable text-file audience fallback")
    p_int_run.add_argument(
        "--audience-source",
        action="append",
        choices=["youtube", "telegram", "website"],
        help="Specific audience source to use (can be given multiple times)",
    )
    p_int_run.add_argument("--content-gap", action="store_true", help="Enable content gap detection (default on)")
    p_int_run.add_argument("--sitemap-url", help="URL to website sitemap.xml")
    p_int_run.add_argument("--existing-content-file", help="Path to local existing_content.json index")
    p_int_run.add_argument("--newsletter-mining", action="store_true", help="Enable newsletter / release mining")
    p_int_run.set_defaults(func=cmd_intelligence)


    # Newsletter mining standalone report
    p_newsletter_report = sub.add_parser(
        "newsletter-report",
        help="Generate a standalone newsletter / release mining report",
    )
    p_newsletter_report.add_argument("--out", help="Report output path")
    p_newsletter_report.set_defaults(func=cmd_newsletter_report)

    # Opportunity calendar
    p_calendar = sub.add_parser(
        "calendar",
        help="Generate a weekly content opportunity calendar",
    )
    p_calendar.add_argument("--days", type=int, default=7, help="Number of days to plan (default 7)")
    p_calendar.add_argument("--out", help="Report output path")
    p_calendar.add_argument("--top", type=int, default=20, help="Number of top opportunities to consider")
    p_calendar.add_argument("--include-newsletter", action="store_true", default=True, help="Include newsletter mining (default on)")
    p_calendar.add_argument("--include-audience", action="store_true", default=True, help="Include audience pain signals (default on)")
    p_calendar.set_defaults(func=cmd_calendar)

    # Personalized feed
    p_feed = sub.add_parser(
        "feed",
        help="Personalized AI news feed (Google Discover-style)",
    )
    p_feed.add_argument("--topic", "-t", help="Optional topic override")
    p_feed.add_argument("--profile", "-p", default="default", help="Brand profile")
    p_feed.add_argument("--limit", type=int, default=10, help="Number of items to return")
    p_feed.add_argument("--exclude-source", action="append", help="Skip a source (repeatable)")
    p_feed.add_argument("--channel", help="Override notification channel")
    p_feed.add_argument("--save", action="store_true", help="Save snapshot to content/feed/YYYY-MM-DD.json")
    p_feed.add_argument("--notify", action="store_true", help="Send top 3 items to notification channel")
    p_feed.add_argument("--post", action="store_true", help="Create social content from the top story")
    p_feed.add_argument("--llm", action="store_true", default=False, help="Use LLM for summaries (default off)")
    p_feed.add_argument("--quiet", action="store_true", help="Skip printing the feed table")
    p_feed.add_argument("--dry-run", action="store_true", help="Preview only; don't send/post")
    p_feed.add_argument("--intelligence", action="store_true", help="Run full authority→cluster→trend→opportunity pipeline")
    p_feed.add_argument("--include-seen", action="store_true", help="Include previously-seen stories in intelligence mode (demo-safe)")
    p_feed.add_argument("--brief", action="store_true", help="Generate content brief for top intelligence opportunity")
    p_feed.add_argument("--save-intelligence", action="store_true", help="Save intelligence snapshot to content/feed/intelligence/")
    p_feed.set_defaults(func=cmd_feed)

    p_social = sub.add_parser("social", help="Social publishing commands")
    p_social.add_argument("action", choices=["publish-due"], help="Action to run")
    p_social.add_argument("--dry-run", action="store_true", help="Preview scheduled posts without publishing")
    p_social.set_defaults(func=cmd_social)

    p_analytics = sub.add_parser("analytics", help="Read-only publishing analytics")
    p_analytics.add_argument("--days", type=int, default=30, help="Window in days (default 30, 0 for all time)")
    p_analytics.add_argument("--platform", default=None, help="Filter by platform")
    p_analytics.add_argument("--json", action="store_true", help="Output JSON")
    p_analytics.add_argument("--save", action="store_true", help="Save snapshot to content/analytics/")
    p_analytics.add_argument("--sync", action="store_true", help="Sync external analytics connectors (blog only for now)")
    p_analytics.add_argument("--from", dest="from_date", default=None, help="Start date YYYY-MM-DD")
    p_analytics.add_argument("--to", dest="to_date", default=None, help="End date YYYY-MM-DD")
    p_analytics.set_defaults(func=cmd_analytics)

    return parser


def cmd_social(args: argparse.Namespace) -> int:
    """Run social publishing commands."""
    from .social_drafts import publish_due_social_drafts

    result = publish_due_social_drafts(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0


def cmd_analytics(args: argparse.Namespace) -> int:
    """Read-only analytics from persisted records."""
    from .analytics import compute_analytics, export_json, save_analytics

    if args.sync:
        from .analytics_connectors.blog import sync_blog_analytics
        print(json.dumps(sync_blog_analytics(from_date=args.from_date, to_date=args.to_date), indent=2))
        return 0

    days = None if args.days == 0 else args.days
    snapshot = compute_analytics(days=days, platform_filter=args.platform)
    if args.save:
        path = save_analytics(snapshot)
        print(f"Saved: {path}")
    if args.json or not args.save:
        print(export_json(snapshot))
    return 0


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
