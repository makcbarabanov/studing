-- Additive migration for prod parity:
-- brings dreams_steps schema to current API/UI contract without data loss.

ALTER TABLE dreams_steps
    ADD COLUMN IF NOT EXISTS start_time TIME NULL,
    ADD COLUMN IF NOT EXISTS end_time TIME NULL,
    ADD COLUMN IF NOT EXISTS series_id VARCHAR(100) NULL,
    ADD COLUMN IF NOT EXISTS series_index INT NULL,
    ADD COLUMN IF NOT EXISTS series_total INT NULL;

CREATE INDEX IF NOT EXISTS idx_dreams_steps_series_id ON dreams_steps(series_id);

