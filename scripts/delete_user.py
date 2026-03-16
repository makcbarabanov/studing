#!/usr/bin/env python3
"""
Удаление пользователя и всех зависимостей из БД.
Использование: python3 scripts/delete_user.py <user_id>

Зависимости: .env в корне проекта (DB_HOST, DB_USER, DB_PASS, DB_NAME).
"""
import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file)

import psycopg2
from psycopg2.extras import RealDictCursor


def delete_user(user_id: int, delete_avatar: bool = True) -> None:
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            dbname=os.getenv("DB_NAME"),
        )
        conn.autocommit = False

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, name, surname, phone, avatar_path FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                print(f"Пользователь с id={user_id} не найден.", file=sys.stderr)
                sys.exit(1)

            print(f"Удаляю: {row['name']} {row['surname']} (id={user_id}, phone={row['phone']})")

            # 1. Снять связь бадди
            cur.execute("UPDATE users SET buddy_id = NULL, buddy_trust = false WHERE buddy_id = %s", (user_id,))
            n = cur.rowcount
            if n:
                print(f"  — снята связь бадди у {n} пользователей")

            # 2. dreams_log (кто отметил «сбылось»)
            cur.execute("DELETE FROM dreams_log WHERE fulfilled_by_user_id = %s", (user_id,))
            n = cur.rowcount
            if n:
                print(f"  — удалено {n} записей dreams_log")

            # 3. Мечты (если CASCADE не применён — удалим вручную)
            cur.execute("DELETE FROM dreams WHERE user_id = %s", (user_id,))
            n = cur.rowcount
            if n:
                print(f"  — удалено {n} мечт")

            # 4. Пользователь (остальное — CASCADE)
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            if cur.rowcount != 1:
                print("Ошибка: пользователь не удалён (возможно, остались FK).", file=sys.stderr)
                conn.rollback()
                sys.exit(2)

        conn.commit()
        print("  — пользователь удалён из БД")

        # 5. Аватарка (опционально)
        if delete_avatar and row.get("avatar_path"):
            avatar_path = _project_root / "media" / row["avatar_path"]
            if avatar_path.exists():
                avatar_path.unlink()
                print(f"  — удалён файл аватарки: {avatar_path}")
            else:
                print(f"  — файл аватарки не найден: {avatar_path}")

        print("Готово.")

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


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 scripts/delete_user.py <user_id> [--keep-avatar]", file=sys.stderr)
        sys.exit(1)

    try:
        user_id = int(sys.argv[1])
    except ValueError:
        print("user_id должен быть числом.", file=sys.stderr)
        sys.exit(1)

    delete_avatar = "--keep-avatar" not in sys.argv
    delete_user(user_id, delete_avatar=delete_avatar)


if __name__ == "__main__":
    main()
