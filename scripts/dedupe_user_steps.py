#!/usr/bin/env python3
"""
Мягкое удаление дубликатов шагов (deleted=true). Оставляет строку с минимальным id.

Дубликаты:
  1) одинаковые dream_id + deadline + title (активные шаги)
  2) одинаковые dream_id + series_id + series_index (активные, series_id не NULL)

Использование:
  python3 scripts/dedupe_user_steps.py 17
  python3 scripts/dedupe_user_steps.py 17 --dry-run
  python3 scripts/dedupe_user_steps.py --all
  python3 scripts/dedupe_user_steps.py --all --dry-run

На проде (после git pull):
  docker compose exec app python3 scripts/dedupe_user_steps.py --all --dry-run
  docker compose exec app python3 scripts/dedupe_user_steps.py --all

Перед миграцией уникальных индексов (_sql/mig_dreams_steps_unique_*.sql) обязательно dedupe по всей БД (--all).
"""
import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    from dotenv import load_dotenv

    load_dotenv(_env_file)

import psycopg2
from psycopg2.extras import RealDictCursor


def _connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
    )


def _find_duplicate_ids(cur, user_id: Optional[int]) -> Tuple[List[int], List[int]]:
    user_filter = "AND d.user_id = %s" if user_id is not None else ""
    params = (user_id,) if user_id is not None else ()

    cur.execute(
        f"""
        WITH dups AS (
            SELECT s.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.dream_id, s.deadline, s.title
                       ORDER BY s.id
                   ) AS rn
            FROM dreams_steps s
            JOIN dreams d ON d.id = s.dream_id
            WHERE COALESCE(s.deleted, false) = false
              AND s.deadline IS NOT NULL
              {user_filter}
        )
        SELECT id FROM dups WHERE rn > 1
        """,
        params,
    )
    by_date_title = [r["id"] for r in cur.fetchall()]

    cur.execute(
        f"""
        WITH dups AS (
            SELECT s.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.dream_id, s.series_id, s.series_index
                       ORDER BY s.id
                   ) AS rn
            FROM dreams_steps s
            JOIN dreams d ON d.id = s.dream_id
            WHERE COALESCE(s.deleted, false) = false
              AND s.series_id IS NOT NULL
              AND s.series_index IS NOT NULL
              {user_filter}
        )
        SELECT id FROM dups WHERE rn > 1
        """,
        params,
    )
    by_series_slot = [r["id"] for r in cur.fetchall()]
    return by_date_title, by_series_slot


def dedupe_steps(user_id: Optional[int] = None, dry_run: bool = False) -> None:
    conn = _connect()
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if user_id is not None:
                cur.execute("SELECT id, name, surname FROM users WHERE id = %s", (user_id,))
                user = cur.fetchone()
                if not user:
                    print(f"Пользователь id={user_id} не найден.", file=sys.stderr)
                    sys.exit(1)
                print(f"Пользователь: {user['name']} {user['surname']} (id={user_id})")
            else:
                print("Режим: все пользователи (--all)")

            by_date_title, by_series_slot = _find_duplicate_ids(cur, user_id)
            to_delete = sorted(set(by_date_title) | set(by_series_slot))
            print(f"Дубликаты по (dream, deadline, title): {len(by_date_title)}")
            print(f"Дубликаты по (dream, series_id, series_index): {len(by_series_slot)}")
            print(f"Всего к удалению (уникальные id): {len(to_delete)}")

            if not to_delete:
                print("Дубликатов нет.")
                return

            if dry_run:
                print("dry-run: изменения не применены.")
                preview = to_delete[:20]
                print("Примеры id:", preview, ("…" if len(to_delete) > 20 else ""))
                return

            cur.execute(
                "UPDATE dreams_steps SET deleted = true WHERE id = ANY(%s)",
                (to_delete,),
            )
            conn.commit()
            print(f"Помечено deleted=true: {cur.rowcount} шагов.")
    except psycopg2.Error as e:
        conn.rollback()
        print(f"Ошибка БД: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Удалить дубликаты шагов")
    parser.add_argument("user_id", type=int, nargs="?", help="ID пользователя (например 17 — Света)")
    parser.add_argument("--all", action="store_true", help="Очистить дубликаты по всей БД (для миграции индексов)")
    parser.add_argument("--dry-run", action="store_true", help="Только показать, не менять БД")
    args = parser.parse_args()

    if args.all and args.user_id is not None:
        print("Укажите либо user_id, либо --all, не оба сразу.", file=sys.stderr)
        sys.exit(1)
    if not args.all and args.user_id is None:
        parser.error("нужен user_id или флаг --all")

    dedupe_steps(user_id=None if args.all else args.user_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
