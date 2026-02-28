#!/usr/bin/env python3
"""
Установить новый пароль пользователю по user_id (через админ-API).
Используй, если пользователь не может войти под старым паролем.

Запуск:
  USER_ID=17 PASSWORD=новый_пароль API_BASE=http://23.172.217.180:8000 python3 scripts/set_user_password.py

Или: python3 scripts/set_user_password.py 17 новый_пароль
"""
import os
import sys

try:
    import requests
except ImportError:
    print("Установите requests: pip install requests")
    sys.exit(1)

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")


def main():
    if len(sys.argv) >= 3:
        user_id = sys.argv[1]
        password = sys.argv[2]
    else:
        user_id = os.environ.get("USER_ID")
        password = os.environ.get("PASSWORD")
    if not user_id or not password:
        print("Укажи user_id и новый пароль.")
        print("Пример: python3 scripts/set_user_password.py 17 новый_пароль")
        print("Или: USER_ID=17 PASSWORD=новый_пароль python3 scripts/set_user_password.py")
        sys.exit(1)
    try:
        uid = int(user_id)
    except ValueError:
        print("USER_ID должен быть числом.")
        sys.exit(1)

    r = requests.put(
        f"{API_BASE}/admin/users/{uid}",
        json={"password": password},
        timeout=10,
    )
    if not r.ok:
        print("Ошибка:", r.status_code, r.text)
        sys.exit(1)
    print("Пароль для пользователя id={} установлен. Можно входить в кабинет с этим паролем (телефон пользователя не менялся).".format(uid))


if __name__ == "__main__":
    main()
