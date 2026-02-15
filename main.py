import os
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
from passlib.hash import bcrypt

# 1. Загружаем секреты из файла .env
load_dotenv()

# 2. Создаем Диспетчера
app = FastAPI()

# --- БЛОК БЕЗОПАСНОСТИ (CORS) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Разрешить всем
    allow_methods=["*"], # Разрешить любые методы
    allow_headers=["*"], # Разрешить любые заголовки
)
# -------------------------------

# Модели данных
class UserLogin(BaseModel):
    phone: str
    password: str

class UserRegister(BaseModel):
    name: str
    surname: str
    phone: str
    city: str
    password: str

class UserCreate(BaseModel):
    full_name: str
    phone: str
    city: str
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    password: Optional[str] = None

def get_db_connection():
    """Создаёт мост к Складу (PostgreSQL) используя данные из .env"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
        cursor_factory=RealDictCursor
    )

@app.get("/")
def read_root():
    """Главное окно — приветствие"""
    return {"message": "Welcome to the Island! API is running."}

@app.get("/admin", response_class=FileResponse)
def admin_page():
    """Админка — веб-интерфейс для управления пользователями"""
    return FileResponse(Path(__file__).parent / "admin.html")

@app.get("/index.html", response_class=FileResponse)
def index_page():
    """Личный кабинет (вход и регистрация)"""
    return FileResponse(Path(__file__).parent / "index.html")

# --- Эндпоинт 1: АВТОРИЗАЦИЯ ---
@app.post("/login")
def login_user(user_login: UserLogin):
    """
    Эндпоинт для авторизации.
    Ищет по телефону, проверяет пароль через bcrypt, отдаёт full_name (name + surname).
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            phone_alt = ("+7" + user_login.phone[1:]) if user_login.phone.startswith("8") and len(user_login.phone) >= 11 else user_login.phone
            cur.execute("""
                SELECT id, name, surname, city, phone, password_hash 
                FROM users 
                WHERE phone = %s OR phone = %s
            """, (user_login.phone, phone_alt))
            user_data = cur.fetchone()

            if user_data is None:
                raise HTTPException(status_code=400, detail="Пользователь с таким телефоном не найден")

            stored = user_data["password_hash"] or ""
            # Поддержка и bcrypt-хеша, и старого пароля в открытом виде (для уже существующих пользователей)
            if stored.startswith("$2b$") or stored.startswith("$2a$"):
                if not bcrypt.verify(user_login.password, stored):
                    raise HTTPException(status_code=400, detail="Неверный пароль")
            else:
                if stored != user_login.password:
                    raise HTTPException(status_code=400, detail="Неверный пароль")

            full_name = f"{user_data['name'] or ''} {user_data['surname'] or ''}".strip() or "Пользователь"
            return {
                "id": user_data["id"],
                "full_name": full_name,
                "city": user_data["city"],
                "phone": user_data["phone"],
                "dream": "Мечта загружается..."
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")
    finally:
        conn.close()

# --- Эндпоинт: РЕГИСТРАЦИЯ ---
@app.post("/register")
def register_user(user: UserRegister):
    """Регистрация: name, surname, phone, city; пароль хешируется bcrypt."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            phone_alt = ("+7" + user.phone[1:]) if user.phone.startswith("8") and len(user.phone) >= 11 else user.phone
            cur.execute("SELECT id FROM users WHERE phone = %s OR phone = %s", (user.phone, phone_alt))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Пользователь с таким телефоном уже зарегистрирован")
            cur.execute("""
                INSERT INTO users (name, surname, phone, city, password_hash)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (user.name.strip(), user.surname.strip(), user.phone, user.city.strip(), bcrypt.hash(user.password)))
            row = cur.fetchone()
        conn.commit()
        return {"id": row["id"]}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")
    finally:
        conn.close()

# --- Эндпоинт 2: ПОЛУЧЕНИЕ МЕЧТ ПОЛЬЗОВАТЕЛЯ ---
@app.get("/dreams")
def get_dreams(user_id: int):  # Теперь ждём ID от браузера
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Пробуем колонку dream; если нет — dream_text (разные версии схемы)
            try:
                cur.execute("SELECT dream FROM dreams WHERE user_id = %s", (user_id,))
            except psycopg2.ProgrammingError:
                cur.execute("SELECT dream_text AS dream FROM dreams WHERE user_id = %s", (user_id,))
            dreams_rows = cur.fetchall()
            dreams_list = [row["dream"] for row in dreams_rows]
            return {"dreams": dreams_list}
    except psycopg2.ProgrammingError as e:
        raise HTTPException(
            status_code=500,
            detail=f"БД: таблица dreams отсутствует или другая ошибка. Выполни в psql: CREATE TABLE dreams (id SERIAL PRIMARY KEY, user_id INT REFERENCES users(id), dream TEXT, date TIMESTAMP DEFAULT NOW()); INSERT INTO dreams (user_id, dream) VALUES (1, 'Моя мечта'); Текст ошибки: {e!s}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")
    finally:
        conn.close()


def _full_name(row: dict) -> str:
    """Склейка name + surname для ответа админки (схема БД: name, surname)."""
    n = (row.get("name") or "").strip()
    s = (row.get("surname") or "").strip()
    return f"{n} {s}".strip() or "—"

def _split_full_name(full_name: str) -> tuple:
    """Разбивка «ФИО» на name и surname (первое слово — имя, остальное — фамилия)."""
    parts = (full_name or "").strip().split(maxsplit=1)
    return (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")

# --- Админ API (схема БД: name, surname) ---
@app.get("/admin/users")
def admin_list_users():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, surname, phone, city FROM users ORDER BY id")
            rows = cur.fetchall()
            return [{"id": r["id"], "full_name": _full_name(r), "phone": r["phone"], "city": r["city"]} for r in rows]
    finally:
        conn.close()

@app.get("/admin/users/{user_id}")
def admin_get_user(user_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, surname, phone, city FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            return {"id": row["id"], "full_name": _full_name(row), "phone": row["phone"], "city": row["city"]}
    finally:
        conn.close()

@app.post("/admin/users")
def admin_create_user(user: UserCreate):
    conn = get_db_connection()
    try:
        conn.autocommit = False
        name, surname = _split_full_name(user.full_name)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (name, surname, phone, city, password_hash)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, surname, phone, city
            """, (name, surname, user.phone, user.city, bcrypt.hash(user.password)))
            row = cur.fetchone()
            conn.commit()
            return {"id": row["id"], "full_name": _full_name(row), "phone": row["phone"], "city": row["city"]}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Телефон уже занят")
    finally:
        conn.close()

@app.put("/admin/users/{user_id}")
def admin_update_user(user_id: int, user: UserUpdate):
    conn = get_db_connection()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, surname, phone, city, password_hash FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            name, surname = _split_full_name(user.full_name) if user.full_name is not None else (row["name"], row["surname"])
            phone = user.phone if user.phone is not None else row["phone"]
            city = user.city if user.city is not None else row["city"]
            password_hash = bcrypt.hash(user.password) if user.password else row["password_hash"]
            cur.execute("""
                UPDATE users SET name = %s, surname = %s, phone = %s, city = %s, password_hash = %s
                WHERE id = %s RETURNING id, name, surname, phone, city
            """, (name, surname, phone, city, password_hash, user_id))
            updated = cur.fetchone()
            conn.commit()
            return {"id": updated["id"], "full_name": _full_name(updated), "phone": updated["phone"], "city": updated["city"]}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Телефон уже занят")
    finally:
        conn.close()

@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
        conn.commit()
        return {"message": "Пользователь удалён"}
    finally:
        conn.close()