import os
import time
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
from passlib.hash import bcrypt

# 1. Загружаем секреты из файла .env
load_dotenv()

# 2. Создаем Диспетчера
app = FastAPI()

# Каталоги для медиа: раздача по /media и сохранение аватаров
BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "media"
AVATARS_DIR = MEDIA_DIR / "avatars"
AVATARS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

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
    status_id: Optional[int] = 1  # 1 = planned (справочник dreams_statuses)
    category_id: Optional[int] = None
    deadline: Optional[str] = None  # YYYY-MM-DD
    price: Optional[float] = None  # рубли

class DreamUpdate(BaseModel):
    dream: Optional[str] = None
    status_id: Optional[int] = None
    category_id: Optional[int] = None
    deadline: Optional[str] = None  # YYYY-MM-DD or null to clear
    price: Optional[float] = None  # рубли
    is_public: Optional[bool] = None

class StepCreate(BaseModel):
    title: str
    deadline: Optional[str] = None  # YYYY-MM-DD

class StepUpdate(BaseModel):
    title: Optional[str] = None
    completed: Optional[bool] = None
    deadline: Optional[str] = None  # YYYY-MM-DD
    deleted: Optional[bool] = None  # мягкое удаление / восстановление

def _load_steps(cur, dream_ids):
    """Загружает шаги по списку dream_id. Возвращает dict dream_id -> list of {id, title, completed, deadline, deleted}."""
    out = {}
    if not dream_ids:
        return out
    try:
        cur.execute(
            "SELECT dream_id, id, title, completed, sort_order, deadline, deleted FROM dreams_steps WHERE dream_id = ANY(%s) ORDER BY dream_id, sort_order, id",
            (dream_ids,),
        )
        for s in cur.fetchall():
            did = s["dream_id"]
            if did not in out:
                out[did] = []
            dl = s.get("deadline")
            out[did].append({
                "id": s["id"],
                "title": s["title"],
                "completed": bool(s["completed"]),
                "deadline": str(dl) if dl else None,
                "deleted": bool(s.get("deleted", False)),
            })
    except psycopg2.ProgrammingError:
        cur.connection.rollback()
        try:
            cur.execute(
                "SELECT dream_id, id, title, completed, sort_order FROM dreams_steps WHERE dream_id = ANY(%s) ORDER BY dream_id, sort_order, id",
                (dream_ids,),
            )
            for s in cur.fetchall():
                did = s["dream_id"]
                if did not in out:
                    out[did] = []
                out[did].append({
                    "id": s["id"], "title": s["title"], "completed": bool(s["completed"]),
                    "deadline": None, "deleted": False,
                })
        except psycopg2.ProgrammingError:
            pass
    return out

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
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            phone_alt = ("+7" + user_login.phone[1:]) if user_login.phone.startswith("8") and len(user_login.phone) >= 11 else user_login.phone
            try:
                cur.execute("""
                    SELECT id, name, surname, city, phone, password_hash, avatar_path, buddy_id, buddy_trust
                    FROM users
                    WHERE phone = %s OR phone = %s
                """, (user_login.phone, phone_alt))
            except psycopg2.ProgrammingError:
                conn.rollback()
                cur.execute("""
                    SELECT id, name, surname, city, phone, password_hash, avatar_path, buddy_id
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
            avatar_path = user_data.get("avatar_path")
            buddy_id = user_data.get("buddy_id")
            buddy_trust = bool(user_data.get("buddy_trust"))
            buddy_name = None
            if buddy_id:
                cur.execute("SELECT name, surname FROM users WHERE id = %s", (buddy_id,))
                buddy_row = cur.fetchone()
                if buddy_row:
                    buddy_name = f"{buddy_row.get('name') or ''} {buddy_row.get('surname') or ''}".strip() or None
            return {
                "id": user_data["id"],
                "full_name": full_name,
                "city": user_data["city"],
                "phone": user_data["phone"],
                "avatar_path": avatar_path,
                "buddy_id": buddy_id,
                "buddy_trust": buddy_trust,
                "buddy_name": buddy_name,
                "dream": "Мечта загружается..."
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")
    finally:
        conn.close()


@app.get("/landing_stats")
def landing_stats():
    """Публичная статистика для лендинга: сколько мечт исполнено (из dreams_log), сколько участников (users)."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            fulfilled_dreams = 0
            try:
                cur.execute("SELECT COUNT(DISTINCT dream_id) AS n FROM dreams_log")
                row = cur.fetchone()
                if row:
                    fulfilled_dreams = row.get("n") or 0
            except psycopg2.ProgrammingError:
                pass
            cur.execute("SELECT COUNT(*) AS n FROM users")
            users_count = cur.fetchone().get("n") or 0
        return {"fulfilled_dreams": fulfilled_dreams, "users_count": users_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# --- Эндпоинт: ЗАГРУЗКА АВАТАРА ---
AVATAR_EXTENSIONS = frozenset((".jpg", ".jpeg", ".png", ".webp", ".gif"))
AVATAR_MAX_BYTES = 2 * 1024 * 1024  # 2 МБ

@app.post("/avatar")
def upload_avatar(user_id: int, file: UploadFile = File(...)):
    """Загрузить аватар пользователя. Файл сохраняется в media/avatars/{user_id}.{ext}, в БД — avatar_path."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Файл не выбран")
    ext = Path(file.filename).suffix.lower()
    if ext not in AVATAR_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Разрешены только jpg, png, webp, gif (в т.ч. анимированный)")
    content = file.file.read()
    if len(content) > AVATAR_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Файл не более 2 МБ")
    # Сохраняем как avatars/{user_id}.{ext}
    safe_ext = ".jpg" if ext == ".jpeg" else ext
    filename = f"{user_id}{safe_ext}"
    filepath = AVATARS_DIR / filename
    try:
        filepath.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить файл: {str(e)}")
    avatar_path = f"avatars/{filename}"
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("UPDATE users SET avatar_path = %s WHERE id = %s", (avatar_path, user_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка БД: {str(e)}")
    finally:
        conn.close()
    return {"ok": True, "avatar_path": avatar_path}

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

# --- Справочники для мечт ---
@app.get("/dreams_statuses")
def list_dream_statuses():
    """Список статусов мечты (id, code, label_ru, icon)."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, code, label_ru, icon FROM dreams_statuses ORDER BY id")
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@app.get("/dreams_categories")
@app.get("/dream_categories")  # алиас для обратной совместимости
def list_dream_categories():
    """Список категорий мечты (id, code, label_ru, icon)."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, code, label_ru, icon FROM dreams_categories ORDER BY id")
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def _can_edit_buddy_dream(cur, editor_id: int, dream_owner_id: int) -> bool:
    """Проверяет, может ли editor_id редактировать мечты владельца dream_owner_id (свои или бадди с доверием)."""
    if editor_id == dream_owner_id:
        return True
    cur.execute("SELECT buddy_id, buddy_trust FROM users WHERE id = %s", (editor_id,))
    row = cur.fetchone()
    return bool(row and row.get("buddy_id") == dream_owner_id and row.get("buddy_trust"))

def _resolve_editor_and_check_dream(cur, dream_id: int, user_id: int, viewer_id: Optional[int]) -> int:
    """Возвращает user_id владельца мечты и проверяет, что текущий запросчик (editor) может её редактировать. Иначе 403/404."""
    cur.execute("SELECT id, user_id FROM dreams WHERE id = %s", (dream_id,))
    dream = cur.fetchone()
    if not dream:
        raise HTTPException(status_code=404, detail="Мечта не найдена")
    owner_id = dream["user_id"]
    editor_id = viewer_id if viewer_id is not None else user_id
    if not _can_edit_buddy_dream(cur, editor_id, owner_id):
        raise HTTPException(status_code=403, detail="Нет права редактировать эту мечту")
    return owner_id

def _build_dream_item(row, steps_by_dream):
    """Собирает один элемент для ответа GET /dreams из строки БД."""
    dream_id = row["id"]
    title = (row.get("dream") or "").strip()
    dream_text = row.get("dream") or ""
    dl = row.get("deadline")
    deadline = str(dl) if dl is not None else None
    steps = steps_by_dream.get(dream_id, [])
    price = row.get("price")
    if price is not None and hasattr(price, "__float__"):
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None
    status_obj = None
    if row.get("status_code"):
        status_obj = {"id": row.get("status_id"), "code": row.get("status_code"), "label_ru": row.get("status_label"), "icon": row.get("status_icon")}
    category_obj = None
    if row.get("category_id") and row.get("category_code"):
        category_obj = {"id": row.get("category_id"), "code": row.get("category_code"), "label_ru": row.get("category_label"), "icon": row.get("category_icon")}
    return {
        "id": dream_id,
        "title": title,
        "dream": dream_text,
        "description": "",
        "image_url": None,
        "status": row.get("status_code") or "planned",
        "status_obj": status_obj,
        "deadline": deadline,
        "category": row.get("category_code"),
        "category_obj": category_obj,
        "price": price,
        "is_public": row.get("is_public") if row.get("is_public") is not None else True,
        "progress": 0,
        "steps": steps,
    }

# --- Эндпоинт 2: ПОЛУЧЕНИЕ МЕЧТ ПОЛЬЗОВАТЕЛЯ ---
@app.get("/dreams")
def get_dreams(user_id: int, viewer_id: Optional[int] = None):
    """Список мечт пользователя user_id. Если передан viewer_id: отдаём только если viewer_id == user_id или viewer — бадди user_id (users.buddy_id у viewer = user_id)."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if viewer_id is not None and viewer_id != user_id:
                cur.execute("SELECT buddy_id FROM users WHERE id = %s", (viewer_id,))
                row = cur.fetchone()
                if not row or row.get("buddy_id") != user_id:
                    raise HTTPException(status_code=403, detail="Нет доступа к мечтам этого пользователя")
            dreams_rows = None
            try:
                cur.execute("""
                    SELECT d.id, d.dream, d.deadline, d.price, d.status_id, d.category_id, d.is_public,
                           s.code AS status_code, s.label_ru AS status_label, s.icon AS status_icon,
                           c.code AS category_code, c.label_ru AS category_label, c.icon AS category_icon
                    FROM dreams d
                    LEFT JOIN dreams_statuses s ON d.status_id = s.id
                    LEFT JOIN dreams_categories c ON d.category_id = c.id
                    WHERE d.user_id = %s ORDER BY d.id
                """, (user_id,))
                dreams_rows = cur.fetchall()
            except psycopg2.ProgrammingError:
                conn.rollback()
                try:
                    cur.execute(
                        "SELECT id, dream, deadline, price, status_id, category_id, is_public FROM dreams WHERE user_id = %s ORDER BY id",
                        (user_id,),
                    )
                    dreams_rows = cur.fetchall()
                    for r in dreams_rows:
                        r["status_code"] = "planned"
                        r["status_label"] = r["category_code"] = r["category_label"] = r["status_icon"] = r["category_icon"] = None
                        if r.get("is_public") is None:
                            r["is_public"] = True
                        try:
                            cur.execute("SELECT id, code, label_ru, icon FROM dreams_categories")
                            cat_map = {row["id"]: dict(row) for row in cur.fetchall()}
                            for r in dreams_rows:
                                cid = r.get("category_id")
                                if cid and cid in cat_map:
                                    c = cat_map[cid]
                                    r["category_code"] = c.get("code")
                                    r["category_label"] = c.get("label_ru")
                                    r["category_icon"] = c.get("icon")
                        except psycopg2.ProgrammingError:
                            pass
                except psycopg2.ProgrammingError:
                    conn.rollback()
                    try:
                        cur.execute(
                            "SELECT id, dream, deadline FROM dreams WHERE user_id = %s ORDER BY id",
                            (user_id,),
                        )
                        dreams_rows = [dict(r) for r in cur.fetchall()]
                        for r in dreams_rows:
                            r["price"] = r["status_id"] = r["category_id"] = None
                            r["status_code"] = "planned"
                            r["status_label"] = r["category_code"] = r["category_label"] = r["status_icon"] = r["category_icon"] = None
                            if r.get("is_public") is None:
                                r["is_public"] = True
                    except psycopg2.ProgrammingError:
                        conn.rollback()
                        cur.execute("SELECT id, dream FROM dreams WHERE user_id = %s ORDER BY id", (user_id,))
                        dreams_rows = [dict(r) for r in cur.fetchall()]
                        for r in dreams_rows:
                            r["deadline"] = r["price"] = r["status_id"] = r["category_id"] = None
                            r["status_code"] = "planned"
                            r["status_label"] = r["category_code"] = r["category_label"] = r["status_icon"] = r["category_icon"] = None
                            r["is_public"] = True
            if not dreams_rows:
                dreams_fulfilled_by_me = 0
                try:
                    cur.execute("SELECT COUNT(*) AS n FROM dreams_log L JOIN dreams D ON D.id = L.dream_id WHERE L.fulfilled_by_user_id = %s AND D.user_id != %s", (user_id, user_id))
                    dreams_fulfilled_by_me = cur.fetchone().get("n") or 0
                except (psycopg2.ProgrammingError, AttributeError):
                    pass
                return {"dreams": [], "dreams_fulfilled_count": 0, "dreams_fulfilled_times": 0, "dreams_fulfilled_by_me": dreams_fulfilled_by_me}
            dream_ids = [r["id"] for r in dreams_rows]
            steps_by_dream = _load_steps(cur, dream_ids)
            result = [_build_dream_item(row, steps_by_dream) for row in dreams_rows]
            dreams_fulfilled_count = 0
            dreams_fulfilled_times = 0
            dreams_fulfilled_by_me = 0
            try:
                cur.execute("""
                    SELECT COUNT(DISTINCT dream_id) AS dreams_count, COUNT(*) AS times_count
                    FROM dreams_log WHERE dream_id = ANY(%s)
                """, (dream_ids,))
                row = cur.fetchone()
                if row:
                    dreams_fulfilled_count = row.get("dreams_count") or 0
                    dreams_fulfilled_times = row.get("times_count") or 0
                cur.execute("""
                    SELECT COUNT(*) AS n FROM dreams_log L JOIN dreams D ON D.id = L.dream_id
                    WHERE L.fulfilled_by_user_id = %s AND D.user_id != %s
                """, (user_id, user_id))
                row = cur.fetchone()
                if row:
                    dreams_fulfilled_by_me = row.get("n") or 0
            except psycopg2.ProgrammingError:
                pass
            return {
                "dreams": result,
                "dreams_fulfilled_count": dreams_fulfilled_count,
                "dreams_fulfilled_times": dreams_fulfilled_times,
                "dreams_fulfilled_by_me": dreams_fulfilled_by_me,
            }
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
    """Добавить мечту. Обязательно: user_id, dream. Опционально: status_id (по умолчанию 1), category_id, deadline (YYYY-MM-DD)."""
    conn = get_db_connection()
    status_id = body.status_id if body.status_id is not None else 1
    is_public = body.is_public if body.is_public is not None else True
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                if body.deadline:
                    cur.execute(
                        "INSERT INTO dreams (user_id, dream, status_id, category_id, date, deadline, price, is_public) VALUES (%s, %s, %s, %s, CURRENT_DATE, %s, %s, %s) RETURNING id, dream, deadline",
                        (body.user_id, body.dream.strip(), status_id, body.category_id, body.deadline, body.price, is_public),
                    )
                else:
                    cur.execute(
                        "INSERT INTO dreams (user_id, dream, status_id, category_id, date, price, is_public) VALUES (%s, %s, %s, %s, CURRENT_DATE, %s, %s) RETURNING id, dream, deadline",
                        (body.user_id, body.dream.strip(), status_id, body.category_id, body.price, is_public),
                    )
            except psycopg2.ProgrammingError:
                conn.rollback()
                code = _STATUS_ID_TO_CODE.get(status_id, "planned")
                try:
                    if body.deadline:
                        cur.execute(
                            "INSERT INTO dreams (user_id, dream, status, date, deadline) VALUES (%s, %s, %s, CURRENT_DATE, %s) RETURNING id, dream, deadline",
                            (body.user_id, body.dream.strip(), code, body.deadline),
                        )
                    else:
                        cur.execute(
                            "INSERT INTO dreams (user_id, dream, status, date) VALUES (%s, %s, %s, CURRENT_DATE) RETURNING id, dream",
                            (body.user_id, body.dream.strip(), code),
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
            return {"id": row["id"], "dream": row.get("dream") or body.dream, "status_id": status_id, "deadline": deadline}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# Маппинг status_id -> code для старой схемы (колонка status VARCHAR)
_STATUS_ID_TO_CODE = {1: "planned", 2: "in_progress", 3: "done"}

@app.patch("/dreams/{dream_id}")
def update_dream(dream_id: int, body: DreamUpdate, user_id: int):
    """Обновить мечту (текст, статус, дедлайн). Только если мечта принадлежит user_id."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM dreams WHERE id = %s AND user_id = %s", (dream_id, user_id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Мечта не найдена или не ваша")
            old_status_id = None
            try:
                cur.execute("SELECT status_id FROM dreams WHERE id = %s", (dream_id,))
                r = cur.fetchone()
                if r:
                    old_status_id = r.get("status_id")
            except psycopg2.ProgrammingError:
                pass
            # Используем только переданные клиентом поля (чтобы category_id=null сохранялось)
            payload = body.model_dump(exclude_unset=True)
            updates, vals = [], []
            if "dream" in payload and payload["dream"] is not None:
                updates.append("dream = %s")
                vals.append(payload["dream"].strip())
            if "status_id" in payload:
                updates.append("status_id = %s")
                vals.append(payload["status_id"])
            if "category_id" in payload:
                updates.append("category_id = %s")
                vals.append(payload["category_id"])
            if "deadline" in payload:
                updates.append("deadline = %s")
                vals.append(payload["deadline"] if payload["deadline"] else None)
            if "price" in payload:
                updates.append("price = %s")
                vals.append(payload["price"])
            if "is_public" in payload:
                updates.append("is_public = %s")
                vals.append(payload["is_public"])
            if not updates:
                return {"ok": True}
            vals.append(dream_id)
            try:
                cur.execute(
                    "UPDATE dreams SET " + ", ".join(updates) + " WHERE id = %s",
                    vals,
                )
            except psycopg2.ProgrammingError:
                conn.rollback()
                # Повтор без category_id (если колонки нет в старой схеме)
                updates_old, vals_old = [], []
                if "dream" in payload and payload["dream"] is not None:
                    updates_old.append("dream = %s")
                    vals_old.append(payload["dream"].strip())
                if "status_id" in payload:
                    updates_old.append("status_id = %s")
                    vals_old.append(payload["status_id"])
                if "deadline" in payload:
                    updates_old.append("deadline = %s")
                    vals_old.append(payload["deadline"] if payload["deadline"] else None)
                if "price" in payload:
                    updates_old.append("price = %s")
                    vals_old.append(payload["price"])
                if "is_public" in payload:
                    updates_old.append("is_public = %s")
                    vals_old.append(payload["is_public"])
                if updates_old:
                    vals_old.append(dream_id)
                    try:
                        cur.execute(
                            "UPDATE dreams SET " + ", ".join(updates_old) + " WHERE id = %s",
                            vals_old,
                        )
                    except psycopg2.ProgrammingError:
                        conn.rollback()
                        updates_old2, vals_old2 = [], []
                        if "dream" in payload and payload["dream"] is not None:
                            updates_old2.append("dream = %s")
                            vals_old2.append(payload["dream"].strip())
                        if "deadline" in payload:
                            updates_old2.append("deadline = %s")
                            vals_old2.append(payload["deadline"] if payload["deadline"] else None)
                        if "price" in payload:
                            updates_old2.append("price = %s")
                            vals_old2.append(payload["price"])
                        if "is_public" in payload:
                            updates_old2.append("is_public = %s")
                            vals_old2.append(payload["is_public"])
                        if updates_old2:
                            vals_old2.append(dream_id)
                            cur.execute(
                                "UPDATE dreams SET " + ", ".join(updates_old2) + " WHERE id = %s",
                                vals_old2,
                            )
            conn.commit()
            # При переходе мечты в статус «выполнено» (3) — одна запись в dreams_log (единый источник для лендинга и кабинета)
            if payload.get("status_id") == 3 and old_status_id != 3:
                try:
                    cur.execute(
                        "INSERT INTO dreams_log (dream_id, date, fulfilled_by_user_id) VALUES (%s, CURRENT_DATE, %s)",
                        (dream_id, user_id),
                    )
                    conn.commit()
                except psycopg2.ProgrammingError:
                    conn.rollback()
            return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.delete("/dreams/{dream_id}")
def delete_dream(dream_id: int, user_id: int, viewer_id: Optional[int] = None):
    """Удалить мечту. Разрешено владельцу или бадди с buddy_trust=true (viewer_id=кто удаляет)."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _resolve_editor_and_check_dream(cur, dream_id, user_id, viewer_id)
            cur.execute("DELETE FROM dreams_steps WHERE dream_id = %s", (dream_id,))
            cur.execute("DELETE FROM dreams WHERE id = %s", (dream_id,))
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
def create_step(dream_id: int, body: StepCreate, user_id: int, viewer_id: Optional[int] = None):
    """Добавить шаг к мечте. Разрешено владельцу или бадди с buddy_trust=true."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _resolve_editor_and_check_dream(cur, dream_id, user_id, viewer_id)
            cur.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM dreams_steps WHERE dream_id = %s", (dream_id,))
            next_order = cur.fetchone()["next_order"]
            deadline = body.deadline if body.deadline else None
            try:
                cur.execute(
                    "INSERT INTO dreams_steps (dream_id, title, completed, sort_order, deadline) VALUES (%s, %s, false, %s, %s) RETURNING id, title, completed, deadline",
                    (dream_id, body.title.strip(), next_order, deadline),
                )
            except psycopg2.ProgrammingError:
                cur.connection.rollback()
                cur.execute(
                    "INSERT INTO dreams_steps (dream_id, title, completed, sort_order) VALUES (%s, %s, false, %s) RETURNING id, title, completed",
                    (dream_id, body.title.strip(), next_order),
                )
            row = cur.fetchone()
            conn.commit()
            dl = row.get("deadline")
            return {
                "id": row["id"],
                "title": row["title"],
                "completed": bool(row["completed"]),
                "deadline": str(dl) if dl else None,
            }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.patch("/dreams/{dream_id}/steps/{step_id}")
def update_step(dream_id: int, step_id: int, body: StepUpdate, user_id: int, viewer_id: Optional[int] = None):
    """Обновить шаг. Разрешено владельцу мечты или бадди с buddy_trust=true."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _resolve_editor_and_check_dream(cur, dream_id, user_id, viewer_id)
            updates, vals = [], []
            if body.title is not None:
                updates.append("title = %s")
                vals.append(body.title.strip())
            if body.completed is not None:
                updates.append("completed = %s")
                vals.append(body.completed)
            if body.deadline is not None:
                updates.append("deadline = %s")
                vals.append(body.deadline if body.deadline else None)
            if body.deleted is not None:
                updates.append("deleted = %s")
                vals.append(body.deleted)
            if not updates:
                return {"ok": True}
            vals.append(step_id)
            vals.append(dream_id)
            try:
                cur.execute(
                    "UPDATE dreams_steps SET " + ", ".join(updates) + " WHERE id = %s AND dream_id = %s",
                    vals,
                )
            except psycopg2.ProgrammingError:
                cur.connection.rollback()
                updates_old, vals_old = [], []
                if body.title is not None:
                    updates_old.append("title = %s")
                    vals_old.append(body.title.strip())
                if body.completed is not None:
                    updates_old.append("completed = %s")
                    vals_old.append(body.completed)
                if body.deleted is not None:
                    updates_old.append("deleted = %s")
                    vals_old.append(body.deleted)
                if updates_old:
                    vals_old.extend([step_id, dream_id])
                    cur.execute(
                        "UPDATE dreams_steps SET " + ", ".join(updates_old) + " WHERE id = %s AND dream_id = %s",
                        vals_old,
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