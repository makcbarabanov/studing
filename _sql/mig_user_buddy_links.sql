-- Additive migration: create or update user_buddy_links schema for Phase A
BEGIN;

CREATE TABLE IF NOT EXISTS public.user_buddy_links (
    id BIGSERIAL PRIMARY KEY,
    viewer_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    subject_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    link_type VARCHAR(100) NOT NULL DEFAULT 'custom',
    can_read BOOLEAN NOT NULL DEFAULT TRUE,
    can_write BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (viewer_id != subject_id)
);

ALTER TABLE public.user_buddy_links
    ADD COLUMN IF NOT EXISTS link_type VARCHAR(100) NOT NULL DEFAULT 'custom',
    ADD COLUMN IF NOT EXISTS can_read BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS can_write BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE public.user_buddy_links
    ALTER COLUMN viewer_id TYPE BIGINT USING viewer_id::BIGINT,
    ALTER COLUMN subject_id TYPE BIGINT USING subject_id::BIGINT;

ALTER TABLE public.user_buddy_links
    ADD CONSTRAINT IF NOT EXISTS user_buddy_links_no_self CHECK (viewer_id != subject_id);

CREATE INDEX IF NOT EXISTS idx_user_buddy_links_viewer ON public.user_buddy_links(viewer_id);
CREATE INDEX IF NOT EXISTS idx_user_buddy_links_subject ON public.user_buddy_links(subject_id);

COMMIT;
