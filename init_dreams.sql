-- Таблица мечт (если её ещё нет в БД)
CREATE TABLE IF NOT EXISTS dreams (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    dream TEXT,
    date TIMESTAMP DEFAULT NOW()
);

-- Пример мечты для user_id = 1
INSERT INTO dreams (user_id, dream) VALUES (1, 'Создать лучшую соцсеть в мире');
