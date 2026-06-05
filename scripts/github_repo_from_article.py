#!/usr/bin/env python3
"""Create/update a GitHub companion repo for a published tutorial article.

The repo contains the article as README.md and extracts fenced code blocks into
snippets/ so readers have a concrete place to copy from. This is intentionally
generic: tutorial-specific repos can be improved later, but every published
tutorial gets a useful public companion repository.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests

sys.path.insert(0, os.path.expanduser("~/social-media-kit"))
from agent.config import load_env

load_env()

ROOT = Path(os.path.expanduser("~/social-media-kit"))
BASE = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
SITE = os.environ.get("BWA_SITE_URL", "https://buildwithabdallah.com").rstrip("/")
OWNER = os.environ.get("GITHUB_REPO_OWNER", "Abdallah-Tah")
VISIBILITY = os.environ.get("GITHUB_REPO_VISIBILITY", "public")

EXT = {
    "bash": "sh",
    "shell": "sh",
    "sh": "sh",
    "php": "php",
    "json": "json",
    "xml": "xml",
    "env": "env",
    "text": "txt",
    "txt": "txt",
    "markdown": "md",
    "md": "md",
    "python": "py",
    "js": "js",
    "javascript": "js",
    "ts": "ts",
    "typescript": "ts",
}


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ.get('BLOG_API_TOKEN', '')}",
        "Accept": "application/json",
    }


def fetch_article(slug: str | None, latest: bool) -> dict | None:
    if latest:
        resp = requests.get(
            f"{BASE}/posts",
            params={"per_page": 1},
            headers=_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
        return data[0] if data else None

    resp = requests.get(
        f"{BASE}/posts",
        params={"per_page": 50},
        headers=_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    for post in resp.json().get("data") or []:
        if post.get("slug") == slug:
            return post
    return None


def is_tutorial(post: dict) -> bool:
    slug = post.get("slug", "")
    body = post.get("body") or ""
    title = post.get("title", "")
    return "/tutorials/" in f"{SITE}/tutorials/{slug}" or "tutorial" in (title + body).lower()


def code_blocks(markdown: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"```([A-Za-z0-9_+-]*)\n(.*?)```", re.S)
    return [(lang.lower() or "text", code.strip() + "\n") for lang, code in pattern.findall(markdown)]


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, check=check)


def write_repo(post: dict) -> Path:
    slug = post["slug"]
    title = post["title"]
    url = f"{SITE}/tutorials/{slug}"
    repo_dir = ROOT / "content" / "repos" / slug
    snippets = repo_dir / "snippets"
    snippets.mkdir(parents=True, exist_ok=True)

    body = post.get("body") or ""
    readme = (
        f"# {title}\n\n"
        f"Companion repository for the Build With Abdallah tutorial:\n\n"
        f"{url}\n\n"
        "## Contents\n\n"
        "- `README.md` - tutorial text and source link\n"
        "- `snippets/` - code blocks extracted from the tutorial\n\n"
        "## Tutorial\n\n"
        f"{body}\n"
    )
    (repo_dir / "README.md").write_text(readme, encoding="utf-8")

    blocks = code_blocks(body)
    for i, (lang, code) in enumerate(blocks, 1):
        ext = EXT.get(lang, "txt")
        (snippets / f"{i:02d}_{lang}.{ext}").write_text(code, encoding="utf-8")

    manifest = {
        "title": title,
        "slug": slug,
        "article_url": url,
        "code_blocks": len(blocks),
        "source": "Build With Abdallah",
    }
    (repo_dir / "article.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (repo_dir / ".gitignore").write_text(".env\nvendor/\nnode_modules/\n.DS_Store\n", encoding="utf-8")
    return repo_dir


def ensure_git_repo(repo_dir: Path, repo_name: str) -> str:
    if not shutil.which("gh"):
        raise RuntimeError("gh CLI is not installed")
    if not shutil.which("git"):
        raise RuntimeError("git is not installed")

    if not (repo_dir / ".git").exists():
        run(["git", "init"], cwd=repo_dir)
    # Always commit as the repo owner (not whatever global git identity is set),
    # so GitHub attributes companion-repo commits to Abdallah-Tah.
    git_name = os.environ.get("GIT_AUTHOR_NAME", OWNER)
    git_email = os.environ.get(
        "GIT_AUTHOR_EMAIL", "96321216+Abdallah-Tah@users.noreply.github.com"
    )
    run(["git", "config", "user.name", git_name], cwd=repo_dir)
    run(["git", "config", "user.email", git_email], cwd=repo_dir)
    run(["git", "add", "README.md", "article.json", ".gitignore", "snippets"], cwd=repo_dir)
    commit = run(["git", "commit", "-m", "Add tutorial companion repo"], cwd=repo_dir, check=False)
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr).lower():
        raise RuntimeError(commit.stderr.strip() or commit.stdout.strip())

    full = f"{OWNER}/{repo_name}"
    view = run(["gh", "repo", "view", full, "--json", "url"], check=False)
    if view.returncode != 0:
        create_cmd = [
            "gh",
            "repo",
            "create",
            full,
            f"--{VISIBILITY}",
            "--source",
            str(repo_dir),
            "--remote",
            "origin",
            "--push",
            "--description",
            "Companion code snippets for a Build With Abdallah tutorial.",
        ]
        created = run(create_cmd, cwd=repo_dir)
        text = created.stdout + created.stderr
        match = re.search(r"https://github\.com/[^\s]+", text)
        return match.group(0) if match else f"https://github.com/{full}"

    url = json.loads(view.stdout)["url"]
    remotes = run(["git", "remote"], cwd=repo_dir, check=False).stdout.split()
    if "origin" not in remotes:
        run(["git", "remote", "add", "origin", f"https://github.com/{full}.git"], cwd=repo_dir)
    run(["git", "push", "-u", "origin", "HEAD"], cwd=repo_dir)
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/update a GitHub companion repo for a tutorial")
    parser.add_argument("--slug")
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args()

    post = fetch_article(args.slug, latest=args.latest or not args.slug)
    if not post:
        print("ERROR: article not found")
        return 1
    if not is_tutorial(post):
        print(f"SKIP: latest post does not look like a tutorial ({post.get('slug')})")
        return 0

    repo_name = post["slug"][:90].strip("-")
    repo_dir = write_repo(post)
    url = ensure_git_repo(repo_dir, repo_name)
    print(f"GitHub repo ready: {url}")
    print(f"Local repo: {repo_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
