#!/usr/bin/env python3
"""Seven-day sourcing report — the evidence for raising NEWS_MIN_SOURCES.

`NEWS_MIN_SOURCES` ships at 1. Measured 2026-08-01, 83% of the existing corpus
cited exactly one host, so enforcing 2 then would have blocked five runs in six.
The story picker and writer now ask for corroboration; this report says whether
that actually changed, so the decision is made on data rather than hope.

Usage:
    /usr/bin/python3 scripts/sourcing_report.py            # last 7 days
    /usr/bin/python3 scripts/sourcing_report.py --days 14
    /usr/bin/python3 scripts/sourcing_report.py --json
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import sys

KIT = os.path.expanduser("~/social-media-kit")
sys.path.insert(0, KIT)
sys.path.insert(0, os.path.join(KIT, "scripts"))

import content_formats as CF  # noqa: E402

NEWS_LOG = os.path.expanduser("~/logs/smkit-news.log")
DRAFTS = os.path.join(KIT, "content", "drafts")

# Enough runs to trust the rate rather than a lucky streak.
MIN_RUNS_FOR_A_CALL = 8
# Enforcing 2 is safe when nearly every article already clears it. Below this,
# flipping the switch converts working runs into blocked slots.
SAFE_TWO_SOURCE_RATE = 0.85


def _articles(days):
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    for path in sorted(glob.glob(os.path.join(DRAFTS, "*_news_*.md"))):
        stamp = os.path.basename(path)[:10]
        try:
            when = datetime.date.fromisoformat(stamp)
        except ValueError:
            continue
        if when < cutoff:
            continue
        body = open(path, encoding="utf-8", errors="ignore").read()
        title = body.splitlines()[0].lstrip("# ").strip() if body else ""
        urls = CF.source_urls(body)
        hosts = {CF._host(u) for u in urls if u}
        primary = {h for h in hosts if CF._looks_authoritative(h, title)}
        background = {h for h in hosts
                      if any(b in h for b in CF.BACKGROUND_ONLY_HOSTS)}
        yield {
            "date": stamp,
            "slug": os.path.basename(path).split("_news_")[-1][:-3],
            "title": title,
            "hosts": sorted(hosts),
            "distinct_hosts": len(hosts),
            "primary_hosts": len(primary),
            # "Legitimate" = distinct, and not an encyclopedia/aggregator.
            "legitimate_hosts": len(hosts - background),
            "issues": CF.substance_issues(title, body),
        }


def _run_outcomes(days):
    """Parse the cron log for what each scheduled run actually did."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    try:
        log = open(NEWS_LOG, encoding="utf-8", errors="ignore").read()
    except OSError:
        return []
    parts = re.split(r"===== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) news run start =====", log)
    runs = []
    for i in range(1, len(parts), 2):
        ts, block = parts[i], parts[i + 1]
        if ts[:10] < cutoff:
            continue
        issues = re.search(r"quality issues: (.+)", block)
        runs.append({
            "ts": ts,
            "published": "Published news:" in block,
            "blocked": "failed quality gate" in block,
            "ungrounded": "refusing to write an ungrounded" in block,
            "no_candidates": "not enough grounded candidates" in block,
            # Every failed search is a story the picker never got to consider.
            "search_failures": block.count("Search returned no results"),
            "issues": issues.group(1) if issues else "",
        })
    return runs


def build(days):
    arts = list(_articles(days))
    runs = _run_outcomes(days)
    n = len(arts) or 1
    sourcing_blocked = [a for a in arts if any(
        k in i for a_ in [a] for i in a_["issues"]
        for k in ("sole source", "no primary source", "NEWS_MIN_SOURCES",
                  "no sources listed"))]
    return {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "window_days": days,
        "articles": len(arts),
        "runs": len(runs),
        "current_min_sources": CF.MIN_SOURCES,
        "metrics": {
            "mean_distinct_hosts": round(sum(a["distinct_hosts"] for a in arts) / n, 2),
            "mean_primary_hosts": round(sum(a["primary_hosts"] for a in arts) / n, 2),
            "articles_with_2plus_legit": sum(1 for a in arts if a["legitimate_hosts"] >= 2),
            "articles_with_2plus_legit_pct": round(
                100 * sum(1 for a in arts if a["legitimate_hosts"] >= 2) / n, 1),
            "blocked_for_sourcing": len(sourcing_blocked),
            "source_discovery_failures": sum(r["search_failures"] for r in runs),
            "runs_with_search_failures": sum(1 for r in runs if r["search_failures"]),
            "runs_published": sum(1 for r in runs if r["published"]),
            "runs_blocked": sum(1 for r in runs if r["blocked"]),
            "runs_ungrounded": sum(1 for r in runs if r["ungrounded"]),
        },
        "articles_detail": arts,
        "recommendation": _recommend(arts, runs),
    }


def _recommend(arts, runs):
    """Should NEWS_MIN_SOURCES go to 2? Say why, either way."""
    if CF.MIN_SOURCES >= 2:
        return {"verdict": "already enforced",
                "detail": f"NEWS_MIN_SOURCES is {CF.MIN_SOURCES}."}
    if len(runs) < MIN_RUNS_FOR_A_CALL:
        return {"verdict": "not enough data",
                "detail": f"{len(runs)} runs in window; need {MIN_RUNS_FOR_A_CALL}. "
                          "Re-run this report after a full week."}
    if not arts:
        return {"verdict": "not enough data", "detail": "no articles in window."}
    rate = sum(1 for a in arts if a["legitimate_hosts"] >= 2) / len(arts)
    would_block = sum(1 for a in arts if a["legitimate_hosts"] < 2)
    if rate >= SAFE_TWO_SOURCE_RATE:
        return {
            "verdict": "SAFE to set NEWS_MIN_SOURCES=2",
            "detail": (f"{rate:.0%} of articles already cite 2+ legitimate hosts "
                       f"(threshold {SAFE_TWO_SOURCE_RATE:.0%}). Enforcing would have "
                       f"blocked {would_block} of {len(arts)}."),
        }
    return {
        "verdict": "NOT safe yet — keep NEWS_MIN_SOURCES=1",
        "detail": (f"only {rate:.0%} of articles cite 2+ legitimate hosts "
                   f"(need {SAFE_TWO_SOURCE_RATE:.0%}). Enforcing now would block "
                   f"{would_block} of {len(arts)} articles. The picker is not yet "
                   "finding corroboration reliably — check source_discovery_failures "
                   "first; a Brave API key is the usual fix."),
    }


def render(rep):
    m = rep["metrics"]
    out = [
        f"Sourcing report — last {rep['window_days']} days   ({rep['generated']})",
        f"  NEWS_MIN_SOURCES currently: {rep['current_min_sources']}",
        "",
        f"  articles analysed                 {rep['articles']}",
        f"  scheduled runs                    {rep['runs']}"
        f"   (published {m['runs_published']}, blocked {m['runs_blocked']},"
        f" ungrounded {m['runs_ungrounded']})",
        "",
        "  SOURCING",
        f"    mean distinct source hosts      {m['mean_distinct_hosts']}",
        f"    mean primary (official) hosts   {m['mean_primary_hosts']}",
        f"    articles with 2+ legit sources  {m['articles_with_2plus_legit']}"
        f" / {rep['articles']}  ({m['articles_with_2plus_legit_pct']}%)",
        f"    blocked for insufficient source {m['blocked_for_sourcing']}",
        f"    source-discovery failures       {m['source_discovery_failures']}"
        f"   (across {m['runs_with_search_failures']} runs)",
        "",
        "  PER ARTICLE",
    ]
    for a in rep["articles_detail"]:
        flag = "" if not a["issues"] else "  <- " + a["issues"][0][:52]
        out.append(f"    {a['date']}  hosts={a['distinct_hosts']} "
                   f"primary={a['primary_hosts']}  {a['slug'][:40]}{flag}")
    r = rep["recommendation"]
    out += ["", f"  RECOMMENDATION: {r['verdict']}", f"    {r['detail']}"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = build(args.days)
    print(json.dumps(rep, indent=2) if args.json else render(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
