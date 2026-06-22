#!/usr/bin/env bash
# Daily rules-explainer runner — LIVE (auto-publish enabled 2026-06-16).
# Renders the next vetted topic by priority and publishes it to the main
# channel (config/explainer.yaml: youtube_profile=main, channel_ready=true),
# then posts a Telegram notice. Cron slot 11:00 (clear of 08:00 daily-slate,
# 09:00 football, and the even-hour recap cron). Predictions throttled to
# 1/day (Phase 7) so this isn't starved of YouTube quota.
set -euo pipefail
KIT="${KIT:-/home/abdaltm86/social-media-kit}"
cd "$KIT"

load_env() { local f="$1" line key val; [ -f "$f" ] || return 0
  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    key="${line%%=*}"; val="${line#*=}"; val="${val%\"}"; val="${val#\"}"; export "$key=$val"
  done < "$f"; }
load_env ~/.config/social-media-kit/secrets.env
load_env ~/.config/openclaw/secrets.env
if [ -f "$HOME/.telegram-bot-token" ]; then
  TELEGRAM_BOT_TOKEN="$(tr -d '[:space:]' < "$HOME/.telegram-bot-token")"; export TELEGRAM_BOT_TOKEN TELEGRAM_TOKEN="$TELEGRAM_BOT_TOKEN"
fi
export PATH="/home/linuxbrew/.linuxbrew/bin:$PATH"

echo "[rules-daily] $(date) — render next rules explainer (Phase A: render + Telegram, no publish)"
/usr/bin/python3 "$KIT/scripts/rules_daily.py"
echo "[rules-daily] done."
