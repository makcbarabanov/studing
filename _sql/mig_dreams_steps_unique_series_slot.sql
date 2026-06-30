CREATE UNIQUE INDEX IF NOT EXISTS idx_dreams_steps_unique_series_slot ON dreams_steps (dream_id, series_id, series_index) WHERE series_id IS NOT NULL AND COALESCE(deleted, false) = false;
