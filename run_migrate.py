#!/usr/bin/env python3
"""
Запуск SQL-миграций с учётом .env (те же DB_HOST, DB_USER, DB_PASS, DB_NAME, что и main.py).
Позволяет агенту/разработчику применять миграции одной командой без ручного экспорта переменных.

Использование:
  python run_migrate.py _sql/mig_005_xxx.sql
  python run_migrate.py _sql/mig_005_a.sql _sql/mig_006_b.sql
"""
import os
import sys
from pathlib import Path

# Загружаем .env из каталога проекта (рядом с run_migrate.py)
_project_root = Path(__file__).resolve().parent
_env_file = _project_root / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file)
else:
    print("Предупреждение: .env не найден, используются переменные окружения.", file=sys.stderr)

import psycopg2

def main():
    if len(sys.argv) < 2:
        print("Использование: python3 run_migrate.py <файл.sql> [файл2.sql ...]", file=sys.stderr)
        sys.exit(1)

    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            dbname=os.getenv("DB_NAME"),
        )
        conn.autocommit = False

        for file_path in sys.argv[1:]:
            path = Path(file_path)
            if not path.is_absolute():
                path = _project_root / path
            if not path.exists():
                print(f"Ошибка: файл не найден: {path}", file=sys.stderr)
                sys.exit(2)
            sql = path.read_text(encoding="utf-8", errors="replace")
            if not sql.strip():
                print(f"Пропуск пустого файла: {path.name}")
                continue
            print(f"Выполняю: {path.name} ...")
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            print(f"  OK: {path.name}")

    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        print(f"Ошибка БД: {e}", file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(4)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
