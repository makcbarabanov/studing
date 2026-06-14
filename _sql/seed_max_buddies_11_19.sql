-- Макс (1) → Константин (11), Александр (19); Света (17) уже есть
BEGIN;

INSERT INTO user_buddy_links (viewer_id, subject_id, can_read, can_write, status)
VALUES
    (1, 11, true, false, 'active'),
    (1, 19, true, false, 'active'),
    (11, 1, true, false, 'active'),
    (19, 1, true, false, 'active')
ON CONFLICT (viewer_id, subject_id) DO UPDATE SET
    can_read = true,
    can_write = EXCLUDED.can_write,
    status = 'active',
    revoked_at = NULL;

-- Убрать тестовых фейков из списка Макса (если были)
UPDATE user_buddy_links
SET status = 'revoked', revoked_at = NOW(), can_read = false, can_write = false
WHERE status = 'active'
  AND (
    (viewer_id = 1 AND subject_id IN (SELECT id FROM users WHERE phone IN ('89990000091', '89990000092')))
    OR (subject_id = 1 AND viewer_id IN (SELECT id FROM users WHERE phone IN ('89990000091', '89990000092')))
  );

COMMIT;
