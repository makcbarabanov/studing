-- Buddy alerts: link toggles, report-sent ledger, in-app notifications, digest idempotency.
-- Additive migration. Apply: python run_migrate.py _sql/mig_buddy_alerts.sql
-- Or via psql / bootstrap_sandbox_db.sh (see Readme/buddy-alerts.md).
BEGIN;

-- ── A. Per buddy-pair alert switches (synchronized in UI; one truth on the link) ──
ALTER TABLE public.user_buddy_links
    ADD COLUMN IF NOT EXISTS alert_steps_enabled   BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS alert_reports_enabled BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN public.user_buddy_links.alert_steps_enabled IS
    'Subject allows step alerts to this viewer; mirrored in both cabinets';
COMMENT ON COLUMN public.user_buddy_links.alert_reports_enabled IS
    'Subject allows report alerts to this viewer; mirrored in both cabinets';

-- ── B. User-level daily alert time (v1 TZ: Europe/Moscow in app/cron config) ──
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS buddy_alert_daily_at TIME NOT NULL DEFAULT '23:00:00';

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NULL;

COMMENT ON COLUMN public.users.buddy_alert_daily_at IS
    'Local time for end-of-day buddy digest (steps_missed, report_not_sent)';
COMMENT ON COLUMN public.users.timezone IS
    'IANA timezone for buddy_alert_daily_at; NULL = app default Europe/Moscow (v2)';

-- ── C. Server record: daily report was sent (copy or share) ──
CREATE TABLE IF NOT EXISTS public.buddy_step_daily_reports (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    report_date DATE NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    send_method VARCHAR(16) NOT NULL
        CHECK (send_method IN ('copy', 'share')),
    UNIQUE (user_id, report_date)
);

CREATE INDEX IF NOT EXISTS idx_buddy_step_daily_reports_user_date
    ON public.buddy_step_daily_reports (user_id, report_date DESC);

-- ── D. In-app notifications for buddies (bell) ──
CREATE TABLE IF NOT EXISTS public.buddy_alert_notifications (
    id           BIGSERIAL PRIMARY KEY,
    recipient_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    subject_id   BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    alert_type   VARCHAR(32) NOT NULL
        CHECK (alert_type IN ('steps_success_100', 'steps_missed', 'report_not_sent')),
    report_date  DATE NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at      TIMESTAMPTZ NULL,
    UNIQUE (recipient_id, subject_id, alert_type, report_date)
);

CREATE INDEX IF NOT EXISTS idx_buddy_alert_notif_recipient_created
    ON public.buddy_alert_notifications (recipient_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_buddy_alert_notif_unread
    ON public.buddy_alert_notifications (recipient_id)
    WHERE read_at IS NULL;

-- ── E. Idempotency: 23:00 digest must not fire twice for same subject/day/kind ──
CREATE TABLE IF NOT EXISTS public.buddy_daily_digest_runs (
    id           BIGSERIAL PRIMARY KEY,
    subject_id   BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    report_date  DATE NOT NULL,
    digest_kind  VARCHAR(32) NOT NULL
        CHECK (digest_kind IN ('steps_missed', 'report_not_sent')),
    ran_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (subject_id, report_date, digest_kind)
);

COMMIT;
