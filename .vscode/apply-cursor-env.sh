#!/usr/bin/env bash
# Копирует шаблон Cursor/VS Code по среде: FORGE (песок) или PROD (синий).
# settings.json не в git — только локально после clone/pull.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

detect_env() {
  local ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  if [[ "${OSTROV_CURSOR_ENV:-}" == "prod" ]]; then
    echo prod
    return
  fi
  if [[ "${OSTROV_CURSOR_ENV:-}" == "forge" ]]; then
    echo forge
    return
  fi
  # Только IP прода — hostname «Island» бывает и на ноуте (песочница).
  if [[ "$ip" == "188.225.44.48" ]]; then
    echo prod
    return
  fi
  echo forge
}

ENV="$(detect_env)"
mkdir -p .vscode
if [[ "$ENV" == "prod" ]]; then
  cp .vscode/settings.prod.json .vscode/settings.json
  echo "Cursor: PROD (синий) → .vscode/settings.json"
else
  cp .vscode/settings.forge.json .vscode/settings.json
  echo "Cursor: FORGE (песок) → .vscode/settings.json"
fi
