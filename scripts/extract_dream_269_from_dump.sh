#!/usr/bin/env bash
# Извлечь строки dreams.id=269 и dream_books из дампа (для сверки перед прод-restore).
# Требует: docker, файл дампа (PostgreSQL 17 custom format).
set -euo pipefail

DUMP="${1:-$HOME/Backup/prod_default_db_20260520_192735.dump}"
CONTAINER="${RESTORE_CONTAINER:-pg_extract_tmp}"

if [[ ! -f "$DUMP" ]]; then
  echo "✗ Нет файла: $DUMP" >&2
  exit 1
fi

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d --name "$CONTAINER" -e POSTGRES_PASSWORD=tmp -e POSTGRES_DB=extract_tmp postgres:17 >/dev/null
sleep 4
docker cp "$DUMP" "$CONTAINER:/tmp/dump.dump"

docker exec "$CONTAINER" pg_restore -U postgres -d extract_tmp \
  --schema-only -t dreams -t dream_books -t dream_books_log /tmp/dump.dump 2>/dev/null || true

docker exec "$CONTAINER" pg_restore -U postgres -d extract_tmp \
  --data-only -t dreams -t dream_books -t dream_books_log /tmp/dump.dump 2>/dev/null || true

echo "=== dreams 181, 269 ==="
docker exec "$CONTAINER" psql -U postgres -d extract_tmp -c \
  "SELECT id, user_id, dream, title, rule_code, settings FROM dreams WHERE id IN (181,269) ORDER BY id;"

echo "=== dream_books dream_id=269 ==="
docker exec "$CONTAINER" psql -U postgres -d extract_tmp -c \
  "SELECT id, dream_id, title, author, status, started_at, deadline, finished_at FROM dream_books WHERE dream_id=269 ORDER BY id;"

echo "=== dream_books_log ==="
docker exec "$CONTAINER" psql -U postgres -d extract_tmp -c \
  "SELECT COUNT(*) AS log_rows FROM dream_books_log WHERE book_id IN (SELECT id FROM dream_books WHERE dream_id=269);"
