#!/usr/bin/env python3
"""
Установить Костя (id=11) и Александр (id=19) бадди друг друга и прописать avatar_path.
Аватарки уже скопированы: media/avatars/11.jpg (zainza), media/avatars/19.jpg (nikolaev).

Запуск из корня (нужен .env с DB_*):
  python3 scripts/set_buddy_and_avatars_11_19.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import psycopg2
from psycopg2.extras import RealDictCursor

KOSTYA_ID = 11
ALEXANDER_ID = 19


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
        cursor_factory=RealDictCursor,
    )


def main():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET buddy_id = %s WHERE id = %s", (ALEXANDER_ID, KOSTYA_ID))
        cur.execute("UPDATE users SET buddy_id = %s WHERE id = %s", (KOSTYA_ID, ALEXANDER_ID))
        cur.execute("UPDATE users SET avatar_path = %s WHERE id = %s", ("avatars/11.jpg", KOSTYA_ID))
        cur.execute("UPDATE users SET avatar_path = %s WHERE id = %s", ("avatars/19.jpg", ALEXANDER_ID))
        conn.commit()
        print("Готово: Костя (11) и Александр (19) — бадди друг друга, аватарки avatars/11.jpg и avatars/19.jpg.")
    except Exception as e:
        conn.rollback()
        print("Ошибка:", e)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
