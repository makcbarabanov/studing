#!/usr/bin/env python3
"""
Обнулить связь бадди и запросы между Форжем и Блумом для повторного теста.
Запуск из корня проекта (нужен .env с DB_*):
  python3 scripts/reset_buddy_forge_bloom.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import psycopg2

PHONES = ["+79001110101", "+79001110202"]  # Форж, Блум

def main():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
    )
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE phone = ANY(%s)", (PHONES,))
    ids = [r[0] for r in cur.fetchall()]
    if not ids:
        print("Пользователи Форж/Блум не найдены.")
        cur.close()
        conn.close()
        return
    cur.execute("UPDATE users SET buddy_id = NULL WHERE id = ANY(%s)", (ids,))
    updated = cur.rowcount
    cur.execute(
        "DELETE FROM buddy_requests WHERE from_user_id = ANY(%s) OR to_user_id = ANY(%s)",
        (ids, ids),
    )
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    print("Готово: обнулён buddy_id у", updated, "пользователей, удалено записей buddy_requests:", deleted)

if __name__ == "__main__":
    main()
