-- Песочница: два фейковых бадди для Макса (user_id=1) для UI-экспериментов

BEGIN;

INSERT INTO users (name, surname, phone, city, password_hash)
SELECT 'Алекс', 'Тестов-Смотритель', '89990000091', 'Песок', '123'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE phone = '89990000091');

INSERT INTO users (name, surname, phone, city, password_hash)
SELECT 'Борис', 'Тестов-Редактор', '89990000092', 'Песок', '123'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE phone = '89990000092');

INSERT INTO user_buddy_links (viewer_id, subject_id, can_read, can_write, status)
SELECT 1, u.id, true, false, 'active'
FROM users u WHERE u.phone = '89990000091'
ON CONFLICT (viewer_id, subject_id) DO UPDATE SET
    can_read = EXCLUDED.can_read,
    can_write = EXCLUDED.can_write,
    status = 'active',
    revoked_at = NULL;

INSERT INTO user_buddy_links (viewer_id, subject_id, can_read, can_write, status)
SELECT 1, u.id, true, true, 'active'
FROM users u WHERE u.phone = '89990000092'
ON CONFLICT (viewer_id, subject_id) DO UPDATE SET
    can_read = EXCLUDED.can_read,
    can_write = EXCLUDED.can_write,
    status = 'active',
    revoked_at = NULL;

INSERT INTO user_buddy_links (viewer_id, subject_id, can_read, can_write, status)
SELECT u.id, 1, true, false, 'active'
FROM users u WHERE u.phone IN ('89990000091', '89990000092')
ON CONFLICT (viewer_id, subject_id) DO UPDATE SET
    can_read = EXCLUDED.can_read,
    can_write = EXCLUDED.can_write,
    status = 'active',
    revoked_at = NULL;

COMMIT;
