#!/usr/bin/env python3
"""
1. Назначить Косте бадди: Николаев Александр (Ульяновск), id=19.
2. Добавить Санькины (Александра, user_id=19) цели на 2026 год.

Запуск из корня проекта (нужен .env с DB_* и опционально API_BASE):
  KOSTYA_ID=11 python3 scripts/seed_kostya_buddy_and_sasha_dreams_2026.py

Костя: id=11. Если KOSTYA_ID не указан, скрипт только добавит мечты пользователю 19 (Александр).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

import psycopg2
from psycopg2.extras import RealDictCursor

try:
    import requests
except ImportError:
    requests = None

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
ALEXANDER_USER_ID = 19  # Николаев Александр, Ульяновск
DEADLINE_2026 = "2026-12-31"

# Санькины цели на 2026: (текст, price или None)
SASHA_DREAMS_2026 = [
    "Я Купил автомобиль Нисан террано.",
    "Я Прочитал 12 книг.",
    "Я Накопил 200000 рублей и откладываю 5% от каждого дохода.",
    "Я вышел на доход 250000₽/мес.",
    "Каждый день я веду учёт доходов и расходов.",
    "Я провел отпуск с супругой в Сочи.",
    "Слежу за своим здоровьем. Сделал 250 зарядок с утра и 100 пробежек.",
    "Я Купил 5 комнатную квартиру.",
    "Я запустил экскурсии и вышел на доход 100000₽/мес.",
    "Я начал заниматься с наставником по бизнесу.",
]

# Цены где указаны в тексте (руб.): 3=200000, 4=250000, 9=100000
SASHA_DREAMS_PRICES = {
    2: 200000,   # цель 3 (индекс 2)
    3: 250000,   # цель 4
    8: 100000,   # цель 9
}


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
        cursor_factory=RealDictCursor,
    )


def set_buddy(kostya_id: int):
    """Связать Костю и Александра (id=19) как бадди друг друга."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE id IN (%s, %s)", (kostya_id, ALEXANDER_USER_ID))
        rows = cur.fetchall()
        ids = {r["id"] for r in rows}
        if kostya_id not in ids or ALEXANDER_USER_ID not in ids:
            print("   Ошибка: оба пользователя (Kostya и id=19) должны существовать в БД.")
            return False
        cur.execute("UPDATE users SET buddy_id = %s WHERE id = %s", (ALEXANDER_USER_ID, kostya_id))
        cur.execute("UPDATE users SET buddy_id = %s WHERE id = %s", (kostya_id, ALEXANDER_USER_ID))
        conn.commit()
        print("   Костя (id=%s) и Александр (id=%s) назначены бадди друг друга." % (kostya_id, ALEXANDER_USER_ID))
        return True
    finally:
        conn.close()


def create_dream_via_api(user_id: int, dream_text: str, deadline: str, price=None):
    body = {"user_id": user_id, "dream": dream_text, "deadline": deadline}
    if price is not None:
        body["price"] = price
    r = requests.post(f"{API_BASE}/dreams", json=body, timeout=10)
    r.raise_for_status()
    return r.json().get("id")


def add_sasha_dreams_via_api():
    """Добавить мечты пользователю 19 через API."""
    if not requests:
        print("   Установите requests: pip install requests")
        return False
    for i, text in enumerate(SASHA_DREAMS_2026):
        price = SASHA_DREAMS_PRICES.get(i)
        try:
            create_dream_via_api(ALEXANDER_USER_ID, text, DEADLINE_2026, price=price)
            print("   +", text[:55] + ("..." if len(text) > 55 else ""))
        except Exception as e:
            print("   Ошибка:", text[:40], "—", e)
    return True


def add_sasha_dreams_via_db():
    """Добавить мечты пользователю 19 напрямую в БД."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for i, text in enumerate(SASHA_DREAMS_2026):
            price = SASHA_DREAMS_PRICES.get(i)
            try:
                if price is not None:
                    cur.execute(
                        """INSERT INTO dreams (user_id, dream, status_id, category_id, date, deadline, price, is_public)
                           VALUES (%s, %s, 1, NULL, CURRENT_DATE, %s, %s, false)
                           RETURNING id""",
                        (ALEXANDER_USER_ID, text.strip(), DEADLINE_2026, price),
                    )
                else:
                    cur.execute(
                        """INSERT INTO dreams (user_id, dream, status_id, category_id, date, deadline, is_public)
                           VALUES (%s, %s, 1, NULL, CURRENT_DATE, %s, false)
                           RETURNING id""",
                        (ALEXANDER_USER_ID, text.strip(), DEADLINE_2026),
                    )
                print("   +", text[:55] + ("..." if len(text) > 55 else ""))
            except Exception as e:
                print("   Ошибка при вставке:", text[:40], "—", e)
        conn.commit()
        return True
    finally:
        conn.close()


def main():
    kostya_id = os.environ.get("KOSTYA_ID")
    if kostya_id:
        try:
            kid = int(kostya_id)
        except ValueError:
            print("KOSTYA_ID должен быть числом.")
            sys.exit(1)
        print("1. Назначаем бадди: Костя (id=%s) ↔ Александр (id=%s)..." % (kid, ALEXANDER_USER_ID))
        if not set_buddy(kid):
            sys.exit(1)
        print()
    else:
        print("KOSTYA_ID не задан — пропускаем назначение бадди.")
        print()

    print("2. Добавляем Санькины цели на 2026 (user_id=%s)..." % ALEXANDER_USER_ID)
    try:
        add_sasha_dreams_via_api()
    except Exception as e:
        print("   API не удалось, вставляем в БД:", e)
        add_sasha_dreams_via_db()

    print()
    print("Готово.")


if __name__ == "__main__":
    main()
