#!/usr/bin/env python3
"""
Проставляет users.gender по имени, фамилии и отчеству.
Запуск: из корня проекта: python3 scripts/set_users_gender.py
Требуется .env и выполненная миграция mig_users_gender (колонка users.gender).
Сомнительные выводятся в конец — можно доустановить вручную или подсказать автору скрипта.
"""
import os
import re
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file)
else:
    print("Ошибка: нужен .env в корне проекта.", file=sys.stderr)
    sys.exit(1)

import psycopg2
from psycopg2.extras import RealDictCursor

# Имена, по которым однозначно определяем пол (нижний регистр для сравнения)
FEMALE_NAMES = {
    "анна", "мария", "ольга", "ксения", "елена", "наталья", "наталия", "ирина", "светлана",
    "юлия", "дарья", "виктория", "полина", "екатерина", "татьяна", "александра", "марина",
    "валерия", "алина", "диана", "валентина", "людмила", "галина", "нина", "лариса",
    "вероника", "ульяна", "василиса", "милана", "софья", "софия", "алиса", "арина",
    "милена", "маргарита", "элина", "карина", "виолетта", "стелла", "ревекка",
}
MALE_NAMES = {
    "александр", "иван", "макс", "максим", "дмитрий", "сергей", "андрей", "алексей",
    "михаил", "евгений", "николай", "артём", "артем", "илья", "кирилл", "павел",
    "роман", "владимир", "денис", "никита", "виктор", "константин", "олег", "владислав",
    "марк", "леонид", "борис", "григорий", "вадим", "георгий", "тимофей", "матвей",
    "даниил", "данил", "захар", "пётр", "петр", "фёдор", "федор", "ярослав", "гоша",
}

def normalize(s):
    return (s or "").strip().lower()

def by_patronymic(patronymic):
    p = normalize(patronymic)
    if not p:
        return None
    if p.endswith("ович") or p.endswith("евич") or p.endswith("ич"):
        return "m"
    if p.endswith("овна") or p.endswith("евна") or p.endswith("ична") or p.endswith("инична"):
        return "f"
    return None

def by_surname(surname):
    s = normalize(surname)
    if not s or len(s) < 3:
        return None
    # женские окончания
    if re.search(r"(ова|ева|ина|ская|цкая|ёва)$", s):
        return "f"
    if re.search(r"(ов|ев|ин|ский|цкий|ёв|ын|ой)$", s):
        return "m"
    return None

def by_name(name):
    n = normalize(name)
    if not n:
        return None
    if n in FEMALE_NAMES:
        return "f"
    if n in MALE_NAMES:
        return "m"
    # сокращения
    if n in ("саша", "шура", "лекса", "алекса"):  # может быть и Александр(а)
        return None
    if n in ("женя", "валя", "саша", "слава"):  # унисекс
        return None
    # по последней букве типично: -а, -я → часто ж
    if len(n) >= 2 and n[-1] in "ая" and n not in MALE_NAMES:
        return "f"
    return None

def infer_gender(row):
    name = row.get("name")
    surname = row.get("surname")
    patronymic = row.get("patronymic")
    g = by_patronymic(patronymic)
    if g:
        return g, "patronymic"
    g = by_name(name)
    if g:
        return g, "name"
    g = by_surname(surname)
    if g:
        return g, "surname"
    return None, None

def main():
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            dbname=os.getenv("DB_NAME"),
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Проверяем наличие колонки gender
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'gender'
            """)
            if not cur.fetchone():
                print("Ошибка: колонки users.gender нет. Выполните миграцию: python3 run_migrate.py _sql/mig_users_gender.sql", file=sys.stderr)
                sys.exit(2)
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'patronymic'
            """)
            has_patronymic = cur.fetchone() is not None
            if has_patronymic:
                cur.execute("SELECT id, name, surname, patronymic FROM users")
            else:
                cur.execute("SELECT id, name, surname FROM users")
            rows = cur.fetchall()
            if not has_patronymic:
                for r in rows:
                    r["patronymic"] = None

        updated = 0
        ambiguous = []
        for row in rows:
            uid = row["id"]
            gender, source = infer_gender(row)
            if gender:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET gender = %s WHERE id = %s", (gender, uid))
                updated += 1
            else:
                name = (row.get("name") or "").strip()
                surname = (row.get("surname") or "").strip()
                ambiguous.append((uid, name, surname))

        conn.commit()
        print("Обновлено записей (пол проставлен):", updated)
        if ambiguous:
            print("\nСомнительные (пол не установлен, оставлен NULL):")
            for uid, name, surname in ambiguous:
                full = " ".join(filter(None, [name, surname])).strip() or "(пусто)"
                print("  id={}  {}".format(uid, full))
            print("\nПодскажите пол для этих (m/f), можно дообновить вручную в БД или добавить имена в скрипт.")
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        print("Ошибка БД:", e, file=sys.stderr)
        sys.exit(3)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()
