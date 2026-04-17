-- waived / completed_late на шагах + дневник dreams_steps_events
-- Идемпотентно: безопасно повторять после восстановления дампа.

ALTER TABLE dreams_steps
  ADD COLUMN IF NOT EXISTS waived BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS completed_late BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS dreams_steps_events (
    id BIGSERIAL PRIMARY KEY,
    step_id INT NOT NULL REFERENCES dreams_steps(id) ON DELETE CASCADE,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type VARCHAR(40) NOT NULL,
    message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dreams_steps_events_user_created
  ON dreams_steps_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dreams_steps_events_step
  ON dreams_steps_events (step_id);
