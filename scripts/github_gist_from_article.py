#!/usr/bin/env python3
"""Create a GitHub Gist snapshot of a published tutorial.

Instead of a full companion repo, each tutorial gets one public Gist containing:
  - TUTORIAL.md  : the full tutorial text + canonical link
  - NN-<lang>.<ext> : every fenced code block, extracted as a runnable file

The Gist is created under the authenticated GitHub account (Abdallah-Tah) via
the gh CLI. Prints "GitHub gist ready: <url>" for the cron to capture.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, os.path.expanduser("~/social-media-kit"))
from agent.config import load_env
load_env()

BASE = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
SITE = os.environ.get("BWA_SITE_URL", "https://buildwithabdallah.com").rstrip("/")

EXT = {
    "bash": "sh", "shell": "sh", "sh": "sh", "console": "sh", "zsh": "sh",
    "php": "php", "blade": "blade.php", "json": "json", "yaml": "yml", "yml": "yml",
    "xml": "xml", "html": "html", "css": "css", "scss": "scss", "env": "env",
    "python": "py", "py": "py", "js": "js", "javascript": "js", "jsx": "jsx",
    "ts": "ts", "typescript": "ts", "tsx": "tsx", "vue": "vue", "go": "go",
    "rust": "rs", "rs": "rs", "java": "java", "csharp": "cs", "cs": "cs",
    "cpp": "cpp", "c++": "cpp", "c": "c", "sql": "sql", "ruby": "rb",
    "dockerfile": "Dockerfile", "text": "txt", "txt": "txt", "md": "md", "markdown": "md",
}


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ.get('BLOG_API_TOKEN', '')}", "Accept": "application/json"}


def fetch_article(slug: str | None, latest: bool) -> dict | None:
    if latest:
        d = requests.get(f"{BASE}/posts", params={"per_page": 1}, headers=_headers(), timeout=20).json().get("data") or []
        return d[0] if d else None
    for post in requests.get(f"{BASE}/posts", params={"per_page": 50}, headers=_headers(), timeout=20).json().get("data") or []:
        if post.get("slug") == slug:
            return post
    return None


def is_tutorial(post: dict) -> bool:
    return "tutorial" in (post.get("title", "") + (post.get("body") or "")).lower()


def _infer_lang(code: str) -> str:
    """Guess a language for an unlabeled fenced block from its content."""
    c = code.strip()
    low = c.lower()
    if c.startswith("<?php") or ("->" in c and "$" in c and "function" in low):
        return "php"
    if "<template>" in low or "<script setup" in low:
        return "vue"
    if re.match(r"^(npm |pnpm |yarn |npx |pip |pip3 |python -m |composer |php artisan |"
                r"cd |mkdir|git |dotnet |cargo |go |curl |export |source |sudo |brew |apt )", c):
        return "bash"
    if "#include" in low:
        return "cpp"
    if "using system" in low or "namespace " in low or re.search(r"public (class|record|interface)", c):
        return "csharp"
    if c.startswith("{") and '"' in c and ":" in c:
        return "json"
    if re.search(r"^\s*(def |class |import |from )\w", c, re.M) and "function" not in low and "const " not in low:
        return "python"
    if re.search(r"\b(const |let |function |=>|export (default|const|function)|import .+ from)", c):
        return "ts" if re.search(r":\s*(string|number|boolean|any)\b|interface \w", c) else "js"
    if re.search(r"\bselect\b.+\bfrom\b", low):
        return "sql"
    if c.startswith(("├", "└", "│")) or re.search(r"[│├└]─", c):
        return "text"
    return "text"


def unwrap_markdown_fence(s: str) -> str:
    """Strip an outer ```markdown ... ``` wrapper the writer sometimes adds."""
    s = (s or "").strip()
    m = re.match(r"^```(markdown|md)?[ \t]*\n", s)
    if m and s.rstrip().endswith("```"):
        inner = s[m.end():].rstrip()[:-3].strip()
        if re.search(r"^#{1,4}\s", inner, re.M):
            return inner
    return s


def code_blocks(markdown: str) -> list[tuple[str, str]]:
    markdown = unwrap_markdown_fence(markdown)
    pat = re.compile(r"```([A-Za-z0-9_.+-]*)\n(.*?)```", re.S)
    out = []
    for lang, code in pat.findall(markdown):
        if not code.strip():
            continue  # gists reject blank files
        lang = lang.lower()
        body = code.strip() + "\n"
        if not lang or lang in ("text", "txt", "plaintext", "plain"):
            lang = _infer_lang(body)
        out.append((lang, body))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Create a GitHub Gist snapshot of a tutorial")
    ap.add_argument("--slug")
    ap.add_argument("--latest", action="store_true")
    args = ap.parse_args()

    if not __import__("shutil").which("gh"):
        print("ERROR: gh CLI not installed")
        return 1

    post = fetch_article(args.slug, latest=args.latest or not args.slug)
    if not post:
        print("ERROR: article not found")
        return 1
    if not is_tutorial(post):
        print(f"SKIP: latest post is not a tutorial ({post.get('slug')})")
        return 0

    slug, title = post["slug"], post["title"]
    url = f"{SITE}/tutorials/{slug}"
    body = post.get("body") or ""
    blocks = code_blocks(body)
    if not blocks:
        print(f"SKIP: no code blocks to snapshot ({slug})")
        return 0

    work = Path(tempfile.mkdtemp(prefix="gist_"))
    files: list[Path] = []

    # The tutorial snapshot itself.
    tut = work / "TUTORIAL.md"
    tut.write_text(
        f"# {title}\n\n"
        f"Code snapshot for the Build With Abdallah tutorial:\n{url}\n\n"
        f"---\n\n{body}\n",
        encoding="utf-8",
    )
    files.append(tut)

    # Each code block as its own runnable file (Gists are flat — no folders).
    seen: dict[str, int] = {}
    for i, (lang, code) in enumerate(blocks, 1):
        ext = EXT.get(lang, "txt")
        name = f"{i:02d}-{(lang or 'code')}.{ext}" if ext != "Dockerfile" else f"{i:02d}-Dockerfile"
        files.append(work / name)
        files[-1].write_text(code, encoding="utf-8")

    desc = f"{title} — code snapshot · {url}"
    cmd = ["gh", "gist", "create", "--public", "--desc", desc] + [str(p) for p in files]
    res = subprocess.run(cmd, text=True, capture_output=True)
    out = (res.stdout + res.stderr).strip()
    m = re.search(r"https://gist\.github\.com/\S+", out)
    if res.returncode != 0 or not m:
        print(f"ERROR: gist create failed: {out[:300]}")
        return 1
    print(f"GitHub gist ready: {m.group(0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
