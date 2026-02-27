#!/usr/bin/env python3
"""
Установить пароль 2026 для тестовых пользователей Форж и Блум.
Запуск из корня проекта (нужен .env с DB_*):
  python3 scripts/set_test_passwords.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

try:
    import psycopg2
    from passlib.hash import bcrypt
except ImportError as e:
    print("Нужны: pip install psycopg2-binary passlib")
    sys.exit(1)

password_plain = "2026"
phones = ["+79001110101", "+79001110202"]  # Форж, Блум

def main():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
    )
    h = bcrypt.hash(password_plain)
    cur = conn.cursor()
    for phone in phones:
        cur.execute("UPDATE users SET password_hash = %s WHERE phone = %s", (h, phone))
        if cur.rowcount:
            print("Пароль 2026 установлен для", phone)
        else:
            print("Пользователь не найден:", phone)
    conn.commit()
    cur.close()
    conn.close()
    print("Готово. Вход: Форж +79001110101 / Блум +79001110202, пароль: 2026")

if __name__ == "__main__":
    main()
