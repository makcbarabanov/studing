import os
import time
import calendar
from datetime import datetime
from pathlib import Path
import psycopg2
from psycopg2 import OperationalError
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json
from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv
from passlib.hash import bcrypt

# bcrypt принимает пароль не длиннее 72 байт; длинные обрезаем, чтобы не было 500 при входе/регистрации
def _bcrypt_password(password: str) -> str:
    if not password:
        return password
    b = password.encode("utf-8")
    if len(b) <= 72:
        return password
    return b[:72].decode("utf-8", errors="replace")

# 1. Загружаем секреты из файла .env
load_dotenv()

# 2. Создаем Диспетчера
app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent

@app.get("/landing", include_in_schema=False)
def landing_root_redirect():
    """Без слэша → /landing/ (index.html через StaticFiles)."""
    return RedirectResponse(url="/landing/", status_code=307)

# Каталоги: медиа (аватары) и статика (картинки для фона и т.п.)
MEDIA_DIR = BASE_DIR / "media"
AVATARS_DIR = MEDIA_DIR / "avatars"
AVATARS_DIR.mkdir(parents=True, exist_ok=True)
EXAMPLES_DIR = BASE_DIR / "examples"
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")
if EXAMPLES_DIR.is_dir():
    app.mount("/examples", StaticFiles(directory=str(EXAMPLES_DIR)), name="examples")
LANDING_DIR = BASE_DIR / "landing"
if LANDING_DIR.is_dir():
    app.mount("/landing", StaticFiles(directory=str(LANDING_DIR), html=True), name="landing")

# --- БЛОК БЕЗОПАСНОСТИ (CORS) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Разрешить всем
    allow_methods=["*"], # Разрешить любые методы
    allow_headers=["*"], # Разрешить любые заголовки
)
# -------------------------------

# Пул соединений с БД (Connection Pool) — переиспользуем соединения вместо создания нового на каждый запрос
db_pool = None

def _db_conn_kwargs():
    """Параметры подключения к БД (host, user, password, ...)."""
    conn_kw = dict(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
        cursor_factory=RealDictCursor,
        connect_timeout=15,
        keepalives=1,
        keepalives_idle=30,
    )
    if os.getenv("DB_PORT"):
        conn_kw["port"] = int(os.getenv("DB_PORT"))
    sslmode = (os.getenv("DB_SSLMODE") or "").strip()
    if sslmode:
        conn_kw["sslmode"] = sslmode
    return conn_kw

def _connect_with_retry(max_attempts=3):
    """Подключение к БД с повтором при SSL/сетевых ошибках."""
    for attempt in range(max_attempts):
        try:
            return psycopg2.connect(**_db_conn_kwargs())
        except OperationalError as e:
            if attempt < max_attempts - 1 and ("SSL" in str(e) or "closed" in str(e).lower()):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    return None

@app.on_event("startup")
def startup_event():
    global db_pool
    if not os.getenv("DB_HOST"):
        return  # Локальный запуск без БД (например, только статика)
    for attempt in range(3):
        try:
            conn_kw = _db_conn_kwargs()
            db_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=20,
                **conn_kw,
            )
            return
        except OperationalError as e:
            if attempt < 2 and ("SSL" in str(e) or "closed" in str(e).lower()):
                time.sleep(1.5 * (attempt + 1))
                continue
            print("⚠ Пул БД не создан:", e)
            break
        except Exception as e:
            print("⚠ Пул БД не создан:", e)
            break

@app.on_event("shutdown")
def shutdown_event():
    global db_pool
    if db_pool:
        try:
            db_pool.closeall()
        except Exception:
            pass
        db_pool = None

def _return_conn(conn, discard=False):
    """Вернуть соединение в пул или закрыть. discard=True — отбросить сломанное (SSL closed и т.п.), не возвращать в пул."""
    if conn is None:
        return
    try:
        if db_pool is not None:
            db_pool.putconn(conn, close=discard)
        else:
            conn.close()
    except Exception:
        pass

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
    telegram: Optional[str] = None
    vk: Optional[str] = None

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
    is_public: Optional[bool] = False  # по умолчанию закрыто от витрины

class DreamUpdate(BaseModel):
    dream: Optional[str] = None
    status_id: Optional[int] = None
    category_id: Optional[int] = None
    deadline: Optional[str] = None  # YYYY-MM-DD or null to clear
    price: Optional[float] = None  # рубли
    is_public: Optional[bool] = None
    rule_code: Optional[str] = None   # например 'books_reading'
    settings: Optional[dict] = None  # например {"minutes_per_day": 15}

class StepCreate(BaseModel):
    title: str
    deadline: Optional[str] = None  # YYYY-MM-DD

class FinanceStepsCreate(BaseModel):
    """Тело запроса для создания шагов финцели (анкета «Добавить шаги»)."""
    target_amount: float  # целевая сумма в рублях
    end_date: str  # YYYY-MM-DD — дата окончания периода (определяет год и последний месяц)
    due_day: int = 31  # число каждого месяца для дедлайна шага (1–31)
    distribution: str = "equal"  # equal | custom
    monthly_amounts: Optional[List[float]] = None  # при custom: явный список из 12 сумм по месяцам
    formula: Optional[dict] = None  # при custom: { "first_month_zero": true, "second_month_amount": float, "multiplier": float }

class StepUpdate(BaseModel):
    title: Optional[str] = None
    completed: Optional[bool] = None
    deadline: Optional[str] = None  # YYYY-MM-DD
    deleted: Optional[bool] = None  # мягкое удаление / восстановление
    fact_amount: Optional[float] = None  # для шагов финцели — фактический взнос за период

class BuddyRequestCreate(BaseModel):
    to_user_id: int

class BuddyRequestUpdate(BaseModel):
    status: str  # accepted | declined

class DreamBookCreate(BaseModel):
    title: str
    author: Optional[str] = None
    status: Optional[str] = "planned"  # planned | reading | listening | finished
    started_at: Optional[str] = None   # YYYY-MM-DD
    deadline: Optional[str] = None
    finished_at: Optional[str] = None

class DreamBookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    status: Optional[str] = None
    started_at: Optional[str] = None
    deadline: Optional[str] = None
    finished_at: Optional[str] = None

class DreamBookLogCreate(BaseModel):
    date: str  # YYYY-MM-DD
    minutes_spent: Optional[int] = None
    pages_read: Optional[int] = None

class RoadmapItemCreate(BaseModel):
    text: str
    section: Optional[str] = ""
    initiator: Optional[str] = ""

class RoadmapItemUpdate(BaseModel):
    status: Optional[str] = None  # plan | in_progress | done
    text: Optional[str] = None
    section: Optional[str] = None
    initiator: Optional[str] = None

def _load_steps(cur, dream_ids):
    """Загружает шаги по списку dream_id. Возвращает dict dream_id -> list of {id, title, completed, deadline, deleted, plan_amount, fact_amount}."""
    out = {}
    if not dream_ids:
        return out
    try:
        cur.execute(
            "SELECT dream_id, id, title, completed, sort_order, deadline, deleted, plan_amount, fact_amount FROM dreams_steps WHERE dream_id = ANY(%s) ORDER BY dream_id, sort_order, id",
            (dream_ids,),
        )
        for s in cur.fetchall():
            did = s["dream_id"]
            if did not in out:
                out[did] = []
            dl = s.get("deadline")
            plan = s.get("plan_amount")
            fact = s.get("fact_amount")
            out[did].append({
                "id": s["id"],
                "title": s["title"],
                "completed": bool(s["completed"]),
                "deadline": str(dl) if dl else None,
                "deleted": bool(s.get("deleted", False)),
                "plan_amount": float(plan) if plan is not None else None,
                "fact_amount": float(fact) if fact is not None else None,
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
                    "plan_amount": None, "fact_amount": None,
                })
        except psycopg2.ProgrammingError:
            pass
    return out

def _load_books(cur, dream_ids):
    """Загружает книги по списку dream_id (для мечт с rule_code=books_reading). Возвращает dict dream_id -> list of book dicts."""
    out = {}
    if not dream_ids:
        return out
    try:
        cur.execute(
            """SELECT id, dream_id, title, author, status, started_at, deadline, finished_at
               FROM dream_books WHERE dream_id = ANY(%s) ORDER BY dream_id, COALESCE(started_at, deadline, '9999-12-31'), id""",
            (dream_ids,),
        )
        for r in cur.fetchall():
            did = r["dream_id"]
            if did not in out:
                out[did] = []
            out[did].append({
                "id": r["id"],
                "title": r["title"] or "",
                "author": r["author"],
                "status": r["status"] or "planned",
                "started_at": str(r["started_at"]) if r.get("started_at") else None,
                "deadline": str(r["deadline"]) if r.get("deadline") else None,
                "finished_at": str(r["finished_at"]) if r.get("finished_at") else None,
            })
    except psycopg2.ProgrammingError:
        pass
    return out

def _schedule_items_standard(cur, user_id: int, date_from: str, date_to: str):
    """Пункты расписания из обычных шагов (dreams_steps): дедлайн в диапазоне [date_from, date_to]."""
    items = []
    try:
        cur.execute(
            """SELECT d.id AS dream_id, s.id AS source_id, s.title, s.deadline AS date, s.completed
               FROM dreams d
               JOIN dreams_steps s ON s.dream_id = d.id
               WHERE d.user_id = %s AND s.deadline IS NOT NULL
                 AND s.deadline >= %s AND s.deadline <= %s
                 AND COALESCE(s.deleted, false) = false
               ORDER BY s.deadline, s.id""",
            (user_id, date_from, date_to),
        )
        for r in cur.fetchall():
            items.append({
                "dream_id": r["dream_id"],
                "source_type": "step",
                "source_id": r["source_id"],
                "title": r["title"] or "",
                "date": str(r["date"]),
                "completed": bool(r["completed"]),
            })
    except psycopg2.ProgrammingError:
        pass
    return items

def _schedule_items_books(cur, user_id: int, date_from: str, date_to: str):
    """Виртуальные пункты расписания из активных книг (reading/listening): по одной строке на день в [started_at, deadline]."""
    from datetime import datetime, timedelta
    items = []
    try:
        cur.execute(
            """SELECT d.id AS dream_id, d.settings,
               b.id AS book_id, b.title AS book_title, b.status AS book_status, b.started_at, b.deadline
               FROM dreams d
               JOIN dream_books b ON b.dream_id = d.id
               WHERE d.user_id = %s AND d.rule_code = 'books_reading'
                 AND b.status IN ('reading', 'listening')
                 AND b.started_at IS NOT NULL AND b.deadline IS NOT NULL
                 AND b.deadline >= %s AND b.started_at <= %s""",
            (user_id, date_from, date_to),
        )
        rows = cur.fetchall()
        if not rows:
            return items
        cur.execute(
            """SELECT book_id, date FROM dream_books_log
               WHERE book_id = ANY(%s) AND date >= %s AND date <= %s""",
            (list({r["book_id"] for r in rows}), date_from, date_to),
        )
        log_done = {(r["book_id"], str(r["date"])) for r in cur.fetchall()}
    except psycopg2.ProgrammingError:
        return items
    d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
    d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
    for r in rows:
        dream_id = r["dream_id"]
        book_id = r["book_id"]
        book_title = r["book_title"] or "Книга"
        status = r["book_status"] or "reading"
        started = r["started_at"]
        deadline = r["deadline"]
        if isinstance(started, str):
            started = datetime.strptime(started[:10], "%Y-%m-%d").date()
        if isinstance(deadline, str):
            deadline = datetime.strptime(deadline[:10], "%Y-%m-%d").date()
        settings = r.get("settings") or {}
        if isinstance(settings, str):
            try:
                import json
                settings = json.loads(settings) if settings else {}
            except Exception:
                settings = {}
        mins = settings.get("minutes_per_day", 15)
        prefix = "Слушать" if status == "listening" else "Читать"
        title = f"{prefix} «{book_title}» ({mins} мин)"
        day_start = max(started, d_from)
        day_end = min(deadline, d_to)
        d = day_start
        while d <= day_end:
            date_str = d.strftime("%Y-%m-%d")
            completed = (book_id, date_str) in log_done
            items.append({
                "dream_id": dream_id,
                "source_type": "book",
                "source_id": book_id,
                "title": title,
                "date": date_str,
                "completed": completed,
            })
            d += timedelta(days=1)
    return items

def get_db_connection():
    """Берёт соединение из пула. Валидирует его (SELECT 1); при SSL/connection closed — отбрасывает и повторяет до 3 раз."""
    if db_pool is None:
        return _connect_with_retry()
    for attempt in range(3):
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
        except OperationalError as e:
            try:
                db_pool.putconn(conn, close=True)
            except Exception:
                pass
            if attempt < 2 and ("SSL" in str(e) or "closed" in str(e).lower() or "connection" in str(e).lower()):
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    return None

@app.get("/", response_class=FileResponse)
def root_page():
    """Корень — личный кабинет"""
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/dreams.html", response_class=FileResponse)
def dreams_page():
    """Публичная витрина мечт — без авторизации. Захотел помочь — регистрация в ЛК."""
    return FileResponse(Path(__file__).parent / "dreams.html")

@app.get("/admin", response_class=FileResponse)
def admin_page():
    """Админка — веб-интерфейс для управления пользователями"""
    return FileResponse(Path(__file__).parent / "admin.html")

@app.get("/index.html", response_class=FileResponse)
def index_page():
    """Личный кабинет (вход и регистрация)"""
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/index2.html", response_class=FileResponse)
def index2_page():
    """Вариант интерфейса (архив): заголовок «мечты | шаги», под ним контекстный заголовок (Мои мечты / Витрина / Уведомления)."""
    return FileResponse(Path(__file__).parent / "archive" / "index2.html")

@app.get("/roadmap.html", response_class=FileResponse)
def roadmap_page():
    """Roadmap и обратная связь от тестировщиков."""
    return FileResponse(Path(__file__).parent / "roadmap.html")

# --- Эндпоинт 1: АВТОРИЗАЦИЯ ---
@app.post("/login")
def login_user(user_login: UserLogin):
    """
    Эндпоинт для авторизации.
    Ищет по телефону, проверяет пароль через bcrypt, отдаёт full_name (name + surname).
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            phone_alt = ("+7" + user_login.phone[1:]) if user_login.phone.startswith("8") and len(user_login.phone) >= 11 else user_login.phone
            try:
                cur.execute("""
                    SELECT id, name, surname, city, phone, password_hash, avatar_path, buddy_id, buddy_trust, telegram, vk
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
                if not bcrypt.verify(_bcrypt_password(user_login.password), stored):
                    raise HTTPException(status_code=400, detail="Неверный пароль")
            else:
                if stored != user_login.password:
                    raise HTTPException(status_code=400, detail="Неверный пароль")

            full_name = f"{user_data['name'] or ''} {user_data['surname'] or ''}".strip() or "Пользователь"
            avatar_path = user_data.get("avatar_path")
            buddy_id = user_data.get("buddy_id")
            buddy_trust = bool(user_data.get("buddy_trust"))
            buddy_name = None
            buddy_avatar_path = None
            if buddy_id:
                cur.execute("SELECT name, surname, avatar_path FROM users WHERE id = %s", (buddy_id,))
                buddy_row = cur.fetchone()
                if buddy_row:
                    buddy_name = f"{buddy_row.get('name') or ''} {buddy_row.get('surname') or ''}".strip() or None
                    buddy_avatar_path = buddy_row.get("avatar_path")
            result = {
                "id": user_data["id"],
                "full_name": full_name,
                "city": user_data["city"],
                "phone": user_data["phone"],
                "avatar_path": avatar_path,
                "buddy_id": buddy_id,
                "buddy_trust": buddy_trust,
                "buddy_name": buddy_name,
                "buddy_avatar_path": buddy_avatar_path,
                "dream": "Мечта загружается..."
            }
            if "telegram" in user_data:
                result["telegram"] = user_data.get("telegram")
            if "vk" in user_data:
                result["vk"] = user_data.get("vk")
            return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")
    finally:
        _return_conn(conn)


@app.get("/landing_stats")
def landing_stats():
    """Публичная статистика для лендинга: сколько мечт исполнено (из dreams_log), сколько участников (users)."""
    conn = None
    fulfilled_dreams = 0
    users_count = 0
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute("SELECT COUNT(DISTINCT dream_id) AS n FROM dreams_log")
                row = cur.fetchone()
                if row:
                    fulfilled_dreams = row.get("n") or 0
            except (psycopg2.ProgrammingError, psycopg2.OperationalError):
                pass
            try:
                cur.execute("SELECT COUNT(*) AS n FROM users")
                row = cur.fetchone()
                if row:
                    users_count = row.get("n") or 0
            except (psycopg2.ProgrammingError, psycopg2.OperationalError):
                pass
        return {"fulfilled_dreams": fulfilled_dreams, "users_count": users_count}
    except Exception as e:
        return {"fulfilled_dreams": 0, "users_count": 0}
    finally:
        _return_conn(conn)


# --- Эндпоинт: ЗАГРУЗКА АВАТАРА ---
AVATAR_EXTENSIONS = frozenset((".jpg", ".jpeg", ".png", ".webp", ".gif"))
AVATAR_MAX_BYTES = 2 * 1024 * 1024  # 2 МБ

@app.post("/avatar")
def upload_avatar(
    user_id: int,
    file: Optional[UploadFile] = File(None, alias="file"),
    avatar: Optional[UploadFile] = File(None, alias="avatar"),
):
    """Загрузить аватар пользователя. Файл: form field «file» или «avatar». Сохраняется в media/avatars/{user_id}.{ext}."""
    upload = file or avatar
    if not upload:
        raise HTTPException(status_code=400, detail="Не отправлен файл. Используйте поле «file» или «avatar» в multipart/form-data.")
    if not upload.filename or not upload.filename.strip():
        raise HTTPException(status_code=400, detail="Файл не выбран")
    ext = Path(upload.filename).suffix.lower()
    if ext not in AVATAR_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Разрешены только jpg, png, webp, gif. Получено расширение: {ext!r}.",
        )
    content = upload.file.read()
    if len(content) > AVATAR_MAX_BYTES:
        size_mb = round(len(content) / (1024 * 1024), 2)
        raise HTTPException(
            status_code=400,
            detail=f"Файл не более 2 МБ. Получено: {size_mb} МБ.",
        )
    # Сохраняем как avatars/{user_id}.{ext}
    safe_ext = ".jpg" if ext == ".jpeg" else ext
    filename = f"{user_id}{safe_ext}"
    filepath = AVATARS_DIR / filename
    try:
        filepath.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить файл: {str(e)}")
    avatar_path = f"avatars/{filename}"
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("UPDATE users SET avatar_path = %s WHERE id = %s", (avatar_path, user_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка БД: {str(e)}")
    finally:
        _return_conn(conn)
    return {"ok": True, "avatar_path": avatar_path}


@app.get("/users/me")
def users_me(user_id: int):
    """Актуальные данные текущего пользователя: id, full_name, avatar_path, buddy_id, buddy_name, buddy_avatar_path, telegram, vk. Для сессии и для формы редактирования профиля."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute(
                    """SELECT id, name, surname, city, phone, avatar_path, buddy_id, buddy_trust, telegram, vk
                       FROM users WHERE id = %s""",
                    (user_id,),
                )
            except psycopg2.ProgrammingError:
                conn.rollback()
                cur.execute(
                    """SELECT id, name, surname, city, phone, avatar_path, buddy_id, buddy_trust
                       FROM users WHERE id = %s""",
                    (user_id,),
                )
            user_data = cur.fetchone()
            if user_data is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            full_name = f"{user_data.get('name') or ''} {user_data.get('surname') or ''}".strip() or "Пользователь"
            buddy_id = user_data.get("buddy_id")
            buddy_name = None
            buddy_avatar_path = None
            if buddy_id:
                cur.execute("SELECT name, surname, avatar_path FROM users WHERE id = %s", (buddy_id,))
                buddy_row = cur.fetchone()
                if buddy_row:
                    buddy_name = f"{buddy_row.get('name') or ''} {buddy_row.get('surname') or ''}".strip() or None
                    buddy_avatar_path = buddy_row.get("avatar_path")
            out = {
                "id": user_data["id"],
                "full_name": full_name,
                "city": user_data.get("city"),
                "phone": user_data.get("phone"),
                "avatar_path": user_data.get("avatar_path"),
                "buddy_id": buddy_id,
                "buddy_trust": bool(user_data.get("buddy_trust")),
                "buddy_name": buddy_name,
                "buddy_avatar_path": buddy_avatar_path,
            }
            if "telegram" in user_data:
                out["telegram"] = user_data.get("telegram") or ""
            if "vk" in user_data:
                out["vk"] = user_data.get("vk") or ""
            return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


class ProfileUpdateBody(BaseModel):
    user_id: int
    current_password: Optional[str] = None
    new_password: Optional[str] = None
    telegram: Optional[str] = None
    vk: Optional[str] = None
    phone: Optional[str] = None


@app.patch("/users/me")
def update_profile(body: ProfileUpdateBody):
    """Обновить профиль: пароль (нужен current_password), telegram, vk, phone. Только свои данные (user_id = текущий)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, password_hash FROM users WHERE id = %s",
                (body.user_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            updates = []
            params = []
            if body.new_password is not None and body.new_password != "":
                if not body.current_password:
                    raise HTTPException(status_code=400, detail="Для смены пароля укажите текущий пароль")
                stored = (row.get("password_hash") or "") or ""
                if stored.startswith("$2b$") or stored.startswith("$2a$"):
                    if not bcrypt.verify(_bcrypt_password(body.current_password), stored):
                        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
                else:
                    if stored != body.current_password:
                        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
                if len(body.new_password) < 6:
                    raise HTTPException(status_code=400, detail="Новый пароль не менее 6 символов")
                updates.append("password_hash = %s")
                params.append(bcrypt.hash(_bcrypt_password(body.new_password)))
            if body.telegram is not None:
                updates.append("telegram = %s")
                params.append((body.telegram or "").strip() or None)
            if body.vk is not None:
                updates.append("vk = %s")
                params.append((body.vk or "").strip() or None)
            if body.phone is not None:
                updates.append("phone = %s")
                params.append((body.phone or "").strip() or None)
            if not updates:
                return {"ok": True}
            params.append(body.user_id)
            cur.execute(
                "UPDATE users SET " + ", ".join(updates) + " WHERE id = %s",
                params,
            )
        conn.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


# --- Коды стран, которые уже есть в БД (для выпадающего списка: показать вверху и жирным) ---
PHONE_PREFIXES_ORDER = [
    "+7-7", "+971", "+998", "+995", "+86", "+81", "+82", "+91", "+61", "+64",
    "+55", "+52", "+90", "+380", "+375", "+49", "+44", "+43", "+41", "+48",
    "+420", "+421", "+371", "+370", "+372", "+33", "+39", "+34", "+1", "+7",
]


@app.get("/users/phone-prefixes")
def users_phone_prefixes():
    """Список кодов стран (префиксов телефонов), которые встречаются в users.phone. Для сортировки выпадающего списка стран."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT phone FROM users WHERE phone IS NOT NULL AND phone != ''")
            rows = cur.fetchall()
        phones = [r[0] for r in rows]
        seen = set()
        for p in phones:
            if not p or not isinstance(p, str):
                continue
            p = p.strip()
            for code in PHONE_PREFIXES_ORDER:
                if p.startswith(code):
                    seen.add(code)
                    break
        return {"prefixes": list(seen)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


# --- Список пользователей для модалки «Добавить бадди» ---
@app.get("/users/list")
def users_list(exclude_user_id: Optional[int] = None):
    """Список пользователей без бадди: id, name, surname, avatar_path. exclude_user_id — не включать этого пользователя."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Только пользователи, у которых ещё нет бадди (buddy_id IS NULL)
            sql_base = "SELECT id, name, surname FROM users WHERE buddy_id IS NULL"
            if exclude_user_id is not None:
                cur.execute(sql_base + " AND id != %s ORDER BY surname, name", (exclude_user_id,))
            else:
                cur.execute(sql_base + " ORDER BY surname, name")
            rows = cur.fetchall()
            out = [{"id": r["id"], "name": (r.get("name") or "").strip(), "surname": (r.get("surname") or "").strip(), "avatar_path": None, "gender": r.get("gender")} for r in rows]
            try:
                if exclude_user_id is not None:
                    cur.execute("SELECT id, name, surname, gender FROM users WHERE id != %s AND buddy_id IS NULL ORDER BY surname, name", (exclude_user_id,))
                else:
                    cur.execute("SELECT id, name, surname, gender FROM users WHERE buddy_id IS NULL ORDER BY surname, name")
                rows = cur.fetchall()
                out = [{"id": r["id"], "name": (r.get("name") or "").strip(), "surname": (r.get("surname") or "").strip(), "avatar_path": None, "gender": r.get("gender")} for r in rows]
            except psycopg2.ProgrammingError:
                pass
            try:
                cur.execute("SELECT id, avatar_path FROM users WHERE avatar_path IS NOT NULL")
                for row in cur.fetchall():
                    for i in out:
                        if i["id"] == row["id"]:
                            i["avatar_path"] = row.get("avatar_path")
                            break
            except psycopg2.ProgrammingError:
                pass
            return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


# --- Запросы в бадди (buddy_requests) ---
def _ensure_buddy_requests_table(cur):
    """Создать таблицу buddy_requests, если её нет (для совместимости без ручного запуска миграции)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS buddy_requests (
            id SERIAL PRIMARY KEY,
            from_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            to_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'declined', 'cancelled')),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_buddy_requests_to_user ON buddy_requests(to_user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_buddy_requests_from_user ON buddy_requests(from_user_id)")
    except psycopg2.ProgrammingError:
        pass


@app.get("/buddy_requests")
def list_buddy_requests(user_id: int):
    """Список запросов для текущего пользователя: входящие (pending) и исходящие (pending)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_buddy_requests_table(cur)
            conn.commit()
            cur.execute("""
                SELECT br.id, br.from_user_id, br.to_user_id, br.status, br.created_at,
                       u.name AS from_name, u.surname AS from_surname
                FROM buddy_requests br
                JOIN users u ON u.id = br.from_user_id
                WHERE br.to_user_id = %s AND br.status = 'pending'
                ORDER BY br.created_at DESC
            """, (user_id,))
            incoming = [dict(r) for r in cur.fetchall()]
            cur.execute("""
                SELECT br.id, br.from_user_id, br.to_user_id, br.status, br.created_at,
                       u.name AS to_name, u.surname AS to_surname
                FROM buddy_requests br
                JOIN users u ON u.id = br.to_user_id
                WHERE br.from_user_id = %s AND br.status = 'pending'
                ORDER BY br.created_at DESC
            """, (user_id,))
            outgoing = [dict(r) for r in cur.fetchall()]
            return {"incoming": incoming, "outgoing": outgoing}
    finally:
        _return_conn(conn)


@app.post("/buddy_requests")
def create_buddy_request(body: BuddyRequestCreate, user_id: int):
    """Отправить запрос в бадди. user_id — отправитель (from_user_id), body.to_user_id — кому."""
    if body.to_user_id == user_id:
        raise HTTPException(status_code=400, detail="Нельзя отправить запрос себе")
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_buddy_requests_table(cur)
            cur.execute("SELECT id, buddy_id FROM users WHERE id IN (%s, %s)", (user_id, body.to_user_id))
            rows = {r["id"]: r for r in cur.fetchall()}
            if body.to_user_id not in rows:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            if rows.get(body.to_user_id, {}).get("buddy_id"):
                raise HTTPException(status_code=400, detail="У этого пользователя уже есть бадди")
            if rows.get(user_id, {}).get("buddy_id"):
                raise HTTPException(status_code=400, detail="У вас уже есть бадди")
            cur.execute(
                "SELECT id FROM buddy_requests WHERE from_user_id = %s AND to_user_id = %s AND status = 'pending'",
                (user_id, body.to_user_id),
            )
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Запрос уже отправлен")
            cur.execute(
                "INSERT INTO buddy_requests (from_user_id, to_user_id, status) VALUES (%s, %s, 'pending') RETURNING id, from_user_id, to_user_id, status, created_at",
                (user_id, body.to_user_id),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.patch("/buddy_requests/{request_id}")
def update_buddy_request(request_id: int, body: BuddyRequestUpdate, user_id: int):
    """Принять или отклонить входящий запрос. Только тот, кому пришёл запрос (to_user_id), может менять статус."""
    if body.status not in ("accepted", "declined"):
        raise HTTPException(status_code=400, detail="status должен быть accepted или declined")
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, from_user_id, to_user_id, status FROM buddy_requests WHERE id = %s", (request_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Запрос не найден")
            if row["to_user_id"] != user_id:
                raise HTTPException(status_code=403, detail="Только получатель может принять или отклонить запрос")
            if row["status"] != "pending":
                raise HTTPException(status_code=400, detail="Запрос уже обработан")
            from_id = row["from_user_id"]
            to_id = row["to_user_id"]
            cur.execute("UPDATE buddy_requests SET status = %s WHERE id = %s", (body.status, request_id))
            if body.status == "accepted":
                cur.execute("UPDATE users SET buddy_id = %s WHERE id = %s", (to_id, from_id))
                cur.execute("UPDATE users SET buddy_id = %s WHERE id = %s", (from_id, to_id))
                cur.execute("SELECT name, surname, avatar_path FROM users WHERE id = %s", (from_id,))
                buddy_row = cur.fetchone()
                buddy_name = ((buddy_row.get("name") or "") + " " + (buddy_row.get("surname") or "")).strip() if buddy_row else ""
                buddy_avatar_path = buddy_row.get("avatar_path") if buddy_row else None
            else:
                buddy_name = None
                buddy_avatar_path = None
            conn.commit()
            out = {"id": request_id, "status": body.status}
            if body.status == "accepted":
                out["buddy_id"] = from_id
                out["buddy_name"] = buddy_name
                out["buddy_avatar_path"] = buddy_avatar_path
            return out
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.delete("/buddy_requests/{request_id}")
def cancel_buddy_request(request_id: int, user_id: int):
    """Отменить исходящий запрос. Только отправитель (from_user_id) может отменить."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, from_user_id, status FROM buddy_requests WHERE id = %s", (request_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Запрос не найден")
            if row["from_user_id"] != user_id:
                raise HTTPException(status_code=403, detail="Только отправитель может отменить запрос")
            if row["status"] != "pending":
                raise HTTPException(status_code=400, detail="Запрос уже обработан")
            cur.execute("UPDATE buddy_requests SET status = 'cancelled' WHERE id = %s", (request_id,))
            conn.commit()
            return {"id": request_id, "status": "cancelled"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


# --- Эндпоинт: РЕГИСТРАЦИЯ ---
@app.post("/register")
def register_user(user: UserRegister):
    """Регистрация: name, surname, phone, city; пароль хешируется bcrypt."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            phone_alt = ("+7" + user.phone[1:]) if user.phone.startswith("8") and len(user.phone) >= 11 else user.phone
            cur.execute("SELECT id FROM users WHERE phone = %s OR phone = %s", (user.phone, phone_alt))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Пользователь с таким телефоном уже зарегистрирован")
            tel = (user.telegram or "").strip() or None
            vk_val = (user.vk or "").strip() or None
            cur.execute("""
                INSERT INTO users (name, surname, phone, city, password_hash, telegram, vk)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (user.name.strip(), user.surname.strip(), user.phone, user.city.strip(), bcrypt.hash(_bcrypt_password(user.password)), tel, vk_val))
            row = cur.fetchone()
        conn.commit()
        return {"id": row["id"]}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")
    finally:
        _return_conn(conn)

# --- Справочники для мечт ---
@app.get("/dreams_statuses")
def list_dream_statuses():
    """Список статусов мечты (id, code, label_ru, icon)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, code, label_ru, icon FROM dreams_statuses ORDER BY id")
            return [dict(r) for r in cur.fetchall()]
    finally:
        _return_conn(conn)

@app.get("/dreams_categories")
@app.get("/dream_categories")  # алиас для обратной совместимости
def list_dream_categories():
    """Список категорий мечты (id, code, label_ru, icon)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, code, label_ru, icon FROM dreams_categories ORDER BY id")
            return [dict(r) for r in cur.fetchall()]
    finally:
        _return_conn(conn)

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

def _build_dream_item(row, steps_by_dream, books_by_dream=None):
    """Собирает один элемент для ответа GET /dreams из строки БД."""
    dream_id = row["id"]
    title = (row.get("dream") or "").strip()
    dream_text = row.get("dream") or ""
    dl = row.get("deadline")
    deadline = str(dl) if dl is not None else None
    steps = steps_by_dream.get(dream_id, [])
    books = (books_by_dream or {}).get(dream_id, [])
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
        "status_id": row.get("status_id"),
        "status_obj": status_obj,
        "deadline": deadline,
        "category": row.get("category_code"),
        "category_obj": category_obj,
        "price": price,
        "is_public": row.get("is_public") if row.get("is_public") is not None else True,
        "progress": 0,
        "steps": steps,
        "rule_code": row.get("rule_code"),
        "settings": row.get("settings"),
        "books": books,
    }


@app.get("/dreams/showcase/counts")
def get_dreams_showcase_counts(user_id: Optional[int] = None):
    """Счётчики витрины: new, helping, favorites, all. Для отображения при просмотре своих мечт."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM dreams WHERE COALESCE(is_public, true) = true"
            )
            count_all = cur.fetchone()["n"] or 0
            count_new = count_all
            count_helping = 0
            count_helped = 0
            count_favorites = 0
            if user_id:
                cur.execute(
                    """SELECT COUNT(*) AS n FROM dreams d
                       WHERE COALESCE(d.is_public, true) = true
                       AND NOT EXISTS (SELECT 1 FROM user_dream_views v WHERE v.user_id = %s AND v.dream_id = d.id)""",
                    (user_id,),
                )
                count_new = cur.fetchone()["n"] or 0
                cur.execute(
                    """SELECT COUNT(*) AS n FROM user_dream_help_intent h
                       JOIN dreams d ON d.id = h.dream_id AND COALESCE(d.is_public, true) = true
                       WHERE h.user_id = %s
                       AND NOT EXISTS (SELECT 1 FROM user_dream_helped hl WHERE hl.user_id = %s AND hl.dream_id = h.dream_id)""",
                    (user_id, user_id),
                )
                count_helping = cur.fetchone()["n"] or 0
                cur.execute(
                    """SELECT COUNT(*) AS n FROM user_dream_helped hl
                       JOIN dreams d ON d.id = hl.dream_id AND COALESCE(d.is_public, true) = true
                       WHERE hl.user_id = %s""",
                    (user_id,),
                )
                count_helped = cur.fetchone()["n"] or 0
                cur.execute(
                    """SELECT COUNT(*) AS n FROM user_dream_favorites f
                       JOIN dreams d ON d.id = f.dream_id AND COALESCE(d.is_public, true) = true
                       WHERE f.user_id = %s""",
                    (user_id,),
                )
                count_favorites = cur.fetchone()["n"] or 0
                count_in_progress = 0
                count_pending_completion = 0
                try:
                    cur.execute(
                        """SELECT COUNT(DISTINCT d.id) AS n FROM dreams d
                           WHERE d.user_id = %s AND EXISTS (SELECT 1 FROM user_dream_help_intent h WHERE h.dream_id = d.id)""",
                        (user_id,),
                    )
                    count_in_progress = cur.fetchone()["n"] or 0
                    cur.execute(
                        """SELECT COUNT(DISTINCT r.dream_id) AS n FROM user_dream_completion_request r
                           JOIN dreams d ON d.id = r.dream_id WHERE d.user_id = %s""",
                        (user_id,),
                    )
                    count_pending_completion = cur.fetchone()["n"] or 0
                except psycopg2.ProgrammingError:
                    pass
            else:
                count_in_progress = 0
                count_pending_completion = 0
            return {
                "new": count_new, "helping": count_helping, "helped": count_helped,
                "favorites": count_favorites, "all": count_all,
                "in_progress": count_in_progress, "pending_completion": count_pending_completion,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.get("/dreams/showcase")
def get_dreams_showcase(user_id: Optional[int] = None, showcase_filter: Optional[str] = None):
    """Витрина мечт: публичные мечты. user_id — для флагов. showcase_filter: new, helping, all, favorites, viewed, in_progress."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if showcase_filter == "in_progress" and user_id:
                rows = []
                try:
                    cur.execute("""
                        SELECT d.id, d.dream, d.deadline, d.price, d.date, d.user_id,
                               u.name AS user_name, u.surname AS user_surname
                        FROM dreams d
                        JOIN users u ON u.id = d.user_id
                        WHERE d.user_id = %s
                          AND EXISTS (SELECT 1 FROM user_dream_help_intent h WHERE h.dream_id = d.id)
                        ORDER BY d.id DESC
                    """, (user_id,))
                    rows = cur.fetchall()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    try:
                        cur.execute("""
                            SELECT d.id, d.dream, d.deadline, d.price, d.date, d.user_id
                            FROM dreams d
                            WHERE d.user_id = %s
                              AND EXISTS (SELECT 1 FROM user_dream_help_intent h WHERE h.dream_id = d.id)
                            ORDER BY d.id DESC
                        """, (user_id,))
                        rows = cur.fetchall()
                    except Exception:
                        rows = []
                completion_dreams = set()
                if rows:
                    try:
                        cur.execute(
                            "SELECT dream_id FROM user_dream_completion_request WHERE dream_id = ANY(%s)",
                            ([r["id"] for r in rows],),
                        )
                        completion_dreams = {r["dream_id"] for r in cur.fetchall()}
                    except psycopg2.ProgrammingError:
                        pass
                result = []
                for r in rows:
                    full_name = f"{r.get('user_name') or ''} {r.get('user_surname') or ''}".strip() or "Участник"
                    result.append({
                        "id": r["id"],
                        "dream": r.get("dream") or "",
                        "deadline": str(r["deadline"]) if r.get("deadline") else None,
                        "price": float(r["price"]) if r.get("price") is not None else None,
                        "date": str(r["date"]) if r.get("date") else None,
                        "user_id": r["user_id"],
                        "user_name": full_name,
                        "is_owner_view": True,
                        "has_pending_completion": r["id"] in completion_dreams,
                    })
                counts = {"new": 0, "helping": 0, "helped": 0, "favorites": 0, "all": 0, "in_progress": len(rows), "pending_completion": len(completion_dreams)}
                return {"dreams": result, "counts": counts}
            if showcase_filter == "favorites" and user_id:
                try:
                    cur.execute(
                        "SELECT dream_id FROM user_dream_favorites WHERE user_id = %s",
                        (user_id,),
                    )
                    fav_ids = [r["dream_id"] for r in cur.fetchall()]
                except Exception:
                    fav_ids = []
                if not fav_ids:
                    try:
                        cur.execute("SELECT COUNT(*) AS n FROM dreams WHERE COALESCE(is_public, true) = true")
                        count_all = cur.fetchone()["n"] or 0
                        cur.execute("SELECT COUNT(*) AS n FROM user_dream_favorites WHERE user_id = %s", (user_id,))
                        count_favorites = cur.fetchone()["n"] or 0
                        cur.execute("""SELECT COUNT(*) AS n FROM user_dream_help_intent h JOIN dreams d ON d.id = h.dream_id
                            WHERE h.user_id = %s AND COALESCE(d.is_public, true) = true
                            AND NOT EXISTS (SELECT 1 FROM user_dream_helped hl WHERE hl.user_id = %s AND hl.dream_id = h.dream_id)""", (user_id, user_id))
                        count_helping = cur.fetchone()["n"] or 0
                        cur.execute("""SELECT COUNT(*) AS n FROM user_dream_helped hl JOIN dreams d ON d.id = hl.dream_id
                            WHERE hl.user_id = %s AND COALESCE(d.is_public, true) = true""", (user_id,))
                        count_helped = cur.fetchone()["n"] or 0
                    except Exception:
                        count_all = count_favorites = count_helping = count_helped = 0
                    counts = {"new": 0, "helping": count_helping, "helped": count_helped, "favorites": count_favorites, "all": count_all}
                    return {"dreams": [], "counts": counts}
                try:
                    cur.execute("""
                        SELECT d.id, d.dream, d.deadline, d.price, d.date, d.user_id,
                               COALESCE(s.code, 'planned') AS status_code, s.label_ru AS status_label,
                               u.name AS user_name, u.surname AS user_surname, u.city AS user_city,
                               u.telegram AS user_telegram, u.vk AS user_vk, u.phone AS user_phone
                        FROM dreams d
                        JOIN users u ON u.id = d.user_id
                        LEFT JOIN dreams_statuses s ON d.status_id = s.id
                        WHERE d.id = ANY(%s) AND COALESCE(d.is_public, true) = true
                        ORDER BY d.date DESC NULLS LAST, d.id DESC
                    """, (fav_ids,))
                    rows = cur.fetchall()
                except psycopg2.ProgrammingError:
                    conn.rollback()
                    cur.execute("""
                        SELECT d.id, d.dream, d.deadline, d.price, d.date, d.user_id,
                               u.name AS user_name, u.surname AS user_surname, u.city AS user_city,
                               u.telegram AS user_telegram, u.vk AS user_vk, u.phone AS user_phone
                        FROM dreams d JOIN users u ON u.id = d.user_id
                        WHERE d.id = ANY(%s) AND COALESCE(d.is_public, true) = true
                        ORDER BY d.date DESC NULLS LAST, d.id DESC
                    """, (fav_ids,))
                    rows = cur.fetchall()
                    for r in rows:
                        r["status_code"] = "planned"
                        r["status_label"] = "Запланировано"
                dream_ids = [r["id"] for r in rows]
                viewed = set()
                helping = set()
                helped = set()
                completion_requested = set()
                try:
                    cur.execute("SELECT dream_id FROM user_dream_views WHERE user_id = %s AND dream_id = ANY(%s)", (user_id, dream_ids))
                    viewed = {r["dream_id"] for r in cur.fetchall()}
                    cur.execute("SELECT dream_id FROM user_dream_help_intent WHERE user_id = %s AND dream_id = ANY(%s)", (user_id, dream_ids))
                    helping = {r["dream_id"] for r in cur.fetchall()}
                    cur.execute("SELECT dream_id FROM user_dream_helped WHERE user_id = %s AND dream_id = ANY(%s)", (user_id, dream_ids))
                    helped = {r["dream_id"] for r in cur.fetchall()}
                    try:
                        cur.execute("SELECT dream_id FROM user_dream_completion_request WHERE helper_user_id = %s AND dream_id = ANY(%s)", (user_id, dream_ids))
                        completion_requested = {r["dream_id"] for r in cur.fetchall()}
                    except psycopg2.ProgrammingError:
                        pass
                except psycopg2.ProgrammingError:
                    pass
                favorites_count_by_dream = {}
                try:
                    cur.execute("SELECT dream_id, COUNT(*) AS c FROM user_dream_favorites WHERE dream_id = ANY(%s) GROUP BY dream_id", (dream_ids,))
                    for row in cur.fetchall():
                        favorites_count_by_dream[row["dream_id"]] = row["c"] or 0
                except psycopg2.ProgrammingError:
                    pass
                result = []
                for r in rows:
                    did = r["id"]
                    full_name = f"{r.get('user_name') or ''} {r.get('user_surname') or ''}".strip() or "Участник"
                    price_val = float(r["price"]) if r.get("price") is not None else None
                    item = {
                        "id": did,
                        "dream": r.get("dream") or "",
                        "deadline": str(r["deadline"]) if r.get("deadline") else None,
                        "price": price_val,
                        "date": str(r["date"]) if r.get("date") else None,
                        "user_id": r["user_id"],
                        "user_name": full_name,
                        "city": (r.get("user_city") or "").strip() or None,
                        "status": r.get("status_code") or "planned",
                        "status_label": r.get("status_label") or "Запланировано",
                        "telegram": (r.get("user_telegram") or "").strip() or None,
                        "vk": (r.get("user_vk") or "").strip() or None,
                        "phone": r.get("user_phone"),
                        "is_viewed": did in viewed,
                        "is_favorite": True,
                        "is_helping": did in helping and did not in helped,
                        "is_helped": did in helped,
                        "pending_completion_request": (did in completion_requested) and (did in helping and did not in helped),
                        "favorites_count": favorites_count_by_dream.get(did, 0),
                    }
                    result.append(item)
                try:
                    cur.execute("SELECT COUNT(*) AS n FROM dreams WHERE COALESCE(is_public, true) = true")
                    count_all = cur.fetchone()["n"] or 0
                    cur.execute("SELECT COUNT(*) AS n FROM user_dream_favorites WHERE user_id = %s", (user_id,))
                    count_favorites = cur.fetchone()["n"] or 0
                    cur.execute("""SELECT COUNT(*) AS n FROM user_dream_help_intent h JOIN dreams d ON d.id = h.dream_id
                        WHERE h.user_id = %s AND COALESCE(d.is_public, true) = true
                        AND NOT EXISTS (SELECT 1 FROM user_dream_helped hl WHERE hl.user_id = %s AND hl.dream_id = h.dream_id)""", (user_id, user_id))
                    count_helping = cur.fetchone()["n"] or 0
                    cur.execute("""SELECT COUNT(*) AS n FROM user_dream_helped hl JOIN dreams d ON d.id = hl.dream_id
                        WHERE hl.user_id = %s AND COALESCE(d.is_public, true) = true""", (user_id,))
                    count_helped = cur.fetchone()["n"] or 0
                except Exception:
                    count_all = count_favorites = count_helping = count_helped = 0
                counts = {"new": 0, "helping": count_helping, "helped": count_helped, "favorites": count_favorites, "all": count_all}
                return {"dreams": result, "counts": counts}
            try:
                cur.execute("""
                    SELECT d.id, d.dream, d.deadline, d.price, d.date, d.user_id,
                           COALESCE(s.code, 'planned') AS status_code,
                           s.label_ru AS status_label,
                           u.name AS user_name, u.surname AS user_surname, u.city AS user_city,
                           u.telegram AS user_telegram, u.vk AS user_vk, u.phone AS user_phone
                    FROM dreams d
                    JOIN users u ON u.id = d.user_id
                    LEFT JOIN dreams_statuses s ON d.status_id = s.id
                    WHERE COALESCE(d.is_public, true) = true
                    ORDER BY d.id DESC
                """)
                rows = cur.fetchall()
            except psycopg2.ProgrammingError:
                conn.rollback()
                cur.execute("""
                    SELECT d.id, d.dream, d.deadline, d.price, d.date, d.user_id,
                           u.name AS user_name, u.surname AS user_surname, u.city AS user_city,
                           u.telegram AS user_telegram, u.vk AS user_vk, u.phone AS user_phone
                    FROM dreams d
                    JOIN users u ON u.id = d.user_id
                    WHERE COALESCE(d.is_public, true) = true
                    ORDER BY d.id DESC
                """)
                rows = cur.fetchall()
                for r in rows:
                    r["status_code"] = "planned"
                    r["status_label"] = "Запланировано"
            dream_ids = [r["id"] for r in rows]
            viewed = set()
            favorites = set()
            helping = set()
            helped = set()
            completion_requested = set()
            if user_id and dream_ids:
                try:
                    cur.execute(
                        "SELECT dream_id FROM user_dream_views WHERE user_id = %s AND dream_id = ANY(%s)",
                        (user_id, dream_ids),
                    )
                    viewed = {r["dream_id"] for r in cur.fetchall()}
                    cur.execute(
                        "SELECT dream_id FROM user_dream_favorites WHERE user_id = %s AND dream_id = ANY(%s)",
                        (user_id, dream_ids),
                    )
                    favorites = {r["dream_id"] for r in cur.fetchall()}
                    cur.execute(
                        "SELECT dream_id FROM user_dream_help_intent WHERE user_id = %s AND dream_id = ANY(%s)",
                        (user_id, dream_ids),
                    )
                    helping = {r["dream_id"] for r in cur.fetchall()}
                    cur.execute(
                        "SELECT dream_id FROM user_dream_helped WHERE user_id = %s AND dream_id = ANY(%s)",
                        (user_id, dream_ids),
                    )
                    helped = {r["dream_id"] for r in cur.fetchall()}
                    try:
                        cur.execute(
                            "SELECT dream_id FROM user_dream_completion_request WHERE helper_user_id = %s AND dream_id = ANY(%s)",
                            (user_id, dream_ids),
                        )
                        completion_requested = {r["dream_id"] for r in cur.fetchall()}
                    except psycopg2.ProgrammingError:
                        pass
                except psycopg2.ProgrammingError:
                    pass
            favorites_count_by_dream = {}
            if dream_ids:
                try:
                    cur.execute(
                        "SELECT dream_id, COUNT(*) AS c FROM user_dream_favorites WHERE dream_id = ANY(%s) GROUP BY dream_id",
                        (dream_ids,),
                    )
                    for row in cur.fetchall():
                        favorites_count_by_dream[row["dream_id"]] = row["c"] or 0
                except psycopg2.ProgrammingError:
                    pass
            result = []
            for r in rows:
                did = r["id"]
                full_name = f"{r.get('user_name') or ''} {r.get('user_surname') or ''}".strip() or "Участник"
                price_val = r.get("price")
                if price_val is not None:
                    try:
                        price_val = float(price_val)
                    except (TypeError, ValueError):
                        price_val = None
                else:
                    price_val = None
                item = {
                    "id": did,
                    "dream": r.get("dream") or "",
                    "deadline": str(r["deadline"]) if r.get("deadline") else None,
                    "price": price_val,
                    "date": str(r["date"]) if r.get("date") else None,
                    "user_id": r["user_id"],
                    "user_name": full_name,
                    "city": (r.get("user_city") or "").strip() or None,
                    "status": r.get("status_code") or "planned",
                    "status_label": r.get("status_label") or "Запланировано",
                    "telegram": (r.get("user_telegram") or "").strip() or None,
                    "vk": (r.get("user_vk") or "").strip() or None,
                    "phone": r.get("user_phone"),
                    "is_viewed": did in viewed,
                    "is_favorite": did in favorites,
                    "is_helping": did in helping and did not in helped,
                    "is_helped": did in helped,
                    "pending_completion_request": (did in completion_requested) and (did in helping and did not in helped),
                    "favorites_count": favorites_count_by_dream.get(did, 0),
                }
                result.append(item)
            if showcase_filter and user_id:
                if showcase_filter == "new":
                    result = [x for x in result if not x["is_viewed"]]
                elif showcase_filter == "helping":
                    result = [x for x in result if x["is_helping"]]
                elif showcase_filter == "helped":
                    result = [x for x in result if x["is_helped"]]
                elif showcase_filter == "favorites":
                    result = [x for x in result if x["is_favorite"]]
                elif showcase_filter == "viewed":
                    result = [x for x in result if x["is_viewed"]]
            if user_id:
                result.sort(key=lambda x: x["date"] or "", reverse=True)
                result.sort(key=lambda x: x["is_viewed"])
            else:
                result.sort(key=lambda x: x["date"] or "", reverse=True)
            # Счётчики: Новые, Помогаю, Помог, Избранные, Все
            count_all = len(rows)
            count_new = count_all - len(viewed) if user_id else count_all
            count_helping = len([d for d in helping if d not in helped])
            count_helped = len(helped)
            count_favorites = len(favorites)
            counts = {"new": count_new, "helping": count_helping, "helped": count_helped, "favorites": count_favorites, "all": count_all}
            return {"dreams": result, "counts": counts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


class ShowcaseActionBody(BaseModel):
    user_id: int


class AcceptCompletionBody(BaseModel):
    user_id: int
    move_to_done: Optional[bool] = True  # True = в завершённые (status_id=3), False = вернуть в личные (dreams_log + помог, статус не меняем — для повторяемых мечт)


@app.get("/dreams/{dream_id}/contact")
def get_dream_contact(dream_id: int):
    """Контакты автора мечты (telegram, vk, phone) — для модалки «Хочу помочь». Всегда актуальные из БД."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT u.name, u.surname, u.city, u.telegram, u.vk, u.phone
                FROM dreams d JOIN users u ON u.id = d.user_id
                WHERE d.id = %s AND COALESCE(d.is_public, true) = true
            """, (dream_id,))
            r = cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Мечта не найдена")
            full_name = f"{r.get('name') or ''} {r.get('surname') or ''}".strip() or "Участник"
            return {
                "user_name": full_name,
                "city": (r.get("user_city") or "").strip() or None,
                "telegram": (r.get("telegram") or "").strip() or None,
                "vk": (r.get("vk") or "").strip() or None,
                "phone": r.get("phone"),
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.post("/dreams/{dream_id}/view")
def record_dream_view(dream_id: int, body: ShowcaseActionBody):
    """Записать просмотр мечты (при появлении карточки во вьюпорте)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_dream_views (user_id, dream_id) VALUES (%s, %s)
                   ON CONFLICT (user_id, dream_id) DO UPDATE SET viewed_at = NOW()""",
                (body.user_id, dream_id),
            )
        conn.commit()
        return {"ok": True}
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=404, detail="Мечта не найдена")
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.post("/dreams/{dream_id}/favorite")
def add_dream_favorite(dream_id: int, body: ShowcaseActionBody):
    """Добавить мечту в избранное. Владельцу создаётся запись в dream_favorite_notifications (для колокольчика)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO user_dream_favorites (user_id, dream_id) VALUES (%s, %s) ON CONFLICT (user_id, dream_id) DO NOTHING RETURNING id",
                (body.user_id, dream_id),
            )
            inserted = cur.fetchone()
        conn.commit()
        if inserted:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur2:
                    cur2.execute("SELECT user_id FROM dreams WHERE id = %s", (dream_id,))
                    row = cur2.fetchone()
                    if row:
                        owner_id = row["user_id"]
                        if owner_id != body.user_id:
                            cur2.execute(
                                "INSERT INTO dream_favorite_notifications (owner_id, dream_id) VALUES (%s, %s)",
                                (owner_id, dream_id),
                            )
                conn.commit()
            except (psycopg2.ProgrammingError, psycopg2.OperationalError):
                if conn:
                    conn.rollback()
        return {"ok": True}
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=404, detail="Мечта не найдена")
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.delete("/dreams/{dream_id}/favorite")
def remove_dream_favorite(dream_id: int, user_id: int):
    """Убрать мечту из избранного."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_dream_favorites WHERE user_id = %s AND dream_id = %s", (user_id, dream_id))
        conn.commit()
        return {"ok": True}
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


def _ensure_completion_request_table(cur):
    """Создать таблицу user_dream_completion_request, если её нет."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_dream_completion_request (
            id SERIAL PRIMARY KEY,
            dream_id INT NOT NULL REFERENCES dreams(id) ON DELETE CASCADE,
            helper_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            requested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            UNIQUE(dream_id, helper_user_id)
        )
    """)
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_completion_request_dream ON user_dream_completion_request(dream_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_completion_request_helper ON user_dream_completion_request(helper_user_id)")
    except psycopg2.ProgrammingError:
        pass


@app.post("/dreams/{dream_id}/completion-request")
def create_completion_request(dream_id: int, body: ShowcaseActionBody):
    """Помощник нажал «Готово!» — отправить запрос владельцу. Возвращает owner_name для тоста."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_completion_request_table(cur)
            conn.commit()
            cur.execute("SELECT id, user_id FROM dreams WHERE id = %s", (dream_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Мечта не найдена")
            owner_id = row["user_id"]
            cur.execute(
                "SELECT 1 FROM user_dream_help_intent WHERE user_id = %s AND dream_id = %s",
                (body.user_id, dream_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="Вы не помогаете этой мечте")
            cur.execute(
                """INSERT INTO user_dream_completion_request (dream_id, helper_user_id, requested_at)
                   VALUES (%s, %s, NOW())
                   ON CONFLICT (dream_id, helper_user_id) DO UPDATE SET requested_at = NOW()""",
                (dream_id, body.user_id),
            )
            cur.execute("SELECT name, surname FROM users WHERE id = %s", (owner_id,))
            owner = cur.fetchone()
            owner_name = "Участник"
            if owner:
                owner_name = f"{owner.get('name') or ''} {owner.get('surname') or ''}".strip() or owner_name
        conn.commit()
        return {"ok": True, "owner_name": owner_name}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.get("/dreams/notifications")
def get_dreams_notifications(user_id: int):
    """Уведомления владельца: (1) мечты, по которым помощник нажал «Готово!»; (2) мечты, которые добавили в избранное. Для колокольчика."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            completion_list = []
            try:
                cur.execute("""
                    SELECT r.dream_id, r.helper_user_id, r.requested_at,
                           d.dream, d.deadline,
                           u.name AS helper_name, u.surname AS helper_surname
                    FROM user_dream_completion_request r
                    JOIN dreams d ON d.id = r.dream_id AND d.user_id = %s
                    JOIN users u ON u.id = r.helper_user_id
                    ORDER BY r.requested_at DESC
                """, (user_id,))
                rows = cur.fetchall()
            except psycopg2.ProgrammingError:
                rows = []
            seen_dreams = {}
            for r in rows:
                did = r["dream_id"]
                helper_name = f"{r.get('helper_name') or ''} {r.get('helper_surname') or ''}".strip() or "Участник"
                if did not in seen_dreams:
                    seen_dreams[did] = {"dream_id": did, "dream": r.get("dream") or "", "deadline": str(r["deadline"]) if r.get("deadline") else None, "helper_names": [], "at": r.get("requested_at")}
                    completion_list.append(seen_dreams[did])
                seen_dreams[did]["helper_names"].append(helper_name)
            favorite_list = []
            try:
                cur.execute("""
                    SELECT n.dream_id, n.created_at, d.dream, d.deadline
                    FROM dream_favorite_notifications n
                    JOIN dreams d ON d.id = n.dream_id AND d.user_id = %s
                    ORDER BY n.created_at DESC
                """, (user_id,))
                fav_rows = cur.fetchall()
            except psycopg2.ProgrammingError:
                fav_rows = []
            for r in fav_rows:
                favorite_list.append({
                    "type": "favorite",
                    "dream_id": r["dream_id"],
                    "dream": r.get("dream") or "",
                    "deadline": str(r["deadline"]) if r.get("deadline") else None,
                    "at": r.get("created_at"),
                })
            out = []
            for o in completion_list:
                at_val = o.get("at")
                at_str = at_val.isoformat() if at_val and hasattr(at_val, "isoformat") else str(at_val or "")
                out.append({
                    "type": "completion",
                    "dream_id": o["dream_id"],
                    "dream": o["dream"],
                    "deadline": o["deadline"],
                    "helper_names": list(dict.fromkeys(o["helper_names"])),
                    "_at": at_str,
                })
            for o in favorite_list:
                at_val = o.get("at")
                at_str = at_val.isoformat() if at_val and hasattr(at_val, "isoformat") else str(at_val or "")
                out.append({
                    "type": "favorite",
                    "dream_id": o["dream_id"],
                    "dream": o["dream"],
                    "deadline": o["deadline"],
                    "_at": at_str,
                })
            out.sort(key=lambda x: x.get("_at") or "", reverse=True)
            for o in out:
                o.pop("_at", None)
            return {"notifications": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.post("/dreams/{dream_id}/accept-completion")
def accept_completion(dream_id: int, body: AcceptCompletionBody):
    """Владелец нажал «Принять»: все помощники получают «Помог», запись в dreams_log. move_to_done=True — мечта в завершённые (status_id=3); False — остаётся в личных (для повторяемых)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, user_id FROM dreams WHERE id = %s", (dream_id,))
            row = cur.fetchone()
            if not row or row["user_id"] != body.user_id:
                raise HTTPException(status_code=404, detail="Мечта не найдена или вы не владелец")
            cur.execute("SELECT user_id FROM user_dream_help_intent WHERE dream_id = %s", (dream_id,))
            helpers = [r["user_id"] for r in cur.fetchall()]
            for h in helpers:
                cur.execute("INSERT INTO user_dream_helped (user_id, dream_id) VALUES (%s, %s) ON CONFLICT (user_id, dream_id) DO NOTHING", (h, dream_id))
                cur.execute("DELETE FROM user_dream_help_intent WHERE user_id = %s AND dream_id = %s", (h, dream_id))
            cur.execute("DELETE FROM user_dream_completion_request WHERE dream_id = %s", (dream_id,))
            if body.move_to_done is not False:
                cur.execute("UPDATE dreams SET status_id = 3 WHERE id = %s", (dream_id,))
            cur.execute("INSERT INTO dreams_log (dream_id, date, fulfilled_by_user_id) VALUES (%s, CURRENT_DATE, %s)", (dream_id, body.user_id))
        conn.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.post("/dreams/{dream_id}/revision")
def revision_completion(dream_id: int, body: ShowcaseActionBody):
    """Владелец нажал «На доработку»: снять запрос на завершение, помощник остаётся в «Помогаю»."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM dreams WHERE id = %s", (dream_id,))
            row = cur.fetchone()
            if not row or row[0] != body.user_id:
                raise HTTPException(status_code=404, detail="Мечта не найдена или вы не владелец")
            cur.execute("DELETE FROM user_dream_completion_request WHERE dream_id = %s", (dream_id,))
        conn.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.post("/dreams/{dream_id}/decline-help")
def decline_help(dream_id: int, body: ShowcaseActionBody):
    """Владелец нажал «Отказаться»: убрать всех помощников по этой мечте (МВП — от всех разом)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM dreams WHERE id = %s", (dream_id,))
            row = cur.fetchone()
            if not row or row[0] != body.user_id:
                raise HTTPException(status_code=404, detail="Мечта не найдена или вы не владелец")
            cur.execute("DELETE FROM user_dream_completion_request WHERE dream_id = %s", (dream_id,))
            cur.execute("DELETE FROM user_dream_help_intent WHERE dream_id = %s", (dream_id,))
        conn.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.post("/dreams/{dream_id}/helped")
def record_dream_helped(dream_id: int, body: ShowcaseActionBody):
    """Отметить «Помог» — пользователь завершил помощь мечте. Удаляет из help_intent, добавляет в helped. (Вызывается после того, как владелец нажал «Принять».)"""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_dream_helped (user_id, dream_id) VALUES (%s, %s) ON CONFLICT (user_id, dream_id) DO NOTHING",
                (body.user_id, dream_id),
            )
            cur.execute(
                "DELETE FROM user_dream_help_intent WHERE user_id = %s AND dream_id = %s",
                (body.user_id, dream_id),
            )
        conn.commit()
        return {"ok": True}
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=404, detail="Мечта не найдена")
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.delete("/dreams/{dream_id}/helped")
def revert_dream_helped(dream_id: int, user_id: int):
    """Вернуть — отменить помощь (удалить из helped и help_intent)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_dream_helped WHERE user_id = %s AND dream_id = %s", (user_id, dream_id))
            cur.execute("DELETE FROM user_dream_help_intent WHERE user_id = %s AND dream_id = %s", (user_id, dream_id))
        conn.commit()
        return {"ok": True}
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.post("/dreams/{dream_id}/help-intent")
def record_dream_help_intent(dream_id: int, body: ShowcaseActionBody):
    """Записать намерение помочь (нажал «Хочу помочь»)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_dream_help_intent (user_id, dream_id) VALUES (%s, %s) ON CONFLICT (user_id, dream_id) DO NOTHING",
                (body.user_id, dream_id),
            )
        conn.commit()
        return {"ok": True}
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=404, detail="Мечта не найдена")
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


# --- Эндпоинт 2: ПОЛУЧЕНИЕ МЕЧТ ПОЛЬЗОВАТЕЛЯ ---
@app.get("/dreams")
def get_dreams(user_id: int, viewer_id: Optional[int] = None):
    """Список мечт пользователя user_id. Если передан viewer_id: отдаём только если viewer_id == user_id или viewer — бадди user_id (users.buddy_id у viewer = user_id)."""
    conn = None
    try:
        conn = get_db_connection()
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
                           d.rule_code, d.settings,
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
            dream_ids_books = [r["id"] for r in dreams_rows if r.get("rule_code") == "books_reading"]
            books_by_dream = _load_books(cur, dream_ids_books) if dream_ids_books else {}
            result = [_build_dream_item(row, steps_by_dream, books_by_dream) for row in dreams_rows]
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
    except OperationalError as e:
        _return_conn(conn, discard=True)
        conn = None
        raise HTTPException(status_code=503, detail=f"Ошибка соединения с БД (повторите попытку): {str(e)}")
    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка: {str(e)}\n{traceback.format_exc()}"
        )
    finally:
        _return_conn(conn)


@app.get("/schedule")
def get_schedule(user_id: int, date_from: Optional[str] = None, date_to: Optional[str] = None):
    """Агрегатор расписания: обычные шаги + виртуальные строки от мечт типа «книги». Параметры date_from, date_to в формате YYYY-MM-DD; по умолчанию — сегодня."""
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    date_from = date_from or today
    date_to = date_to or today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            items = _schedule_items_standard(cur, user_id, date_from, date_to)
            items.extend(_schedule_items_books(cur, user_id, date_from, date_to))
            items.sort(key=lambda x: (x["date"], x["title"]))
            return {"items": items, "date_from": date_from, "date_to": date_to}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.post("/dreams")
def create_dream(body: DreamCreate):
    """Добавить мечту. Обязательно: user_id, dream. Опционально: status_id (по умолчанию 1), category_id, deadline (YYYY-MM-DD)."""
    if not (body.dream and body.dream.strip()):
        raise HTTPException(status_code=400, detail="Текст мечты не может быть пустым")
    status_id = body.status_id if body.status_id is not None else 1
    is_public = body.is_public if body.is_public is not None else False
    conn = None
    try:
        conn = get_db_connection()
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
        _return_conn(conn)


# Маппинг status_id -> code для старой схемы (колонка status VARCHAR)
_STATUS_ID_TO_CODE = {1: "planned", 2: "in_progress", 3: "done"}

@app.patch("/dreams/{dream_id}")
def update_dream(dream_id: int, body: DreamUpdate, user_id: int):
    """Обновить мечту (текст, статус, дедлайн). Только если мечта принадлежит user_id."""
    conn = None
    try:
        conn = get_db_connection()
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
            if "rule_code" in payload:
                updates.append("rule_code = %s")
                vals.append(payload["rule_code"] if payload["rule_code"] else None)
            if "settings" in payload:
                updates.append("settings = %s")
                vals.append(Json(payload["settings"]) if payload["settings"] is not None else None)
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
        _return_conn(conn)


@app.delete("/dreams/{dream_id}")
def delete_dream(dream_id: int, user_id: int, viewer_id: Optional[int] = None):
    """Удалить мечту. Разрешено владельцу или бадди с buddy_trust=true (viewer_id=кто удаляет)."""
    conn = None
    try:
        conn = get_db_connection()
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
        _return_conn(conn)


@app.post("/dreams/{dream_id}/steps")
def create_step(dream_id: int, body: StepCreate, user_id: int, viewer_id: Optional[int] = None):
    """Добавить шаг к мечте. Разрешено владельцу или бадди с buddy_trust=true."""
    conn = None
    try:
        conn = get_db_connection()
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
        _return_conn(conn)


MONTH_NAMES_RU = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")


def _compute_custom_plan_amounts(body: FinanceStepsCreate) -> List[float]:
    """Считает 12 помесячных планов для distribution=custom: из monthly_amounts или по формуле (янв 0, фев A, далее A*N^k)."""
    if body.distribution != "custom":
        return []
    if body.monthly_amounts and len(body.monthly_amounts) >= 12:
        amounts = [float(x) for x in body.monthly_amounts[:12]]
        s = sum(amounts)
        if s > 0:
            k = body.target_amount / s
            return [round(a * k, 2) for a in amounts]
        return amounts
    if body.formula:
        first_zero = body.formula.get("first_month_zero", True)
        a = float(body.formula.get("second_month_amount") or 0)
        n = float(body.formula.get("multiplier") or 1)
        if a <= 0 or n <= 0:
            raise HTTPException(status_code=400, detail="formula: second_month_amount и multiplier должны быть > 0")
        # месяц 1 = 0 или A/N (если не first_zero), месяц 2 = A, месяц k = A * n^(k-2) для k=3..12
        amounts = [0.0] * 12
        if first_zero:
            amounts[0] = 0.0
            amounts[1] = a
            for k in range(2, 12):
                amounts[k] = a * (n ** (k - 1))
        else:
            amounts[0] = a / n
            amounts[1] = a
            for k in range(2, 12):
                amounts[k] = a * (n ** (k - 1))
        s = sum(amounts)
        if s <= 0:
            raise HTTPException(status_code=400, detail="formula: сумма получилась 0 или отрицательная")
        k = body.target_amount / s
        return [round(x * k, 2) for x in amounts]
    raise HTTPException(status_code=400, detail="При distribution=custom укажите monthly_amounts или formula")


@app.post("/dreams/{dream_id}/steps/finance")
def create_finance_steps(dream_id: int, body: FinanceStepsCreate, user_id: int, viewer_id: Optional[int] = None):
    """Создать шаги финцели (помесячно): равные доли или разные (список/формула). Разрешено владельцу или бадди с доверием."""
    try:
        end = datetime.strptime(body.end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="end_date в формате YYYY-MM-DD")
    year = end.year
    due_day = max(1, min(31, body.due_day))
    if body.distribution == "equal":
        plan_per_month = round(body.target_amount / 12 / 1000) * 1000
        if plan_per_month <= 0:
            plan_per_month = round(body.target_amount / 12, 2)
        plans = [plan_per_month] * 12
    elif body.distribution == "custom":
        plans = _compute_custom_plan_amounts(body)
        if len(plans) != 12:
            raise HTTPException(status_code=400, detail="Нужно 12 сумм по месяцам")
    else:
        raise HTTPException(status_code=400, detail="distribution должен быть equal или custom")
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _resolve_editor_and_check_dream(cur, dream_id, user_id, viewer_id)
            cur.execute("SELECT COUNT(*) AS n FROM dreams_steps WHERE dream_id = %s AND deleted = false", (dream_id,))
            if cur.fetchone()["n"] > 0:
                raise HTTPException(status_code=400, detail="У мечты уже есть шаги. Удалите их перед созданием шагов по анкете.")
            steps_out = []
            for month_1based in range(1, 13):
                _, last_day = calendar.monthrange(year, month_1based)
                day = min(due_day, last_day)
                deadline = f"{year}-{month_1based:02d}-{day:02d}"
                title = MONTH_NAMES_RU[month_1based - 1]
                plan_val = plans[month_1based - 1]
                cur.execute(
                    """INSERT INTO dreams_steps (dream_id, title, completed, sort_order, deadline, plan_amount, fact_amount)
                       VALUES (%s, %s, false, %s, %s, %s, 0)
                       RETURNING id, title, completed, deadline, plan_amount""",
                    (dream_id, title, month_1based - 1, deadline, plan_val),
                )
                row = cur.fetchone()
                steps_out.append({
                    "id": row["id"],
                    "title": row["title"],
                    "completed": False,
                    "deadline": row["deadline"],
                    "plan_amount": float(row["plan_amount"]) if row.get("plan_amount") is not None else None,
                })
            conn.commit()
            return {"created": len(steps_out), "steps": steps_out}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)


@app.patch("/dreams/{dream_id}/steps/{step_id}")
def update_step(dream_id: int, step_id: int, body: StepUpdate, user_id: int, viewer_id: Optional[int] = None):
    """Обновить шаг. Разрешено владельцу мечты или бадди с buddy_trust=true."""
    conn = None
    try:
        conn = get_db_connection()
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
            if body.fact_amount is not None:
                updates.append("fact_amount = %s")
                vals.append(body.fact_amount)
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
        _return_conn(conn)


# --- Книги (модуль books_reading) ---
@app.post("/dreams/{dream_id}/books")
def create_dream_book(dream_id: int, body: DreamBookCreate, user_id: int, viewer_id: Optional[int] = None):
    """Добавить книгу к мечте с rule_code=books_reading. Владелец или бадди с доверием."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _resolve_editor_and_check_dream(cur, dream_id, user_id, viewer_id)
            cur.execute(
                """INSERT INTO dream_books (dream_id, title, author, status, started_at, deadline, finished_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id, title, author, status, started_at, deadline, finished_at""",
                (
                    dream_id,
                    body.title.strip(),
                    body.author.strip() if body.author else None,
                    body.status or "planned",
                    body.started_at if body.started_at else None,
                    body.deadline if body.deadline else None,
                    body.finished_at if body.finished_at else None,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return {
                "id": row["id"],
                "title": row["title"],
                "author": row["author"],
                "status": row["status"],
                "started_at": str(row["started_at"]) if row.get("started_at") else None,
                "deadline": str(row["deadline"]) if row.get("deadline") else None,
                "finished_at": str(row["finished_at"]) if row.get("finished_at") else None,
            }
    except psycopg2.ProgrammingError as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    finally:
        _return_conn(conn)


@app.patch("/dreams/{dream_id}/books/{book_id}")
def update_dream_book(dream_id: int, book_id: int, body: DreamBookUpdate, user_id: int, viewer_id: Optional[int] = None):
    """Обновить книгу. Владелец мечты или бадди с доверием."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _resolve_editor_and_check_dream(cur, dream_id, user_id, viewer_id)
            updates, vals = [], []
            if body.title is not None:
                updates.append("title = %s")
                vals.append(body.title.strip())
            if body.author is not None:
                updates.append("author = %s")
                vals.append(body.author.strip() if body.author else None)
            if body.status is not None:
                updates.append("status = %s")
                vals.append(body.status)
            if body.started_at is not None:
                updates.append("started_at = %s")
                vals.append(body.started_at if body.started_at else None)
            if body.deadline is not None:
                updates.append("deadline = %s")
                vals.append(body.deadline if body.deadline else None)
            if body.finished_at is not None:
                updates.append("finished_at = %s")
                vals.append(body.finished_at if body.finished_at else None)
            if not updates:
                return {"ok": True}
            vals.extend([book_id, dream_id])
            cur.execute(
                "UPDATE dream_books SET " + ", ".join(updates) + " WHERE id = %s AND dream_id = %s",
                vals,
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Книга не найдена")
            conn.commit()
            return {"ok": True}
    except psycopg2.ProgrammingError as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    finally:
        _return_conn(conn)


@app.post("/dreams/{dream_id}/books/{book_id}/log")
def upsert_dream_book_log(dream_id: int, book_id: int, body: DreamBookLogCreate, user_id: int, viewer_id: Optional[int] = None):
    """Отметить факт чтения за дату (или обновить). Владелец мечты или бадди с доверием."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _resolve_editor_and_check_dream(cur, dream_id, user_id, viewer_id)
            cur.execute("SELECT id FROM dream_books WHERE id = %s AND dream_id = %s", (book_id, dream_id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Книга не найдена")
            cur.execute(
                """INSERT INTO dream_books_log (book_id, date, minutes_spent, pages_read)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (book_id, date) DO UPDATE SET minutes_spent = COALESCE(EXCLUDED.minutes_spent, dream_books_log.minutes_spent),
                                                             pages_read = COALESCE(EXCLUDED.pages_read, dream_books_log.pages_read)""",
                (book_id, body.date, body.minutes_spent, body.pages_read),
            )
            conn.commit()
            return {"ok": True}
    except psycopg2.ProgrammingError as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    finally:
        _return_conn(conn)


@app.delete("/dreams/{dream_id}/books/{book_id}/log")
def delete_dream_book_log(dream_id: int, book_id: int, date: str, user_id: int, viewer_id: Optional[int] = None):
    """Убрать отметку о чтении за дату."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _resolve_editor_and_check_dream(cur, dream_id, user_id, viewer_id)
            cur.execute("SELECT 1 FROM dream_books WHERE id = %s AND dream_id = %s", (book_id, dream_id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Книга не найдена")
            cur.execute("DELETE FROM dream_books_log WHERE book_id = %s AND date = %s", (book_id, date))
            conn.commit()
            return {"ok": True}
    except psycopg2.ProgrammingError as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    finally:
        _return_conn(conn)


def _full_name(row: dict) -> str:
    """Склейка name + surname для ответа админки (схема БД: name, surname)."""
    n = (row.get("name") or "").strip()
    s = (row.get("surname") or "").strip()
    return f"{n} {s}".strip() or "—"

def _split_full_name(full_name: str) -> tuple:
    """Разбивка «ФИО» на name и surname (первое слово — имя, остальное — фамилия)."""
    parts = (full_name or "").strip().split(maxsplit=1)
    return (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")

# --- Roadmap API (публичный: просмотр и добавление идей) ---
@app.get("/roadmap")
def roadmap_list(status: Optional[str] = None, section: Optional[str] = None):
    """Список пунктов roadmap. Фильтры: status=plan|done|all, section=Раздел."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = []
            params = []
            if status and status != "all":
                where.append("status = %s")
                params.append(status)
            if section:
                where.append("section = %s")
                params.append(section)
            sql = "SELECT id, step, text, section, status, initiator, count, date_added, date_done, priority, comment FROM roadmap ORDER BY step"
            if where:
                sql = "SELECT id, step, text, section, status, initiator, count, date_added, date_done, priority, comment FROM roadmap WHERE " + " AND ".join(where) + " ORDER BY step"
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            rows = cur.fetchall()
            return [{
                "id": r["id"],
                "step": r["step"],
                "text": r["text"],
                "section": r["section"] or "",
                "status": r["status"],
                "initiator": r["initiator"] or "",
                "count": r["count"] or 1,
                "dateAdded": str(r["date_added"]) if r["date_added"] else "",
                "dateDone": str(r["date_done"]) if r["date_done"] else "",
                "priority": r["priority"] or "",
                "comment": r["comment"] or "",
            } for r in rows]
    finally:
        _return_conn(conn)

@app.post("/roadmap")
def roadmap_create(item: RoadmapItemCreate):
    """Добавить идею в roadmap. step назначается автоматически."""
    conn = None
    try:
        conn = get_db_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(step), 0) + 1 AS next_step FROM roadmap")
            next_step = cur.fetchone()["next_step"]
            today = datetime.now().strftime("%Y-%m-%d")
            cur.execute("""
                INSERT INTO roadmap (step, text, section, status, initiator, count, date_added)
                VALUES (%s, %s, %s, 'plan', %s, 1, %s)
                RETURNING id, step, text, section, status, initiator, count, date_added, date_done, priority, comment
            """, (next_step, (item.text or "").strip(), (item.section or "").strip(), (item.initiator or "").strip(), today))
            row = cur.fetchone()
            conn.commit()
            return {
                "id": row["id"],
                "step": row["step"],
                "text": row["text"],
                "section": row["section"] or "",
                "status": row["status"],
                "initiator": row["initiator"] or "",
                "count": row["count"] or 1,
                "dateAdded": str(row["date_added"]) if row["date_added"] else "",
                "dateDone": str(row["date_done"]) if row["date_done"] else "",
                "priority": row["priority"] or "",
                "comment": row["comment"] or "",
            }
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)

@app.patch("/roadmap/{item_id}")
def roadmap_update(item_id: int, body: RoadmapItemUpdate):
    """Обновить пункт roadmap (статус, текст, раздел, инициатор)."""
    conn = None
    try:
        conn = get_db_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, status, text, section, initiator FROM roadmap WHERE id = %s", (item_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Пункт не найден")
            updates = []
            params = []
            if body.status is not None:
                if body.status not in ("plan", "in_progress", "done"):
                    raise HTTPException(status_code=400, detail="status должен быть plan, in_progress или done")
                updates.append("status = %s")
                params.append(body.status)
                if body.status == "done":
                    updates.append("date_done = %s")
                    params.append(datetime.now().strftime("%Y-%m-%d"))
                else:
                    updates.append("date_done = NULL")
            if body.text is not None:
                updates.append("text = %s")
                params.append((body.text or "").strip())
            if body.section is not None:
                updates.append("section = %s")
                params.append((body.section or "").strip())
            if body.initiator is not None:
                updates.append("initiator = %s")
                params.append((body.initiator or "").strip())
            if not updates:
                raise HTTPException(status_code=400, detail="Укажите хотя бы одно поле для обновления")
            params.append(item_id)
            cur.execute(
                "UPDATE roadmap SET " + ", ".join(updates) + " WHERE id = %s RETURNING id, step, text, section, status, initiator, count, date_added, date_done, priority, comment",
                params,
            )
            updated = cur.fetchone()
            conn.commit()
            return {
                "id": updated["id"],
                "step": updated["step"],
                "text": updated["text"],
                "section": updated["section"] or "",
                "status": updated["status"],
                "initiator": updated["initiator"] or "",
                "count": updated["count"] or 1,
                "dateAdded": str(updated["date_added"]) if updated["date_added"] else "",
                "dateDone": str(updated["date_done"]) if updated["date_done"] else "",
                "priority": updated["priority"] or "",
                "comment": updated["comment"] or "",
            }
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)

@app.delete("/roadmap/{item_id}")
def roadmap_delete(item_id: int):
    """Удалить пункт roadmap."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM roadmap WHERE id = %s RETURNING id", (item_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Пункт не найден")
        conn.commit()
        return {"message": "Удалено"}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _return_conn(conn)

# --- Админ API (схема БД: name, surname) ---
@app.get("/admin/users")
def admin_list_users():
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, surname, phone, city FROM users ORDER BY id")
            rows = cur.fetchall()
            return [{"id": r["id"], "full_name": _full_name(r), "phone": r["phone"], "city": r["city"]} for r in rows]
    finally:
        _return_conn(conn)

@app.get("/admin/users/{user_id}")
def admin_get_user(user_id: int):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, surname, phone, city FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            return {"id": row["id"], "full_name": _full_name(row), "phone": row["phone"], "city": row["city"]}
    finally:
        _return_conn(conn)

@app.post("/admin/users")
def admin_create_user(user: UserCreate):
    conn = None
    try:
        conn = get_db_connection()
        conn.autocommit = False
        name, surname = _split_full_name(user.full_name)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (name, surname, phone, city, password_hash)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, surname, phone, city
            """, (name, surname, user.phone, user.city, bcrypt.hash(_bcrypt_password(user.password))))
            row = cur.fetchone()
            conn.commit()
            return {"id": row["id"], "full_name": _full_name(row), "phone": row["phone"], "city": row["city"]}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Телефон уже занят")
    finally:
        _return_conn(conn)

@app.put("/admin/users/{user_id}")
def admin_update_user(user_id: int, user: UserUpdate):
    conn = None
    try:
        conn = get_db_connection()
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, surname, phone, city, password_hash FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            name, surname = _split_full_name(user.full_name) if user.full_name is not None else (row["name"], row["surname"])
            phone = user.phone if user.phone is not None else row["phone"]
            city = user.city if user.city is not None else row["city"]
            password_hash = bcrypt.hash(_bcrypt_password(user.password)) if user.password else row["password_hash"]
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
        _return_conn(conn)

@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
        conn.commit()
        return {"message": "Пользователь удалён"}
    finally:
        _return_conn(conn)