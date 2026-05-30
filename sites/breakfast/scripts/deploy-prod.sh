#!/usr/bin/env bash
# Деплой лендинга «Завтрак» на прод (rsync). Требует SSH на makc@188.225.44.48
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${BREAKFAST_DEPLOY_HOST:-makc@188.225.44.48}"
REMOTE="${BREAKFAST_DEPLOY_PATH:-/home/makc/Apps/sites/breakfast}"

if ! git -C "$ROOT/.." rev-parse --git-dir >/dev/null 2>&1; then
  echo "✗ Git не найден в web-app — деплой только после push в main" >&2
  exit 1
fi

branch="$(git -C "$ROOT/.." rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
if [[ "$branch" != "main" ]]; then
  echo "⚠ Ветка $branch — золотой стандарт: deploy только с main после push" >&2
fi

echo "→ bump version.json"
NEW="$("$ROOT/scripts/bump-version.sh")"
echo "→ build v.$NEW"

RSYNC=(rsync -avz --delete-excluded)
for path in version.json index.html css/main.css js/sveta-fsm.js js/main.js; do
  if [[ -f "$ROOT/$path" ]]; then
    case "$path" in
      css/*) dest="$REMOTE/css/" ;;
      js/*) dest="$REMOTE/js/" ;;
      *) dest="$REMOTE/" ;;
    esac
    echo "→ $path → $dest"
    "${RSYNC[@]}" "$ROOT/$path" "$HOST:$dest"
  fi
done

echo "✓ Deployed breakfast build v.$NEW to $HOST:$REMOTE"
