-- Песочница: догоняем схему до контракта main.py (идемпотентно, без удаления данных).
-- Не удалять после run_migrate — применять через psql или bootstrap_sandbox_db.sh

-- === users ===
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_path VARCHAR(255) NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS buddy_id INT NULL REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS buddy_trust BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram VARCHAR(100) NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vk VARCHAR(255) NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS gender VARCHAR(1) NULL;

-- === dreams ===
ALTER TABLE dreams ADD COLUMN IF NOT EXISTS status_id INT NOT NULL DEFAULT 1;
ALTER TABLE dreams ADD COLUMN IF NOT EXISTS category_id INT NULL;
ALTER TABLE dreams ADD COLUMN IF NOT EXISTS deadline DATE NULL;
ALTER TABLE dreams ADD COLUMN IF NOT EXISTS price NUMERIC(12,2) NULL;
ALTER TABLE dreams ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT true;
ALTER TABLE dreams ADD COLUMN IF NOT EXISTS title VARCHAR(500) NULL;
ALTER TABLE dreams ADD COLUMN IF NOT EXISTS rule_code VARCHAR(100) NULL;
ALTER TABLE dreams ADD COLUMN IF NOT EXISTS settings JSONB NULL;

-- === справочники ===
CREATE TABLE IF NOT EXISTS dreams_statuses (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    label_ru VARCHAR(100) NOT NULL,
    icon VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS dreams_categories (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    label_ru VARCHAR(100) NOT NULL,
    icon VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS steps_rules (
    id SERIAL PRIMARY KEY,
    category_code VARCHAR(50) NOT NULL,
    rule_code VARCHAR(100) NOT NULL,
    rules JSONB,
    comment TEXT,
    UNIQUE (category_code, rule_code)
);

-- === шаги ===
CREATE TABLE IF NOT EXISTS dreams_steps (
    id SERIAL PRIMARY KEY,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    completed BOOLEAN DEFAULT false,
    sort_order INT DEFAULT 0
);

ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS deadline DATE NULL;
ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS start_time TIME NULL;
ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS end_time TIME NULL;
ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS series_id VARCHAR(100) NULL;
ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS series_index INT NULL;
ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS series_total INT NULL;
ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS deleted BOOLEAN DEFAULT false;
ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS waived BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS completed_late BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS plan_amount NUMERIC(12,2) NULL;
ALTER TABLE dreams_steps ADD COLUMN IF NOT EXISTS fact_amount NUMERIC(12,2) NULL;

CREATE INDEX IF NOT EXISTS idx_dreams_steps_dream_id ON dreams_steps(dream_id);
CREATE INDEX IF NOT EXISTS idx_dreams_steps_series_id ON dreams_steps(series_id);

-- === дневник ===
CREATE TABLE IF NOT EXISTS dreams_steps_events (
    id BIGSERIAL PRIMARY KEY,
    step_id INT NOT NULL REFERENCES dreams_steps(id) ON DELETE CASCADE,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type VARCHAR(40) NOT NULL,
    message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE dreams_steps_events ADD COLUMN IF NOT EXISTS linked_dream_ids JSONB NULL;
ALTER TABLE dreams_steps_events ADD COLUMN IF NOT EXISTS linked_step_ids JSONB NULL;

CREATE INDEX IF NOT EXISTS idx_dreams_steps_events_user_created
  ON dreams_steps_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dreams_steps_events_step
  ON dreams_steps_events (step_id);

-- === dreams_log ===
CREATE TABLE IF NOT EXISTS dreams_log (
    id SERIAL PRIMARY KEY,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    fulfilled_by_user_id INT NOT NULL REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_dreams_log_dream_id ON dreams_log(dream_id);
CREATE INDEX IF NOT EXISTS idx_dreams_log_fulfilled_by ON dreams_log(fulfilled_by_user_id);

-- === книги ===
CREATE TABLE IF NOT EXISTS dream_books (
    id SERIAL PRIMARY KEY,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    author VARCHAR(300) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'planned',
    started_at DATE NULL,
    deadline DATE NULL,
    finished_at DATE NULL,
    linked_step_id INT NULL REFERENCES dreams_steps(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_dream_books_dream_id ON dream_books(dream_id);
CREATE INDEX IF NOT EXISTS idx_dream_books_status ON dream_books(status);
CREATE INDEX IF NOT EXISTS idx_dream_books_linked_step_id ON dream_books(linked_step_id);

CREATE TABLE IF NOT EXISTS dream_books_log (
    id SERIAL PRIMARY KEY,
    book_id INT NOT NULL REFERENCES dream_books(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    minutes_spent INT NULL,
    pages_read INT NULL,
    UNIQUE (book_id, date)
);
CREATE INDEX IF NOT EXISTS idx_dream_books_log_book_date ON dream_books_log(book_id, date);

-- === витрина / уведомления ===
CREATE TABLE IF NOT EXISTS user_dream_views (
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    viewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, dream_id)
);

CREATE TABLE IF NOT EXISTS user_dream_favorites (
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, dream_id)
);

CREATE TABLE IF NOT EXISTS dream_favorite_notifications (
    id SERIAL PRIMARY KEY,
    owner_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_dream_help_intent (
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, dream_id)
);

-- === roadmap ===
CREATE TABLE IF NOT EXISTS roadmap (
    id SERIAL PRIMARY KEY,
    step INT NOT NULL,
    text TEXT NOT NULL,
    section VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'plan',
    initiator VARCHAR(100),
    count INT NOT NULL DEFAULT 1,
    date_added DATE,
    date_done DATE,
    priority VARCHAR(20),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_roadmap_status ON roadmap(status);
CREATE INDEX IF NOT EXISTS idx_roadmap_section ON roadmap(section);
