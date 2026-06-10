-- Buddy links v1: directed viewer→subject permissions (replaces users.buddy_id over time)
-- Branch: feat/buddy-system | Additive only — users.buddy_id kept for fallback
-- Run: psql -f _sql/mig_user_buddy_links.sql (sandbox first)

BEGIN;

CREATE TABLE IF NOT EXISTS user_buddy_links (
    id SERIAL PRIMARY KEY,
    viewer_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    can_read BOOLEAN NOT NULL DEFAULT true,
    can_write BOOLEAN NOT NULL DEFAULT false,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    CONSTRAINT user_buddy_links_viewer_subject_uniq UNIQUE (viewer_id, subject_id),
    CONSTRAINT user_buddy_links_no_self CHECK (viewer_id != subject_id),
    CONSTRAINT user_buddy_links_status_chk CHECK (status IN ('pending', 'active', 'revoked'))
);

CREATE INDEX IF NOT EXISTS idx_user_buddy_links_viewer_active
    ON user_buddy_links (viewer_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_user_buddy_links_subject_active
    ON user_buddy_links (subject_id)
    WHERE status = 'active';

-- Backfill from legacy 1:1 buddy_id (one row per user who has a buddy)
-- can_write mirrors editor-side buddy_trust (see _can_edit_buddy_dream in main.py)
INSERT INTO user_buddy_links (viewer_id, subject_id, can_read, can_write, status)
SELECT
    u.id,
    u.buddy_id,
    true,
    COALESCE(u.buddy_trust, false),
    'active'
FROM users u
WHERE u.buddy_id IS NOT NULL
ON CONFLICT (viewer_id, subject_id) DO UPDATE SET
    can_read = EXCLUDED.can_read,
    can_write = EXCLUDED.can_write,
    status = 'active',
    revoked_at = NULL;

COMMIT;
