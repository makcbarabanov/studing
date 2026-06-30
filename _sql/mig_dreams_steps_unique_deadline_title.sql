CREATE UNIQUE INDEX IF NOT EXISTS idx_dreams_steps_unique_deadline_title ON dreams_steps (dream_id, deadline, title) WHERE deadline IS NOT NULL AND COALESCE(deleted, false) = false;
