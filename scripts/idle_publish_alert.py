#!/usr/bin/env python3
"""Idle-publish alert — fires a Telegram message when a lane goes silent.

The 6 failed news runs between Aug 1 and Aug 4 went completely un-alerted
because each one logged "failed quality gate; no publish" (a soft failure)
rather than a cron-miss that the reboot watchdog catches. This script is the
complement: scheduled every hour, it scans the publisher logs for the most
recent "Published ..." line per lane and alerts when the gap exceeds a
per-lane threshold.

Logs scanned:
  - ~/logs/smkit-news.log     for "Published news: Post ID ..."
  - ~/logs/smkit-cron.log     for "Published: Post ID ..." (tutorials)
  - ~/logs/smkit-roundup.log  for "Published" (weekly roundup)

Idempotent: stores the last alert time per lane in content/last_publish_alert.json
and only re-alerts after ALERT_COOLDOWN_HOURS (default 12) per lane.
"""
import datetime
import json
import os
import re
import sys

KIT = os.path.expanduser("~/social-media-kit")
LOG_DIR = os.path.expanduser("~/logs")
sys.path.insert(0, KIT)
from agent.config import load_env  # noqa: E402

load_env()
sys.path.insert(0, os.path.join(KIT, "scripts"))

# (lane_name, log_file_basename, regex, threshold_hours)
# The regex captures the leading "YYYY-MM-DD HH:MM:SS" timestamp from the
# "===== ... run start =====" block header that wraps each publish line.
LANES = [
    ("news", "smkit-news.log", r"Published news: Post ID", 18),
    ("tutorial", "smkit-cron.log", r"Published: Post ID", 72 * 2 + 6),  # ~2 slots missed
]
ALERT_COOLDOWN_HOURS = int(os.environ.get("IDLE_ALERT_COOLDOWN_HOURS", "12"))
STATE_FILE = os.path.join(KIT, "content", "last_publish_alert.json")


def _timestamp_prefix(line: str):
    """Extract a datetime from the wrapping "===== YYYY-MM-DD HH:MM:SS ... ====="."""
    m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", line)
    if not m:
        return None
    try:
        return datetime.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}")
    except ValueError:
        return None


def last_publish_at(log_path: str, publish_marker: str):
    """Walk the log file backwards: find the most recent run-block start that
    contains a publish-marker line. Returns the run-start datetime or None.

    Logs use "===== YYYY-MM-DD HH:MM:SS <name> run start =====" block markers
    wrapping each invocation. We pair each "running" event with the publish
    line that follows it, so we attribute the timestamp correctly even when
    multiple runs share the same log file.
    """
    if not os.path.exists(log_path):
        return None
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except Exception:
        return None
    cur_start = None
    last_publish = None
    pat = re.compile(publish_marker)
    for ln in lines:
        ts = _timestamp_prefix(ln)
        if "run start" in ln and ts:
            cur_start = ts
        elif pat.search(ln) and cur_start is not None:
            last_publish = cur_start
    return last_publish


def load_state():
    try:
        return json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}
    except Exception:
        return {}


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        json.dump(state, open(STATE_FILE, "w"), indent=2)
    except Exception as e:
        print(f"⚠️ idle alert: could not persist state: {e}")


def send_alert(lane: str, hours_silent: float, last_at: datetime.datetime | None):
    last_str = last_at.strftime("%Y-%m-%d %H:%M") if last_at else "(never in this log)"
    msg = (
        f"⚠️ smkit idle: '{lane}' lane has not published in {int(hours_silent)}h "
        f"(last publish: {last_str}). Check ~/logs/smkit-{lane if lane!='tutorial' else 'cron'}.log "
        f"for quality-gate failures or upstream outages."
    )
    print(msg)
    try:
        import telegram_poster
        telegram_poster.post_message(msg)
    except Exception as e:
        print(f"   (telegram send failed: {e})")


def main():
    now = datetime.datetime.now()
    state = load_state()
    fired_any = False
    for lane, log_name, marker, threshold_h in LANES:
        log_path = os.path.join(LOG_DIR, log_name)
        last = last_publish_at(log_path, marker)
        silence_h = None
        if last is None:
            silence_h = float("inf")  # never published in the log
        else:
            silence_h = (now - last).total_seconds() / 3600.0
        if silence_h <= threshold_h:
            continue
        # Cooldown per lane so we don't spam every hour.
        last_alert_str = state.get(lane, {}).get("last_alert_at")
        if last_alert_str:
            try:
                last_alert = datetime.datetime.fromisoformat(last_alert_str)
                if (now - last_alert).total_seconds() / 3600.0 < ALERT_COOLDOWN_HOURS:
                    continue
            except ValueError:
                pass
        send_alert(lane, silence_h if silence_h != float("inf") else -1, last)
        state[lane] = {
            "last_alert_at": now.isoformat(),
            "last_publish_at": last.isoformat() if last else None,
            "silence_hours": silence_h if silence_h != float("inf") else None,
        }
        fired_any = True
    if fired_any:
        save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
