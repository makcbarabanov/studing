-- Точечный restore: мечта 269 «Библиотека» + 7 книг из дампа prod_default_db_20260520_192735.dump
-- Patch: мечта 181 — title для списка в ЛК (dream уже «Прочитать 11 книг», 37 шагов на месте).
--
-- ПРИМЕНЯТЬ ТОЛЬКО НА ПРОДЕ после:
--   1) «ДА ПРОД» от Макса
--   2) pg_dump prod_before_restore_YYYYMMDD.dump
--   3) успешного прохождения блока «Проверки» ниже
--
-- Источник строк: ~/Backup/prod_default_db_20260520_192735.dump (2026-05-20 19:27 MSK)
-- Forge: песочница / подготовка SQL. Продагент: бэкап + выполнение.

BEGIN;

-- =============================================================================
-- ПРОВЕРКИ (должны пройти до INSERT; при ошибке — ROLLBACK и разбор с Forge)
-- =============================================================================

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM dreams WHERE id = 269) THEN
    RAISE EXCEPTION 'ABORT: dreams.id=269 уже существует';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM dreams WHERE id = 181 AND user_id = 1) THEN
    RAISE EXCEPTION 'ABORT: dreams.id=181 user_id=1 не найдена';
  END IF;
  IF EXISTS (SELECT 1 FROM dream_books WHERE id IN (9, 10, 11, 12, 13, 14, 16)) THEN
    RAISE EXCEPTION 'ABORT: один из id книг 9,10,11,12,13,14,16 уже занят — см. SELECT id FROM dream_books WHERE id IN (...);';
  END IF;
END $$;

-- Снимок до изменений (для отчёта в лог)
SELECT id, user_id, dream, title, rule_code, settings
FROM dreams WHERE id IN (181, 269) OR (user_id = 1 AND rule_code = 'books_reading');

SELECT id, dream_id, title FROM dream_books WHERE dream_id = 269 OR id IN (9, 10, 11, 12, 13, 14, 16);

-- =============================================================================
-- 1) Восстановить мечту 269 «Библиотека»
-- =============================================================================

INSERT INTO dreams (
  id,
  date,
  user_id,
  dream,
  what_need,
  interference,
  completion_count,
  helpers_id,
  created_at,
  updated_at,
  price,
  title,
  description,
  image_url,
  is_public,
  progress,
  deadline,
  status_id,
  category_id,
  rule_code,
  settings
) VALUES (
  269,
  '2026-05-04'::date,
  1,
  'Библиотека',
  NULL,
  NULL,
  0,
  NULL,
  '2026-05-04 22:28:42.941068'::timestamp,
  '2026-05-04 22:28:43.293492'::timestamp,
  NULL,
  NULL,
  NULL,
  NULL,
  false,
  0,
  NULL,
  2,
  NULL,
  'books_reading',
  '{"library_mode": true}'::jsonb
);

-- =============================================================================
-- 2) Восстановить книги (dream_books_log в дампе пуст — не вставляем)
-- linked_step_id в дампе 20.05 отсутствует — NULL (колонка на проде может быть из mig позже)
-- =============================================================================

INSERT INTO dream_books (id, dream_id, title, author, status, started_at, deadline, finished_at)
VALUES
  (9, 269, 'Ненасильственное общение', 'Маршал Розенберг', 'finished', NULL, NULL, NULL),
  (10, 269, 'Человек, который хотел быть счастливым"', 'Лоран Гунель', 'finished', NULL, '2026-05-17'::date, NULL),
  (11, 269, 'На дне', 'Максим Горький', 'finished', NULL, '2026-05-10'::date, NULL),
  (12, 269, 'Вторая жизнь Уве"', 'Фредерик Бакман', 'planned', NULL, '2026-05-24'::date, NULL),
  (13, 269, 'Мозг долгожителя', 'Алексей Москалёв', 'planned', NULL, '2026-05-31'::date, NULL),
  (14, 269, 'Вторники с Морри"', 'Митч Элбом', 'planned', NULL, '2026-06-07'::date, NULL),
  (16, 269, 'Создатель чат жпт, история Сэма Альтмана', 'Кич Хэйги', 'listening', NULL, '2026-05-24'::date, NULL);

-- Если на проде есть linked_step_id — раскомментировать и заполнить при необходимости:
-- UPDATE dream_books SET linked_step_id = NULL WHERE dream_id = 269;

-- =============================================================================
-- 3) Patch мечты 181 (отображение в списке; rule_code НЕ трогаем — библиотека только на 269)
-- =============================================================================

UPDATE dreams
SET
  title = COALESCE(NULLIF(TRIM(title), ''), TRIM(dream)),
  updated_at = NOW()
WHERE id = 181
  AND user_id = 1;

-- =============================================================================
-- Sequences (после явных id)
-- =============================================================================

SELECT setval(
  pg_get_serial_sequence('dreams', 'id'),
  (SELECT COALESCE(MAX(id), 1) FROM dreams)
);

SELECT setval(
  pg_get_serial_sequence('dream_books', 'id'),
  (SELECT COALESCE(MAX(id), 1) FROM dream_books)
);

-- =============================================================================
-- Проверка после restore
-- =============================================================================

SELECT id, user_id, dream, title, rule_code, settings
FROM dreams WHERE id IN (181, 269);

SELECT id, dream_id, title, author, status
FROM dream_books WHERE dream_id = 269 ORDER BY id;

SELECT COUNT(*) AS books_269 FROM dream_books WHERE dream_id = 269;

COMMIT;

-- Smoke (вне транзакции, с хоста):
--   curl -sk 'https://islanddream.ru/dreams?user_id=1' | jq '.dreams[] | select(.id==181 or .id==269) | {id, title, dream, rule_code, books: (.books|length)}'
