#!/usr/bin/env python3
"""Version-claim sanity check — protect credibility from wrong release claims.

Catches the class of error that put "C# 15 is part of .NET 8" live:
  - deterministic check of the stable C#/.NET version mapping, and
  - an LLM fact-check pass for wrong version mappings, preview-as-stable claims,
    and old features presented as new.

If a published post fails, it is set back to DRAFT (unpublished) and the issues
are printed. Exit code 2 = held (cron should skip social + notify); 0 = OK.

  python3 scripts/version_sanity_check.py --latest
  python3 scripts/version_sanity_check.py --id 64
"""
import os
import re
import sys
import json
import argparse
import requests
from pathlib import Path

ROOT = Path(os.environ.get("SMKIT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
from agent.config import load_env
load_env()
sys.path.insert(0, str(ROOT / "scripts"))
import datetime
try:
    import content_research as CR  # SearXNG-backed web search
except Exception:
    CR = None

TECHS = (r"(\.NET|C#|Laravel|PHP|React|Next\.?js|Vue|Nuxt|Node\.?js|Node|Python|Angular|"
         r"TypeScript|Svelte|Rust|Go|Java|Spring|Django|Flask|FastAPI|Symfony|Tailwind|Express)")

BASE = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
KNOWN_FACTS = ("Stable C#/.NET mapping: C# 12 = .NET 8, C# 13 = .NET 9, C# 14 = .NET 10, "
               "C# 15 targets .NET 11 and is in PREVIEW (not shipped/stable).")
# Stable C# -> .NET major mapping for the deterministic check.
CS_NET = {"12": "8", "13": "9", "14": "10", "15": "11"}


def _h(json_ct=False):
    h = {"Authorization": f"Bearer {os.environ.get('BLOG_API_TOKEN','')}", "Accept": "application/json"}
    if json_ct:
        h["Content-Type"] = "application/json"
    return h


def fetch(pid=None):
    if pid:
        return requests.get(f"{BASE}/posts/{pid}", headers=_h(), timeout=20).json().get("data")
    d = requests.get(f"{BASE}/posts", params={"per_page": 1}, headers=_h(), timeout=20).json().get("data", [])
    return d[0] if d else None


def deterministic_issues(body):
    issues, low = [], (body or "").lower()
    for m in re.finditer(r"c#\s*(\d\d)\b", low):
        ver = m.group(1)
        if ver not in CS_NET:
            continue
        seg = low[m.start():m.start() + 140]
        net = re.search(r"\.net\s*(\d{1,2})\b", seg)
        if net and net.group(1) != CS_NET[ver]:
            issues.append(f"Says C# {ver} with .NET {net.group(1)} (correct: .NET {CS_NET[ver]}).")
        if ver == "15" and "preview" not in seg:
            issues.append("Refers to C# 15 without marking it as preview.")
    return issues


# NOTE: a general LLM fact-check is intentionally NOT used here. The writing model's
# training cutoff predates current releases (e.g. C# 14 / .NET 10), so it both misses
# new errors AND flags correct current facts as wrong — the very problem that caused the
# original bad article. We only assert facts we KNOW are stable, via the table below.

# Stable, hand-maintained version facts. Extend as needed; never trust model memory here.
PREVIEW_VERSIONS = {"c# 15", "csharp 15"}  # not yet shipped/stable as of 2026-06


def _extract_claims(text):
    """Find distinct '<Tech> <version>' claims in the article."""
    pairs = re.findall(rf"(?<![A-Za-z0-9]){TECHS}\s*v?\.?\s*(\d+(?:\.\d+)?)\b", text or "", re.I)
    seen = {}
    for tech, ver in pairs:
        key = tech.lower().replace(".", "").replace("js", "")
        seen.setdefault(key, (tech.strip(), ver))
    return list(seen.values())[:4]


def web_grounded_issues(title, body):
    """SOFT check: verify version claims against LIVE web results, not model memory.

    Conservative — only flags a claim the search results CLEARLY contradict. Returns
    notes for human review; it does NOT unpublish (avoids false-positive thrash)."""
    if CR is None or not os.environ.get("OPENAI_API_KEY"):
        return []
    claims = _extract_claims(f"{title} {body}")
    if not claims:
        return []
    year = datetime.date.today().year
    facts = []
    for tech, _ in claims:
        try:
            for r in CR.web_search(f"latest stable {tech} version {year}", count=4):
                if r.get("title"):
                    facts.append(f"- {r['title']} ({r.get('url','')[:50]})")
        except Exception:
            pass
    if not facts:
        return []
    claim_str = ", ".join(f"{t} {v}" for t, v in claims)
    prompt = (
        "Check a tutorial's software-version claims against the web results below (current reality; "
        "ignore your own training knowledge). The article uses these versions: "
        f"{claim_str}.\n"
        "Flag a claim ONLY when a result EXPLICITLY contradicts it — i.e. a result clearly states the "
        "current/latest version is LOWER than the claimed one, OR explicitly calls the claimed version "
        "preview/unreleased/not-yet-available. You MUST quote the exact contradicting result text in your "
        "issue. NEVER flag just because a version is not mentioned or 'not verified' — absence of evidence "
        "is NOT a contradiction; in that case return no issues. When in doubt, return no issues.\n"
        'Return STRICT JSON: {"issues": ["<concern> — evidence: \"<quoted result text>\"", ...]} '
        "(empty list if nothing is explicitly contradicted).\n\n"
        f"WEB RESULTS:\n" + "\n".join(facts[:16]) + f"\n\nARTICLE EXCERPT:\n{(body or '')[:3000]}"
    )
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.0, "response_format": {"type": "json_object"}, "max_tokens": 400},
            timeout=90,
        )
        if r.ok:
            return [str(i) for i in json.loads(r.json()["choices"][0]["message"]["content"]).get("issues", [])][:5]
    except Exception as e:
        print(f"⚠️ web-grounded check skipped ({e})")
    return []


def unpublish(pid):
    """Set a post back to draft. Tries the fields the API accepts."""
    for payload in ({"status": "draft"}, {"publish": False}):
        r = requests.patch(f"{BASE}/posts/{pid}", headers=_h(True), json=payload, timeout=30)
        if r.ok:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--latest", action="store_true")
    args = ap.parse_args()

    p = fetch(args.id)
    if not p:
        print("version-check: no post found")
        return 0
    pid, title, body = p["id"], p.get("title", ""), p.get("body") or ""

    issues = deterministic_issues(body)
    # de-dup similar
    seen, uniq = set(), []
    for i in issues:
        k = i.lower()[:40]
        if k not in seen:
            seen.add(k); uniq.append(i)

    if uniq:
        held = unpublish(pid)
        print(f"VERSION-CHECK FAILED for id {pid} ({title[:50]}). "
              f"{'Unpublished (draft).' if held else 'Could NOT unpublish — manual review needed.'}")
        for i in uniq:
            print(f"  - {i}")
        # Emit a marker the cron can grep, plus a Telegram-ready summary.
        print("VERSION_HELD=1")
        print("HELD_REASON=" + " | ".join(uniq))
        return 2

    # Soft, web-grounded review (post stays live; just flag for a human look).
    soft = web_grounded_issues(title, body)
    if soft:
        print(f"version-check: id {pid} published, but FLAGGED for review:")
        for s in soft:
            print(f"  - {s}")
        print("REVIEW_NOTE=" + " | ".join(soft))
        return 0

    print(f"version-check OK for id {pid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
