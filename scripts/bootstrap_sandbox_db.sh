#!/usr/bin/env bash
# Локальная песочница: схема + справочники + тестовый пользователь.
# Запуск из web-app/: bash scripts/bootstrap_sandbox_db.sh

set -euo pipefail
cd "$(dirname "$0")/.."

DB=(docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T db)
APP=(docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T app)

echo "==> Bootstrap schema (_sql/mig_sandbox_bootstrap.sql)"
cat _sql/mig_sandbox_bootstrap.sql | "${DB[@]}" psql -U marabot -d default_db -v ON_ERROR_STOP=1

echo "==> Reference data (seed)"
cat _sql/seed_system_reference_data_idempotent.sql | "${DB[@]}" psql -U marabot -d default_db -v ON_ERROR_STOP=1

echo "==> Test user + sample step"
"${APP[@]}" python3 <<'PY'
import os
import psycopg2
from passlib.hash import bcrypt

conn = psycopg2.connect(
    host=os.environ.get("DB_HOST", "db"),
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASS"],
    dbname=os.environ["DB_NAME"],
    port=int(os.environ.get("DB_PORT") or 5432),
)
conn.autocommit = True
h = bcrypt.hash("123")
with conn.cursor() as cur:
    cur.execute(
        """UPDATE users SET
             name = COALESCE(NULLIF(TRIM(name), ''), 'Макс'),
             surname = COALESCE(NULLIF(TRIM(surname), ''), 'Барабанов'),
             phone = %s,
             city = COALESCE(NULLIF(TRIM(city), ''), 'Санкт-Петербург'),
             password_hash = %s
           WHERE id = 1""",
        ("+79886296030", h),
    )
    cur.execute(
        """UPDATE dreams SET status_id = 2, is_public = false
           WHERE id = (SELECT id FROM dreams WHERE user_id = 1 ORDER BY id LIMIT 1)"""
    )
    cur.execute(
        """INSERT INTO dreams_steps (dream_id, title, completed, sort_order, deadline)
           SELECT d.id, 'Проверить дневник в песке', false, 0, CURRENT_DATE
           FROM dreams d
           WHERE d.user_id = 1
             AND NOT EXISTS (
               SELECT 1 FROM dreams_steps s
               WHERE s.dream_id = d.id AND s.title = 'Проверить дневник в песке'
             )
           ORDER BY d.id
           LIMIT 1"""
    )
conn.close()
print("user id=1: phone +79886296030, password 123")
PY

echo "==> Smoke"
curl -s -o /dev/null -w "GET /dreams?user_id=1 => %{http_code}\n" "http://127.0.0.1:8000/dreams?user_id=1"
curl -s -X POST "http://127.0.0.1:8000/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"9886296030","password":"123"}' | head -c 120
echo ""
echo "Готово. Вход: 9886296030 / 123"
