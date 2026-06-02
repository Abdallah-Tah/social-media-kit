#!/usr/bin/env bash
# Build a clean, sellable zip of the Social Media Agent for Gumroad.
# Excludes secrets, git history, caches, generated content, and node_modules.
#
# Usage:  bash scripts/make_release.sh
# Output: dist/social-media-agent-<version>.zip
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

VERSION="$(python3 -c 'import agent; print(agent.__version__)' 2>/dev/null || echo 0.0.0)"
NAME="social-media-agent-${VERSION}"
TMP="$(mktemp -d)"
STAGE="${TMP}/${NAME}"
mkdir -p "$STAGE"

echo "📦 Building ${NAME}.zip ..."

# Export ONLY git-tracked files, so no untracked local secret (a stray .env,
# PEM key, scratch export, etc.) can ever land in the release archive.
git -C "$ROOT" archive --format=tar HEAD | tar -xf - -C "$STAGE"
rm -rf \
  "$STAGE/.git" \
  "$STAGE/dist" \
  "$STAGE/node_modules" \
  "$STAGE/.venv" \
  "$STAGE/content/raw" "$STAGE/content/drafts" "$STAGE/content/assets"
find "$STAGE" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -type f -name '*.pyc' -delete 2>/dev/null || true
# Safety: never ship a real secrets file or the consumed-queue archive.
rm -f "$STAGE/config/secrets.env" "$STAGE/config/topics.txt.done"

mkdir -p "$ROOT/dist"
rm -f "$ROOT/dist/${NAME}.zip"
( cd "$TMP" && zip -rq "$ROOT/dist/${NAME}.zip" "${NAME}" )
rm -rf "$TMP"

echo "✅ dist/${NAME}.zip"
echo "   Contents:"
unzip -l "$ROOT/dist/${NAME}.zip" | tail -n +2 | head -n 20

# Final guard: confirm no secrets leaked into the archive.
if unzip -l "$ROOT/dist/${NAME}.zip" | grep -q 'secrets.env$'; then
  echo "❌ secrets.env found in archive — aborting!"; exit 1
fi
echo "🔒 Verified: no secrets.env in the archive."
