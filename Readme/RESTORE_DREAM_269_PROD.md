# Restore мечты 269 «Библиотека» + patch 181 (прод)

**Подготовил:** Forge (песочница)  
**Дамп-источник:** `~/Backup/prod_default_db_20260520_192735.dump` (2026-05-20 19:27)  
**На прод SQL не выполнять без «ДА ПРОД» от Макса.**

## Факты (сверено с дампом 20.05)

| Объект | Состояние на проде (Продагент) | В дампе 20.05 |
|--------|-------------------------------|---------------|
| `dreams` 181 | Есть, `dream` = «Прочитать 11 книг», `title` пустой, 37 шагов | То же |
| `dreams` 269 | **Нет** (DELETE) | `Библиотека`, `rule_code=books_reading`, `settings={"library_mode":true}`, `status_id=2`, `is_public=false` |
| `dream_books` | 0 строк на проде | 7 книг, `id` 9–14, 16 → `dream_id=269` |
| `dream_books_log` | — | 0 строк для этих книг |

**181:** `rule_code` **не** ставим на `books_reading` — библиотека только у **269**.  
**UI списка:** API `GET /dreams` берёт заголовок из колонки `dream`; patch 181 дублирует текст в `title` для совместимости с фронтом/отчётами.

## Файлы

| Файл | Назначение |
|------|------------|
| `_sql/restore_prod_dream_269_and_patch_181.sql` | Готовый SQL (BEGIN…COMMIT, проверки, INSERT, sequences) |
| `scripts/extract_dream_269_from_dump.sh` | Повторная сверка строк из дампа через Docker + Postgres 17 |

## Продагент: порядок работ

### 1. Бэкап перед операцией

```bash
cd /home/makc/Apps/island
export PGPASSWORD='…'   # из .env, не в чат
pg_dump -h "$DB_HOST" -p "${DB_PORT:-5432}" -U "$DB_USER" -d "$DB_NAME" \
  -Fc -f ~/Backups/island/prod_before_restore_$(date +%Y%m%d_%H%M%S).dump
```

### 2. Проверки на проде (read-only)

```sql
SELECT id FROM dreams WHERE id IN (181, 269);
SELECT id, dream_id, title FROM dream_books WHERE id IN (9,10,11,12,13,14,16) OR dream_id = 269;
SELECT id, user_id, dream, title, rule_code FROM dreams WHERE user_id = 1 AND rule_code = 'books_reading';
```

Ожидание: 181 есть, 269 нет; id книг 9–16 свободны.

### 3. Применить SQL

```bash
psql -h "$DB_HOST" -p "${DB_PORT:-5432}" -U "$DB_USER" -d "$DB_NAME" \
  -f _sql/restore_prod_dream_269_and_patch_181.sql
```

Если `dream_books` на проде имеет колонку `linked_step_id` — INSERT без неё даёт NULL (нормально).

### 4. Smoke

```bash
curl -sk 'https://islanddream.ru/dreams?user_id=1' \
  | jq '.dreams[] | select(.id==181 or .id==269) | {id, title, dream, rule_code, books: (.books|length)}'
```

Ожидание:

- `269`: `rule_code` = `books_reading`, `books` = 7  
- `181`: `title` / `dream` про 11 книг, `books` = 0  

В ЛК: раздел библиотеки снова виден (мечта 269).

## Песочница Forge

```bash
cd web-app
./scripts/extract_dream_269_from_dump.sh ~/Backup/prod_default_db_20260520_192735.dump
# Применить тот же SQL к копии БД песка после pg_restore дампа или частичного клона
```

## Не в scope этого restore

- Полный `pg_restore` всей БД  
- Восстановление `dream_books_log` (в дампе пусто)  
- Soft-delete для `books_reading` (отдельный коммит)  
- Починка `bu_db.sh` / weekly dump (бонус, отдельно)

## Роли

| Кто | Действие |
|-----|----------|
| **Макс** | «ДА ПРОД», приоритет «оба» (269 + 181) |
| **Forge** | SQL, сверка с дампом, при необходимости правка UI/миграций |
| **Продагент** | `pg_dump` до, `psql -f` после «ДА ПРОД», smoke, отчёт |
