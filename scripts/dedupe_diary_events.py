#!/usr/bin/env python3
"""
Удаление дубликатов записей дневника: одинаковые user_id + день (UTC) + message + step_id + linked_*.

Оставляет запись с минимальным id.

  python3 scripts/dedupe_diary_events.py --dry-run
  python3 scripts/dedupe_diary_events.py
  python3 scripts/dedupe_diary_events.py 17   # только пользователь 17

На проде:
  docker compose exec app python3 scripts/dedupe_diary_events.py
"""
import os
import sys
from pathlib import Path
from typing import Optional

_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    from dotenv import load_dotenv

    load_dotenv(_env_file)

import psycopg2
from psycopg2.extras import RealDictCursor


def dedupe_diary_events(user_id: Optional[int] = None, dry_run: bool = False) -> None:
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
    )
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            user_filter = "AND e.user_id = %s" if user_id is not None else ""
            params = (user_id,) if user_id is not None else ()
            cur.execute(
                f"""
                WITH dups AS (
                    SELECT e.id,
                           ROW_NUMBER() OVER (
                               PARTITION BY e.user_id,
                                            (e.created_at AT TIME ZONE 'UTC')::date,
                                            e.message,
                                            e.step_id,
                                            COALESCE(e.linked_dream_ids::text, '[]'),
                                            COALESCE(e.linked_step_ids::text, '[]')
                               ORDER BY e.id
                           ) AS rn
                    FROM dreams_steps_events e
                    WHERE e.message IS NOT NULL AND TRIM(e.message) <> ''
                      {user_filter}
                )
                SELECT id FROM dups WHERE rn > 1
                """,
                params,
            )
            ids = [r["id"] for r in cur.fetchall()]
            print(f"Дубликатов к удалению: {len(ids)}")
            if not ids:
                return
            if dry_run:
                print("dry-run:", ids[:25], ("…" if len(ids) > 25 else ""))
                return
            cur.execute("DELETE FROM dreams_steps_events WHERE id = ANY(%s)", (ids,))
            conn.commit()
            print(f"Удалено записей: {cur.rowcount}")
    except psycopg2.Error as e:
        conn.rollback()
        print(f"Ошибка БД: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Удалить дубликаты записей дневника")
    parser.add_argument("user_id", type=int, nargs="?", help="ID пользователя (опционально)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dedupe_diary_events(user_id=args.user_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
