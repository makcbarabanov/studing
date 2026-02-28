#!/usr/bin/env python3
"""
Добавление мечт Светланы Щербининой на 2026 год (цели по сферам).
Мечты добавляются существующему пользователю по его user_id. Данные для входа не подставляются и не создаются.

Запуск (обязательно указать USER_ID — id пользователя в БД):
  USER_ID=17 API_BASE=http://23.172.217.180:8000 python3 scripts/seed_svetlana_dreams_2026.py

Света Щербинина: user_id=17.
"""
import os
import sys

try:
    import requests
except ImportError:
    print("Установите requests: pip install requests")
    sys.exit(1)

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
DEADLINE_2026 = "2026-12-31"

# Мечты по сферам: (текст мечты, code категории из dreams_categories)
DREAMS_2026 = [
    # 1. ФИНАНСЫ (finance)
    ("Создать доход от 300000 руб.", "finance"),
    ("Закрыть долговые обязательства перед банками и людьми.", "finance"),
    # 2. ОТНОШЕНИЯ (relations)
    ("Переехать в новую квартиру с хорошим ремонтом.", "relations"),
    ("Провести пару дней в отеле АЛСЕЙ", "relations"),
    ("Сутки на базе отдыха ДРУЖБА", "relations"),
    ("Посетить вместе театр, филармонию и концерт.", "relations"),
    ("Зимовка в Шри-Ланка", "relations"),
    # 3. ЗДОРОВЬЕ (health)
    ("Снизить вес до 66 кг", "health"),
    ("Долечить свой носик", "health"),
    ("Пройти обследование по-женски.", "health"),
    ("Процедура Ватсу", "health"),
    ("Массаж ТЭО у Евгении Герасименко.", "health"),
    # 4. БЛАГОТВОРИТЕЛЬНОСТЬ (charity)
    ("❤️ Создание пространства для людей", "charity"),
    # 5. ПРОЕКТЫ (projects)
    ("Провести минимум 24 завтрака желаний.", "projects"),
    ("Напечатать 2 вида новых открыток.", "projects"),
    ("Продать 1000 МК по вязанию от нашего нового бренда (разных).", "projects"),
    ("Запустить проект ДЕВУШКИ С ЛИМОНАМИ и провести минимум 10 встреч.", "projects"),
    ("Раскрутить ютуб-канал. Набрать 300 подписчиков. (сейчас 28)", "projects"),
    # 6. РАЗВИТИЕ (development)
    ("Прочитать минимум 12 книг", "development"),
    ("Закончить 2 курса АСИ (по алмазной мудрости)", "development"),
]


def get_categories():
    r = requests.get(f"{API_BASE}/dreams_categories", timeout=10)
    r.raise_for_status()
    return {c["code"]: c["id"] for c in r.json()}


def create_dream(user_id, dream_text, category_id=None, deadline=None):
    body = {"user_id": user_id, "dream": dream_text}
    if category_id is not None:
        body["category_id"] = category_id
    if deadline:
        body["deadline"] = deadline
    r = requests.post(
        f"{API_BASE}/dreams",
        json=body,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["id"]


def main():
    env_uid = os.environ.get("USER_ID")
    if not env_uid:
        print("Задайте USER_ID (id пользователя в БД). Света Щербинина: user_id=17.")
        print("Пример: USER_ID=17 API_BASE=http://23.172.217.180:8000 python3 scripts/seed_svetlana_dreams_2026.py")
        sys.exit(1)
    try:
        user_id = int(env_uid)
    except ValueError:
        print("USER_ID должен быть числом.")
        sys.exit(1)

    print("API_BASE =", API_BASE)
    print("USER_ID =", user_id)
    print()

    print("1. Загрузка категорий...")
    try:
        cat_by_code = get_categories()
    except Exception as e:
        print("   Ошибка:", e)
        sys.exit(1)

    print()
    print("2. Добавление мечт на 2026 год...")
    for text, code in DREAMS_2026:
        cid = cat_by_code.get(code)
        try:
            create_dream(user_id, text, category_id=cid, deadline=DEADLINE_2026)
            print("   +", text[:60] + ("..." if len(text) > 60 else ""))
        except Exception as e:
            print("   Ошибка при добавлении:", text[:40], "—", e)

    print()
    print("Готово. Мечты добавлены пользователю с id =", user_id)


if __name__ == "__main__":
    main()
