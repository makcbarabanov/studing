#!/usr/bin/env python3
"""
Создание тестовых пользователей для проверки добавления бадди.
Запуск: из корня проекта, при работающем API (uvicorn main:app --port 8000).
  python3 scripts/seed_test_users.py
  или с указанием хоста: API_BASE=http://23.172.217.180:8000 python3 scripts/seed_test_users.py
"""
import os
import sys
try:
    import requests
except ImportError:
    print("Установите requests: pip install requests")
    sys.exit(1)

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")

# --- Тестовые пользователи (телефон и пароль сообщить пользователю) ---
FORGE = {
    "name": "Форж",
    "surname": "Маработов",
    "phone": "+79001110101",
    "city": "ОСТРОВ",
    "password": "2026",
    "dreams": [
        "Написать документацию по API для проекта ОСТРОВ",
        "Добавить в roadmap раздел «Несколько бадди» и реализовать таблицу связей",
        "Провести код-ревью личного кабинета с фокусом на мобильную версию",
    ],
}

BLOOM = {
    "name": "Bloom",
    "surname": "Marabotov",
    "phone": "+79001110202",
    "city": "ОСТРОВ",
    "password": "2026",
    "dreams": [
        "Протестировать сценарий «Добавить бадди» от имени двух разных пользователей",
        "Убедиться, что мечты бадди отображаются после принятия приглашения",
    ],
}


def register_user(data):
    r = requests.post(
        f"{API_BASE}/register",
        json={
            "name": data["name"],
            "surname": data["surname"],
            "phone": data["phone"],
            "city": data["city"],
            "password": data["password"],
        },
        timeout=10,
    )
    if r.status_code == 400 and "уже зарегистрирован" in (r.json().get("detail") or ""):
        return None
    r.raise_for_status()
    return r.json()["id"]


def create_dream(user_id, dream_text):
    r = requests.post(
        f"{API_BASE}/dreams",
        json={"user_id": user_id, "dream": dream_text},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["id"]


def main():
    print("API_BASE =", API_BASE)
    print()

    # Форж Маработов
    print("1. Регистрация: Форж Маработов")
    try:
        forge_id = register_user(FORGE)
        if forge_id is None:
            print("   Пользователь уже есть, пропускаем регистрацию и мечты.")
        else:
            print("   id =", forge_id)
            for text in FORGE["dreams"]:
                create_dream(forge_id, text)
                print("   Мечта добавлена:", text[:50] + ("..." if len(text) > 50 else ""))
    except Exception as e:
        print("   Ошибка:", e)
        sys.exit(1)

    print()

    # Bloom Marabotov
    print("2. Регистрация: Bloom Marabotov")
    try:
        bloom_id = register_user(BLOOM)
        if bloom_id is None:
            print("   Пользователь уже есть, пропускаем регистрацию и мечты.")
        else:
            print("   id =", bloom_id)
            for text in BLOOM["dreams"]:
                create_dream(bloom_id, text)
                print("   Мечта добавлена:", text[:50] + ("..." if len(text) > 50 else ""))
    except Exception as e:
        print("   Ошибка:", e)
        sys.exit(1)

    print()
    print("--- Данные для входа (сообщи пользователю) ---")
    print()
    print("Форж Маработов:")
    print("  Телефон:", FORGE["phone"])
    print("  Пароль: ", FORGE["password"])
    print()
    print("Bloom Marabotov:")
    print("  Телефон:", BLOOM["phone"])
    print("  Пароль: ", BLOOM["password"])
    print()
    print("Готово.")


if __name__ == "__main__":
    main()
