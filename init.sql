CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(100),
    phone VARCHAR(20) UNIQUE,
    city VARCHAR(50),
    password_text TEXT
);

INSERT INTO users (full_name, phone, city, password_text) 
VALUES ('Максим Барабанов', '89998884433', 'Санкт-Петербург', 'my_pass_123');
