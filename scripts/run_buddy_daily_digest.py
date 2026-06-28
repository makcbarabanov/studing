#!/usr/bin/env python3
"""
Ежедневный digest уведомлений бадди (пропущенные шаги, отчёт не отправлен).

SRE: запуск на хосте ОС (cron/systemd), прямое подключение к PostgreSQL.
НЕ вызывает HTTP main.py — без internal routes.

Использование:
  python scripts/run_buddy_daily_digest.py

Cron (Moscow, каждый час — скрипт проверяет buddy_alert_daily_at):
  0 * * * * cd /home/makc/Apps/island && venv/bin/python scripts/run_buddy_daily_digest.py >> logs/buddy_digest.log 2>&1
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_env_file = _project_root / ".env"


def _load_env_simple(path: Path) -> None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].strip()
        if "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val


if _env_file.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(_env_file)
    except ImportError:
        _load_env_simple(_env_file)
else:
    print("Предупреждение: .env не найден, используются переменные окружения.", file=sys.stderr)


def main() -> int:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    from buddy_alerts_core import DEFAULT_BUDDY_ALERT_TZ, run_daily_digest

    conn_kw = dict(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
    )
    if os.getenv("DB_PORT"):
        conn_kw["port"] = int(os.getenv("DB_PORT"))

    if not conn_kw.get("host") or not conn_kw.get("dbname"):
        print("Ошибка: задайте DB_HOST, DB_USER, DB_PASS, DB_NAME в .env", file=sys.stderr)
        return 2

    conn = None
    try:
        conn = psycopg2.connect(**conn_kw)
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            subjects, created = run_daily_digest(cur)
        conn.commit()
        print(
            f"OK buddy digest tz={DEFAULT_BUDDY_ALERT_TZ} "
            f"subjects={subjects} notifications_created={created}"
        )
        return 0
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        print(f"Ошибка БД: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Ошибка: {e}", file=sys.stderr)
        return 4
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
