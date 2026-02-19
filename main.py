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

class DreamCreate(BaseModel):
    user_id: int
    dream: str
    status: Optional[str] = "planned"
    deadline: Optional[str] = None  # YYYY-MM-DD

class DreamUpdate(BaseModel):
    dream: Optional[str] = None
    status: Optional[str] = None
    deadline: Optional[str] = None  # YYYY-MM-DD or null to clear

class StepCreate(BaseModel):
    title: str

class StepUpdate(BaseModel):
    title: Optional[str] = None
    completed: Optional[bool] = None

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
def get_dreams(user_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Запросы по приоритету: без deadline, потом с deadline; поддержка dream и dream_text
            try:
                cur.execute(
                    "SELECT id, dream, status, category, price FROM dreams WHERE user_id = %s ORDER BY id",
                    (user_id,),
                )
            except psycopg2.ProgrammingError:
                conn.rollback()
                try:
                    cur.execute(
                        "SELECT id, dream, status FROM dreams WHERE user_id = %s ORDER BY id",
                        (user_id,),
                    )
                except psycopg2.ProgrammingError:
                    conn.rollback()
                    try:
                        cur.execute(
                            "SELECT id, dream, status, deadline FROM dreams WHERE user_id = %s ORDER BY id",
                            (user_id,),
                        )
                    except psycopg2.ProgrammingError:
                        conn.rollback()
                        try:
                            cur.execute("SELECT id, dream FROM dreams WHERE user_id = %s ORDER BY id", (user_id,))
                        except psycopg2.ProgrammingError:
                            conn.rollback()
                            cur.execute("SELECT id, COALESCE(dream, '') AS title FROM dreams WHERE user_id = %s ORDER BY id", (user_id,))
            dreams_rows = cur.fetchall()
            if not dreams_rows:
                return {"dreams": []}
            row0 = dreams_rows[0]
            has_full_schema = "description" in row0 or "progress" in row0
            dream_ids = [r["id"] for r in dreams_rows]
            steps_by_dream = {}
            if dream_ids:
                try:
                    cur.execute(
                        "SELECT dream_id, id, title, completed, sort_order FROM dream_steps WHERE dream_id = ANY(%s) ORDER BY dream_id, sort_order, id",
                        (dream_ids,),
                    )
                    for s in cur.fetchall():
                        did = s["dream_id"]
                        if did not in steps_by_dream:
                            steps_by_dream[did] = []
                        steps_by_dream[did].append({"id": s["id"], "title": s["title"], "completed": bool(s["completed"])})
                except psycopg2.ProgrammingError:
                    pass
            result = []
            for row in dreams_rows:
                dream_id = row["id"]
                title = (row.get("title") or row.get("dream") or "").strip()
                dream_text = row.get("dream") or ""
                status = row.get("status") or "planned"
                dl = row.get("deadline")
                deadline = str(dl) if dl is not None else None
                steps = steps_by_dream.get(dream_id, [])
                category = row.get("category")
                price = row.get("price")
                if price is not None and hasattr(price, "__float__"):
                    try:
                        price = float(price)
                    except (TypeError, ValueError):
                        price = None
                if has_full_schema:
                    result.append({
                        "id": dream_id,
                        "title": title,
                        "dream": dream_text,
                        "description": row.get("description") or "",
                        "image_url": row.get("image_url"),
                        "status": status,
                        "deadline": deadline,
                        "category": category,
                        "price": price,
                        "is_public": row.get("is_public", True),
                        "progress": row.get("progress", 0),
                        "steps": steps,
                    })
                else:
                    result.append({
                        "id": dream_id,
                        "title": title,
                        "dream": dream_text,
                        "description": "",
                        "image_url": None,
                        "status": status,
                        "deadline": deadline,
                        "category": category,
                        "price": price,
                        "is_public": True,
                        "progress": 0,
                        "steps": steps,
                    })
            return {"dreams": result}
    except psycopg2.ProgrammingError as e:
        raise HTTPException(
            status_code=500,
            detail=f"БД: таблица dreams отсутствует или другая ошибка. Текст: {e!s}"
        )
    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка: {str(e)}\n{traceback.format_exc()}"
        )
    finally:
        conn.close()


@app.post("/dreams")
def create_dream(body: DreamCreate):
    """Добавить мечту. Обязательно: user_id, dream. Опционально: status, deadline (YYYY-MM-DD)."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                if body.deadline:
                    cur.execute(
                        "INSERT INTO dreams (user_id, dream, status, date, deadline) VALUES (%s, %s, %s, CURRENT_DATE, %s) RETURNING id, dream, status, deadline",
                        (body.user_id, body.dream.strip(), body.status or "planned", body.deadline),
                    )
                else:
                    cur.execute(
                        "INSERT INTO dreams (user_id, dream, status, date) VALUES (%s, %s, %s, CURRENT_DATE) RETURNING id, dream, status",
                        (body.user_id, body.dream.strip(), body.status or "planned"),
                    )
            except psycopg2.ProgrammingError:
                conn.rollback()
                cur.execute(
                    "INSERT INTO dreams (user_id, dream, date) VALUES (%s, %s, CURRENT_DATE) RETURNING id, dream",
                    (body.user_id, body.dream.strip()),
                )
            row = cur.fetchone()
            conn.commit()
            deadline = str(row["deadline"]) if row.get("deadline") else None
            return {"id": row["id"], "dream": row.get("dream") or body.dream, "status": row.get("status") or "planned", "deadline": deadline}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.patch("/dreams/{dream_id}")
def update_dream(dream_id: int, body: DreamUpdate, user_id: int):
    """Обновить мечту (текст, статус, дедлайн). Только если мечта принадлежит user_id."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM dreams WHERE id = %s AND user_id = %s", (dream_id, user_id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Мечта не найдена или не ваша")
            updates, vals = [], []
            if body.dream is not None:
                updates.append("dream = %s")
                vals.append(body.dream.strip())
            if body.status is not None:
                updates.append("status = %s")
                vals.append(body.status)
            if body.deadline is not None:
                updates.append("deadline = %s")
                vals.append(body.deadline if body.deadline else None)
            if not updates:
                return {"ok": True}
            vals.append(dream_id)
            try:
                cur.execute(
                    "UPDATE dreams SET " + ", ".join(updates) + " WHERE id = %s",
                    vals,
                )
            except psycopg2.ProgrammingError as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail="БД: " + str(e))
            conn.commit()
            return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/dreams/{dream_id}/steps")
def create_step(dream_id: int, body: StepCreate, user_id: int):
    """Добавить шаг к мечте. Только если мечта принадлежит user_id."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM dreams WHERE id = %s AND user_id = %s", (dream_id, user_id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Мечта не найдена или не ваша")
            cur.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM dream_steps WHERE dream_id = %s", (dream_id,))
            next_order = cur.fetchone()["next_order"]
            cur.execute(
                "INSERT INTO dream_steps (dream_id, title, completed, sort_order) VALUES (%s, %s, false, %s) RETURNING id, title, completed",
                (dream_id, body.title.strip(), next_order),
            )
            row = cur.fetchone()
            conn.commit()
            return {"id": row["id"], "title": row["title"], "completed": bool(row["completed"])}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.patch("/dreams/{dream_id}/steps/{step_id}")
def update_step(dream_id: int, step_id: int, body: StepUpdate, user_id: int):
    """Обновить шаг (название или флажок сделан/не сделан)."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM dreams WHERE id = %s AND user_id = %s", (dream_id, user_id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Мечта не найдена или не ваша")
            updates, vals = [], []
            if body.title is not None:
                updates.append("title = %s")
                vals.append(body.title.strip())
            if body.completed is not None:
                updates.append("completed = %s")
                vals.append(body.completed)
            if not updates:
                return {"ok": True}
            vals.append(step_id)
            vals.append(dream_id)
            cur.execute(
                "UPDATE dream_steps SET " + ", ".join(updates) + " WHERE id = %s AND dream_id = %s",
                vals,
            )
            conn.commit()
            return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
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