#!/usr/bin/env bash
# Увеличивает build-версию перед деплоем. Запуск: ./scripts/bump-version.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VF="$ROOT/version.json"
python3 - <<PY
import json
from pathlib import Path
p = Path("$VF")
data = json.loads(p.read_text(encoding="utf-8"))
data["version"] = int(data.get("version", 0)) + 1
p.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
print(data["version"])
PY
