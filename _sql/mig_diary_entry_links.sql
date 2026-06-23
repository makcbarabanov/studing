-- Свободные записи дневника: несколько привязок к мечтам/шагам в одной строке
-- Идемпотентно.

ALTER TABLE dreams_steps_events
  ADD COLUMN IF NOT EXISTS linked_dream_ids JSONB NULL,
  ADD COLUMN IF NOT EXISTS linked_step_ids JSONB NULL;
