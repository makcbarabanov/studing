# Удаление пользователей с зависимостями

При удалении пользователя в DBeaver возникает ошибка FK: другие таблицы ссылаются на `users.id`. Ниже — варианты удаления с учётом всех зависимостей.

## Зависимости от users

| Таблица | Связь | CASCADE? |
|---------|-------|----------|
| `dreams` | `user_id` (владелец мечт) | Да, после mig_dreams_user_cascade |
| `dreams_log` | `fulfilled_by_user_id` (кто отметил «сбылось») | **Нет** |
| `users` | `buddy_id` (самоссылка на другого пользователя) | — |
| `buddy_requests` | `from_user_id`, `to_user_id` | Да |
| `user_dream_views` | `user_id` | Да |
| `user_dream_favorites` | `user_id` | Да |
| `dream_favorite_notifications` | `owner_id` | Да |
| `user_dream_help_intent` | `user_id` | Да |
| `user_dream_completion_request` | `helper_user_id` | Да |
| `user_dream_helped` | `user_id` | Зависит от миграции |

---

## Вариант 1: Миграция + простой DELETE (рекомендуется)

Если миграция `mig_dreams_user_cascade` **ещё не применена**, выполни её:

```bash
# Создай файл _sql/mig_dreams_user_cascade.sql (см. Readme/migrations_applied.md)
python3 run_migrate.py _sql/mig_dreams_user_cascade.sql
```

После этого `dreams` будут удаляться каскадно. Но `dreams_log.fulfilled_by_user_id` и `users.buddy_id` всё равно нужно обработать вручную — см. Вариант 2.

---

## Вариант 2: SQL-скрипт в DBeaver (универсальный)

Выполни в DBeaver (SQL Editor) — подставь нужный `user_id`:

```sql
-- Замени 123 на ID пользователя
DO $$
DECLARE
    uid INT := 123;
BEGIN
    -- 1. Снять связь бадди (другие пользователи не должны ссылаться на удаляемого)
    UPDATE users SET buddy_id = NULL, buddy_trust = false WHERE buddy_id = uid;

    -- 2. Удалить записи dreams_log, где этот пользователь отметил «сбылось» (чужие мечты)
    DELETE FROM dreams_log WHERE fulfilled_by_user_id = uid;

    -- 3. Удалить мечты пользователя (если CASCADE не применён — иначе этот шаг не нужен)
    DELETE FROM dreams WHERE user_id = uid;

    -- 4. Удалить пользователя (остальные таблицы с CASCADE очистятся автоматически)
    DELETE FROM users WHERE id = uid;

    RAISE NOTICE 'Пользователь % удалён', uid;
END $$;
```

**Важно:** если `dreams.user_id` уже с `ON DELETE CASCADE`, шаг 3 можно убрать — мечты удалятся при шаге 4.

---

## Вариант 3: Python-скрипт

```bash
python3 scripts/delete_user.py 123
```

Скрипт делает то же, что SQL выше, и дополнительно удаляет файл аватарки (если есть).

---

## Вариант 4: Только через DBeaver (без скриптов)

1. Открой **SQL Editor** (не таблицу).
2. Вставь и выполни скрипт из Варианта 2, подставив нужный `user_id`.
3. Commit (Ctrl+Enter или кнопка Commit).

**Не удаляй строки через контекстное меню таблицы** — FK-ограничения заблокируют удаление.

---

## Проверка перед удалением

Узнать, что будет затронуто:

```sql
SELECT id, name, surname, phone FROM users WHERE id = 123;

-- Мечты пользователя
SELECT COUNT(*) FROM dreams WHERE user_id = 123;

-- Записи «сбылось», где пользователь отметил чужие мечты
SELECT COUNT(*) FROM dreams_log WHERE fulfilled_by_user_id = 123;

-- Кто имеет этого пользователя бадди
SELECT id, name, surname FROM users WHERE buddy_id = 123;
```

---

## Аватарки

Файлы аватарок лежат в `media/avatars/{user_id}.jpg` (или другой расширение). После удаления пользователя их можно удалить вручную или скриптом `delete_user.py`.
