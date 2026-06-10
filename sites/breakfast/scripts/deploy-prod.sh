#!/usr/bin/env bash
# DEPRECATED: rsync в /home/makc/Apps/sites/breakfast больше не используется.
# Актуальный деплой: git push (Forge) → git pull + docker compose up (Продагент).
# См. Readme/sites-architecture.md и sites/breakfast/README.md
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "⚠ deploy-prod.sh (rsync) устарел." >&2
echo "" >&2
echo "Конвейер:" >&2
echo "  1. Forge: commit + push origin main" >&2
echo "  2. [ПРОД] cd /home/makc/Apps/island && git pull --ff-only origin main" >&2
echo "  3. [ПРОД] docker compose up -d --build" >&2
echo "" >&2

if [[ "${1:-}" == "--bump-only" ]]; then
  echo "→ bump version.json only"
  "$ROOT/scripts/bump-version.sh"
  exit 0
fi

echo "Для bump версии без rsync: $0 --bump-only" >&2
exit 1
