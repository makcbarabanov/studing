CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(100),
    phone VARCHAR(20) UNIQUE,
    city VARCHAR(50),
    password_hash TEXT
);

-- Пароль: my_pass_123 (bcrypt hash)
INSERT INTO users (full_name, phone, city, password_hash) 
VALUES ('Максим Барабанов', '89998884433', 'Санкт-Петербург', '$2b$12$jdywcfCmp0916Dtl/zeumutWTZjjo.Z5tyUsJ03yGXkys8zruCB5C');
