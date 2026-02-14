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

# Модель для данных входа
class UserLogin(BaseModel):
    phone: str
    password: str

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

# --- Эндпоинт 1: АВТОРИЗАЦИЯ ---
@app.post("/login")
def login_user(user_login: UserLogin):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Ищем по телефону (учитываем 8... и +7...)
            phone_alt = ("+7" + user_login.phone[1:]) if user_login.phone.startswith("8") and len(user_login.phone) >= 11 else user_login.phone
            cur.execute("""
                SELECT id, full_name, city, phone, password_hash 
                FROM users 
                WHERE phone = %s OR phone = %s
            """, (user_login.phone, phone_alt))
            
            user_data = cur.fetchone()

            if user_data is None:
                raise HTTPException(status_code=400, detail="Пользователь не найден")
            
            if not bcrypt.verify(user_login.password, user_data["password_hash"]):
                raise HTTPException(status_code=400, detail="Неверный пароль")
            
            return {
                "id": user_data["id"],
                "full_name": user_data["full_name"],
                "city": user_data["city"],
                "phone": user_data["phone"]
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")
    finally:
        conn.close()

# --- Эндпоинт 2: ПОЛУЧЕНИЕ ПРОФИЛЯ И МЕЧТ (Для теста id=1) ---
@app.get("/dreams")
def get_dreams():
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT full_name, city FROM users WHERE id = 1")
                user_info = cur.fetchone()
                if user_info is None:
                    raise HTTPException(status_code=404, detail="Пользователь не найден")

                cur.execute("SELECT dream FROM dreams WHERE user_id = 1")
                dreams_rows = cur.fetchall()
                dreams_list = [row["dream"] for row in dreams_rows]

                return {
                    "full_name": user_info["full_name"],
                    "city": user_info["city"],
                    "dreams": dreams_list
                }
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")


# --- Админ API ---
@app.get("/admin/users")
def admin_list_users():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, full_name, phone, city FROM users ORDER BY id")
            return cur.fetchall()
    finally:
        conn.close()

@app.get("/admin/users/{user_id}")
def admin_get_user(user_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, full_name, phone, city FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            return row
    finally:
        conn.close()

@app.post("/admin/users")
def admin_create_user(user: UserCreate):
    conn = get_db_connection()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (full_name, phone, city, password_hash)
                VALUES (%s, %s, %s, %s)
                RETURNING id, full_name, phone, city
            """, (user.full_name, user.phone, user.city, bcrypt.hash(user.password)))
            row = cur.fetchone()
            conn.commit()
            return row
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
            cur.execute("SELECT id, full_name, phone, city, password_hash FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            full_name = user.full_name if user.full_name is not None else row["full_name"]
            phone = user.phone if user.phone is not None else row["phone"]
            city = user.city if user.city is not None else row["city"]
            password_hash = bcrypt.hash(user.password) if user.password else row["password_hash"]
            cur.execute("""
                UPDATE users SET full_name = %s, phone = %s, city = %s, password_hash = %s
                WHERE id = %s RETURNING id, full_name, phone, city
            """, (full_name, phone, city, password_hash, user_id))
            updated = cur.fetchone()
            conn.commit()
            return updated
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