#!/usr/bin/env python3
"""
Восстановить avatar_path для Светы Щербининой (user_id=17).
Файл должен лежать в media/avatars/17.jpg (или .png).

Запуск из корня (нужен .env с DB_*):
  python3 scripts/set_avatar_svetlana.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import psycopg2

SVETLANA_ID = 17
AVATAR_PATH = "avatars/17.jpg"


def main():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
    )
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET avatar_path = %s WHERE id = %s", (AVATAR_PATH, SVETLANA_ID))
        conn.commit()
        if cur.rowcount:
            print("Готово: для пользователя 17 (Света) установлен avatar_path =", AVATAR_PATH)
        else:
            print("Пользователь с id=17 не найден в БД.")
    except Exception as e:
        conn.rollback()
        print("Ошибка:", e)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
