#!/usr/bin/env bash
# Build With Abdallah quality-gated publish run.
# Intended for cron. Publishes without approval when validation passes, then
# notifies Telegram with exactly what happened.
set -euo pipefail

KIT="${KIT:-/home/abdaltm86/social-media-kit}"
SMKIT="${SMKIT:-/home/abdaltm86/.local/bin/smkit}"

cd "$KIT"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') publish run start ====="

# Keep Telegram notifications in the same chat/topic used by the old
# auto-publish cron. The token file wins over stale inherited env values.
if [ -f "$HOME/.telegram-bot-token" ]; then
  TELEGRAM_BOT_TOKEN="$(tr -d '[:space:]' < "$HOME/.telegram-bot-token")"
  export TELEGRAM_BOT_TOKEN
fi
export TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:--1003948211258}"
export TELEGRAM_MESSAGE_THREAD_ID="${TELEGRAM_MESSAGE_THREAD_ID:-14119}"

latest_id() {
  python3 - <<'PY'
import os, sys, requests
sys.path.insert(0, "/home/abdaltm86/social-media-kit")
from agent.config import load_env
load_env()
base = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
tok = os.environ.get("BLOG_API_TOKEN", "")
try:
    r = requests.get(
        f"{base}/posts",
        params={"per_page": 1},
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
        timeout=20,
    )
    data = r.json().get("data") or []
    print(data[0].get("id", "") if data else "")
except Exception:
    print("")
PY
}

latest_info() {
  python3 - <<'PY'
import os, sys, requests
sys.path.insert(0, "/home/abdaltm86/social-media-kit")
from agent.config import load_env
load_env()
base = os.environ.get("BLOG_API_URL", "https://buildwithabdallah.com/api/v1").rstrip("/")
tok = os.environ.get("BLOG_API_TOKEN", "")
try:
    r = requests.get(
        f"{base}/posts",
        params={"per_page": 1},
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
        timeout=20,
    )
    p = (r.json().get("data") or [{}])[0]
    print((p.get("title") or "") + "|" + (p.get("slug") or ""))
except Exception:
    print("|")
PY
}

notify_telegram() {
  local text="$1"
  if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
    curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
      --data-urlencode "message_thread_id=${TELEGRAM_MESSAGE_THREAD_ID}" \
      --data-urlencode "text=${text}" >/dev/null || true
  fi
}

GOAL="$(cat <<'EOF'
You are the Build With Abdallah senior technical editor.

Create one professional developer article for buildwithabdallah.com and publish it if validation passes. Do not ask for approval. After the run, notify Telegram with what was published, posted, skipped, or blocked.

MANDATORY TOOL RULE:
You must call save_article with the full Markdown article. Then call generate_cover to create an original Build With Abdallah cover. Use source articles as inspiration only; do not pass source_url unless the image license is clearly safe for reuse. If validation passes, call publish_blog with the saved draft path and the cover URL/path returned by generate_cover. Then post to every enabled public channel in the profile. Then call post_telegram with the article title, URL or slug, cover source, channels posted, channels skipped, and validation summary. Do not finish by printing the article in chat. A final response without save_article is a failed run.

CONTENT MODE:
Choose exactly one:
1. Hands-on tutorial
2. Developer news analysis
3. Tool/framework review
4. Production workflow case study

Prefer hands-on tutorials unless there is important recent developer news from a primary source. Do not mix modes in one article.

TOPIC RULES:
- Choose one specific topic only.
- Do not write broad surveys.
- Do not repeat an existing article.
- Check https://buildwithabdallah.com/sitemap.xml before writing.
- The topic must fit one of these clusters: Laravel/PHP, Python, React/Next.js, Vue/Nuxt, .NET/C#, C++, AI agents, automation, developer tools.
- For Laravel/PHP news, check https://laravel-news.com and official project/package sources before using secondary commentary.
- For tutorials, prefer demonstrating one useful package/library/framework feature. Show what the package does, when a developer would use it, and build a small working example around it.

QUALITY RULES FOR TUTORIALS:
- Minimum 1,500 words.
- Build one complete working project end to end.
- Center the tutorial on one package/library/framework feature when possible, and demonstrate the package's actual value with a practical use case.
- Include real commands.
- Include real code blocks with language labels.
- Include project structure.
- Explain each major code block.
- Include common errors and fixes.
- Include a final complete example.
- No fake code, placeholder code, vague install steps, or marketing filler.

QUALITY RULES FOR NEWS:
- Use primary sources first.
- Explain what changed, why it matters, who should care, and what developers should do next.
- Do not exaggerate.
- Include sources.

WRITING STYLE:
- Write like a senior developer explaining a real implementation.
- Use clear, direct English.
- Avoid generic AI-sounding phrases.
- Do not say "dive into", "unlock", "seamlessly", "elevate", "robust", "game changer", or "revolutionary".
- Do not overuse emojis.

COVER IMAGE RULES:
Create an original Build With Abdallah cover with readable programmatic text. Use source images only as inspiration unless the license is clearly safe. Do not reuse third-party publication images, Laravel News images, framework website OG images, or any image with another publication's logo. The final image must include the article title or a concise version of it, the main technology/package name, and a concrete visual concept from the article. Do not use AI-generated screenshots, fake UI, fake code, non-English gibberish, generic abstract AI backgrounds, generic AI waves, or glowing robot art.

SOCIAL COPY RULES:
Write separate social copy for enabled public channels and post it after the article is live. The copy must start with the specific problem or build outcome, list what the reader will learn, include the article link or slug when known, avoid generic marketing language, and use 3 to 6 relevant hashtags.

VALIDATION BEFORE PUBLISH:
Before finishing, verify:
- article is at least 1,500 words
- tutorial has at least 5 real code blocks when the chosen mode is tutorial
- sources are real URLs
- image is original Build With Abdallah branded artwork, or a third-party image with clearly safe reuse rights
- social copy is specific and not generic
- slug is not already in the sitemap

If any validation fails, do not publish publicly. Save the local draft anyway and notify Telegram with the failure reasons.
If validation passes, publish the blog post publicly, post enabled social channels, and notify Telegram with what was done. No approval is required.
EOF
)"

OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT
BEFORE="$(latest_id)"

"$SMKIT" run \
  --provider openai --model gpt-4o \
  --max-steps 50 \
  --goal "$GOAL" \
  --profile live-auto \
  --yes | tee "$OUT"

if ! grep -q "Saved draft to" "$OUT"; then
  MSG="Publish run failed quality gate: the agent finished without saving a draft. No public publish happened. Check /home/abdaltm86/logs/smkit-cron.log for the failed run."
  echo "$MSG"
  notify_telegram "$MSG"
  exit 1
fi

AFTER="$(latest_id)"
if [ -n "$AFTER" ] && [ "$AFTER" != "$BEFORE" ]; then
  INFO="$(latest_info)"
  TITLE="${INFO%%|*}"
  SLUG="${INFO##*|}"
  URL="https://buildwithabdallah.com/tutorials/$SLUG"

  GH="✅ GitHub"
  GH_OUT="$(python3 "$KIT/scripts/github_repo_from_article.py" --latest 2>&1)" \
    || { GH="⚠️ GitHub failed"; echo "$GH_OUT"; }
  GH_URL="$(printf '%s\n' "$GH_OUT" | sed -n 's/^GitHub repo ready: //p' | tail -1)"

  LI="✅ LinkedIn"
  python3 "$KIT/scripts/linkedin_from_article.py" --latest \
    || { LI="⚠️ LinkedIn failed"; echo "linkedin failed"; }

  REEL="✅ Reel"
  REEL_OUT="$(python3 "$KIT/scripts/reel_from_article.py" --latest --publish 2>&1)" \
    || { REEL="⚠️ Reel failed"; echo "$REEL_OUT"; echo "reel failed"; }
  [ -z "${REEL_OUT:-}" ] || echo "$REEL_OUT"

  YT="✅ YouTube"
  if [ "$REEL" = "✅ Reel" ]; then
    REEL_PATH="$KIT/content/assets/reel_${SLUG:0:40}.mp4"
    YT_TITLE="${TITLE:0:82} #Shorts"
    YT_DESC="${TITLE}
${URL}

#Shorts #BuildWithAbdallah"
    python3 "$KIT/scripts/youtube_shorts_publisher.py" upload \
      --video "$REEL_PATH" \
      --title "$YT_TITLE" \
      --description "$YT_DESC" \
      --privacy public \
      --tags "BuildWithAbdallah,Programming,Tutorial,Shorts" \
      --category-id 28 \
      || { YT="⚠️ YouTube failed"; echo "youtube failed"; }
  else
    YT="⚠️ YouTube skipped"
  fi

  notify_telegram "Post-publish automation complete:
${TITLE}
${URL}
${GH}${GH_URL:+: ${GH_URL}}
${LI}
${REEL}
${YT}"
else
  echo "No new article detected after run; skipping GitHub, LinkedIn, and Reel."
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') publish run end ====="
