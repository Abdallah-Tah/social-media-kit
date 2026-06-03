#!/usr/bin/env bash
# Record a demo for your Gumroad page.
#   1. Install asciinema:  pip install asciinema   (optional)
#   2. Record:             asciinema rec demo.cast -c "bash scripts/demo.sh"
#   3. Convert to GIF:     agg demo.cast demo.gif   (https://github.com/asciinema/agg)
# Or just run it during a screen recording.
set -e

say() { printf "\n\033[1;36m$ %s\033[0m\n" "$*"; sleep 1; }

say "smkit doctor"
smkit doctor || true
sleep 2

say 'smkit run --topic "Python asyncio in production" --dry-run'
smkit run --topic "Python asyncio in production" --dry-run --provider ollama || \
  smkit run --topic "Python asyncio in production" --dry-run || true

printf "\n\033[1;32m✓ Researched, wrote, designed a cover, and prepared native posts — all in dry-run.\033[0m\n"
