#!/usr/bin/env python3
"""
Приводит телефоны в БД к формату +79998880011 (без пробелов).
Для пользователей без пароля (password_hash пустой или NULL) ставит пароль = последние 4 цифры телефона.
Запуск из корня проекта: python3 scripts/normalize_phones_and_passwords.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
Path(__file__).resolve().parent.parent
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import psycopg2
from psycopg2.extras import RealDictCursor
from passlib.hash import bcrypt


def normalize_phone(phone):
    """Приводит к виду +79998880011 (без пробелов и прочего)."""
    if not phone or not isinstance(phone, str):
        return ""
    s = re.sub(r"[\s\-\(\)]", "", phone.strip())
    if not s:
        return ""
    if s.startswith("+7") and len(s) == 12 and s[2:].isdigit():
        return s
    if s.startswith("8") and len(s) == 11 and s.isdigit():
        return "+7" + s[1:]
    if s.startswith("7") and len(s) == 11 and s.isdigit():
        return "+" + s
    if len(s) == 10 and s.isdigit():
        return "+7" + s
    return s  # остальное (напр. +375) оставляем как есть


def main():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
        cursor_factory=RealDictCursor,
    )
    updated_phones = 0
    updated_passwords = 0
    errors = []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, phone, password_hash FROM users")
            rows = cur.fetchall()
        for row in rows:
            uid = row["id"]
            phone = row["phone"] or ""
            pwd_hash = row["password_hash"]
            has_password = pwd_hash is not None and str(pwd_hash).strip() != ""

            normalized = normalize_phone(phone)

            # Обновить телефон, если изменился и не пустой
            if normalized and normalized != phone:
                try:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE users SET phone = %s WHERE id = %s", (normalized, uid))
                    conn.commit()
                    updated_phones += 1
                    print("  phone id=%s: %r -> %s" % (uid, phone, normalized))
                except psycopg2.IntegrityError as e:
                    conn.rollback()
                    errors.append("id=%s phone %s: %s" % (uid, normalized, e))

            # Пароль = последние 4 символа телефона (цифры), если пароля нет
            if not has_password and normalized and len(normalized) >= 4:
                last4 = normalized[-4:]
                if last4.isdigit():
                    new_hash = bcrypt.hash(last4)
                    try:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, uid))
                        conn.commit()
                        updated_passwords += 1
                        print("  password id=%s: last4=%s" % (uid, last4))
                    except Exception as e:
                        conn.rollback()
                        errors.append("id=%s password: %s" % (uid, e))

    finally:
        conn.close()

    print("\nИтого: обновлено телефонов %s, установлено паролей (последние 4 цифры) %s." % (updated_phones, updated_passwords))
    if errors:
        print("Ошибки:", errors)


if __name__ == "__main__":
    main()
