-- Актуальная схема базы данных ОСТРОВ

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    surname VARCHAR(100),
    phone VARCHAR(20) UNIQUE,
    city VARCHAR(100),
    password_hash TEXT
    -- Тут могут быть и другие поля, которые мы видели в DBeaver, но это основные
);

CREATE TABLE dreams (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    dream TEXT,
    date DATE DEFAULT CURRENT_DATE
);

-- Тестовые данные
-- Пароль '123' (в реальности должен быть хеш)
INSERT INTO users (name, surname, phone, city, password_hash) 
VALUES ('Макс', 'Барабанов', '89998884433', 'Санкт-Петербург', '123');

INSERT INTO dreams (user_id, dream) 
VALUES (1, 'Запустить соцсеть Остров');