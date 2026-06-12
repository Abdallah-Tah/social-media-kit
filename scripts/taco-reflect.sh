#!/usr/bin/env bash
# Nightly Taco reflection pass. Runs only when >= 10 newly graded runs have
# accumulated since the last reflection (tracked in the journal's meta table).
# Reflection failures warn and exit 0 — this script must never break cron.

KIT="${KIT:-/home/abdaltm86/social-media-kit}"
cd "$KIT" || { echo "[taco-reflect] WARNING: cannot cd to $KIT" >&2; exit 0; }

# Load secrets the same way bwa-pitch-agent.sh does (ANTHROPIC_API_KEY).
load_env() {
  local f="$1" line key val
  [ -f "$f" ] || return 0
  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    key="${line%%=*}"
    val="${line#*=}"
    export "$key"="$val"
  done < "$f"
}
load_env "$KIT/config/secrets.env"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') taco reflect ====="
# /usr/bin/python3 — same interpreter rule as bwa-pitch-agent.sh (has requests).
/usr/bin/python3 -m agent_journal reflect --last 25 \
  || echo "[taco-reflect] WARNING: reflection exited non-zero ($?)" >&2

exit 0
