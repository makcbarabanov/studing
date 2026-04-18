-- Идемпотентно: индекс из mig_dreams_steps_time_and_series_columns.sql
-- На песочнице индекс idx_dreams_steps_series_id отсутствовал (частичное применение / ручной откат).
CREATE INDEX IF NOT EXISTS idx_dreams_steps_series_id ON dreams_steps(series_id);
