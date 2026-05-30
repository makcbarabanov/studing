"""
«Завтрак» — stateless AI + финальное сохранение в БД.
UI state machine живёт на фронте; бэк: action=ai | save.
"""
from __future__ import annotations

import os
import re
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Dict, List, Literal, Optional, TypedDict

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

_APP_DIR = Path(__file__).resolve().parent


def resolve_breakfast_dir() -> Path:
    """Песок: OSTROV/sites/breakfast. Прод (Docker): volume /app/sites/breakfast."""
    env = (os.getenv("BREAKFAST_DIR") or "").strip()
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    for candidate in (
        _APP_DIR / "sites" / "breakfast",
        _APP_DIR.parent / "sites" / "breakfast",
    ):
        if candidate.is_dir():
            return candidate
    return _APP_DIR / "sites" / "breakfast"


def sveta_prompt_path() -> Path:
    return resolve_breakfast_dir() / "prompts" / "sveta.md"

_rate: Dict[str, Deque[float]] = defaultdict(deque)
_rate_lock = Lock()

RATE_LIMIT = 30
RATE_WINDOW_SEC = 60.0

ProviderKind = Literal["gemini", "huggingface", "openai"]
AiKind = Literal["dreams_reaction", "barriers_open", "barriers_reaction"]
ContactChannel = Literal["telegram", "max", "vk", "whatsapp", "email"]

HF_ROUTER_BASE = "https://router.huggingface.co/v1"

GEMINI_ERROR_REPLY = "Ой, магия немного зависла. Можешь отправить еще раз?"

# CJK / иероглифы — Qwen и др. fallback-модели
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
# Хвост с «добавишь ещё» — дублирует кнопки на сайте
_BTN_DUP_RE = re.compile(
    r'[.\s]*[«"]?(?:Добавишь|добавишь|Хочешь что-то еще|ид[её]м дальше)[^.\n!?]*[»"]?[.!?]?\s*$',
    re.IGNORECASE | re.MULTILINE,
)


def _sanitize_sveta_reply(reply: str) -> str:
    """Обрезает иероглифы и мусор; пользователь не должен видеть CJK."""
    if not reply:
        return ""
    cut = _CJK_RE.search(reply)
    if cut:
        reply = reply[: cut.start()]
    reply = _CJK_RE.sub("", reply)
    reply = _BTN_DUP_RE.sub("", reply.strip())
    reply = re.sub(r"\s{2,}", " ", reply).strip()
    return reply


def _reply_language_ok(reply: str) -> bool:
    if not reply or len(reply.strip()) < 12:
        return False
    return _CJK_RE.search(reply) is None


def _fallback_reply(kind: AiKind, name: str, dreams: List[str]) -> str:
    """Русская заглушка, если все LLM недоступны или ответ испорчен."""
    n = name or "друг"
    dream_hint = dreams[0] if dreams else "твоей мечте"
    if kind == "dreams_reaction":
        return (
            f"Как здорово, {n}! Слышу, как важны для тебя эти желания — "
            f"особенно про {dream_hint.lower()}. Я рядом."
        )
    if kind == "barriers_open":
        return (
            f"Рад, что делишься, {n}. Чтобы двигаться к мечтам, "
            f"расскажи: что сейчас больше всего мешает и какая поддержка или ресурс нужны?"
        )
    if kind == "barriers_reaction":
        return (
            f"Спасибо, что откровенно, {n}. Слышу тебя — это уже большой шаг к переменам."
        )
    return GEMINI_ERROR_REPLY


class RouteState(TypedDict):
    provider: ProviderKind
    key_index: int


class ContactItem(BaseModel):
    channel: ContactChannel
    value: Optional[str] = Field(None, max_length=300)
    phone_linked: bool = False


class BreakfastChatRequest(BaseModel):
    action: Literal["ai", "save"]
    ai_kind: Optional[AiKind] = None
    user_name: Optional[str] = Field(None, max_length=80)
    dreams: Optional[List[str]] = None
    barriers: Optional[List[str]] = None
    message: Optional[str] = Field(None, max_length=4000)
    # save
    name: Optional[str] = Field(None, max_length=120)
    city: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=40)
    contact_channel: Optional[ContactChannel] = None
    contact_value: Optional[str] = Field(None, max_length=300)
    phone_linked: bool = False
    email: Optional[str] = Field(None, max_length=200)
    contacts: Optional[List[ContactItem]] = None


class BreakfastChatResponse(BaseModel):
    reply: Optional[str] = None
    ok: bool = True


def _enforce_rate(request: Request) -> None:
    ip = (request.client.host if request.client else "unknown") or "unknown"
    now = time.monotonic()
    with _rate_lock:
        q = _rate[ip]
        while q and now - q[0] > RATE_WINDOW_SEC:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Слишком много сообщений. Подождите минуту.")
        q.append(now)


def _load_system_prompt() -> str:
    path = sveta_prompt_path()
    if not path.is_file():
        raise HTTPException(status_code=503, detail=f"Промпт Светы не найден: {path}")
    return path.read_text(encoding="utf-8").strip()


def _env_keys(prefix: str) -> List[str]:
    keys: List[str] = []
    primary = (os.getenv(prefix) or "").strip()
    if primary:
        keys.append(primary)
    n = 2
    while True:
        extra = (os.getenv(f"{prefix}_{n}") or "").strip()
        if not extra:
            break
        keys.append(extra)
        n += 1
    return keys


def _gemini_keys() -> List[str]:
    return _env_keys("GEMINI_API_KEY")


def _openai_keys() -> List[str]:
    return _env_keys("OPENAI_API_KEY")


def _hf_keys() -> List[str]:
    return _env_keys("HF_TOKEN")


def _is_rotatable(err: str) -> bool:
    e = err.lower()
    needles = (
        "429", "quota", "rate limit", "resource exhausted", "location is not supported",
        "billing", "permission denied", "invalid api key", "incorrect api key",
        "authentication", "unauthorized", "401", "403", "404 models/", "not found for api",
    )
    return any(n in e for n in needles)


def _history_to_gemini(history: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in history:
        role = item.get("role")
        text = item.get("text") or ""
        if role == "user":
            out.append({"role": "user", "parts": [text]})
        elif role == "model":
            out.append({"role": "model", "parts": [text]})
    return out


def _history_to_openai(history: List[Dict[str, str]], user_text: str, system: str) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
    for item in history:
        role = "assistant" if item.get("role") == "model" else "user"
        messages.append({"role": role, "content": item.get("text") or ""})
    messages.append({"role": "user", "content": user_text})
    return messages


def _gemini_reply(api_key: str, history: List[Dict[str, str]], user_text: str, system: str) -> str:
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model_name = (os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()
    model = genai.GenerativeModel(model_name, system_instruction=system)
    chat = model.start_chat(history=_history_to_gemini(history))
    response = chat.send_message(user_text)
    reply = (response.text or "").strip()
    if not reply:
        raise RuntimeError("Пустой ответ Gemini")
    return reply


def _openai_reply(
    api_key: str,
    history: List[Dict[str, str]],
    user_text: str,
    system: str,
    *,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    model = model_name or (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
    response = client.chat.completions.create(
        model=model,
        messages=_history_to_openai(history, user_text, system),
    )
    reply = (response.choices[0].message.content or "").strip()
    if not reply:
        raise RuntimeError("Пустой ответ OpenAI-совместимого API")
    return reply


def _huggingface_reply(api_key: str, history: List[Dict[str, str]], user_text: str, system: str) -> str:
    model_name = (os.getenv("HF_MODEL") or "Qwen/Qwen2.5-7B-Instruct").strip()
    return _openai_reply(api_key, history, user_text, system, base_url=HF_ROUTER_BASE, model_name=model_name)


def _all_routes() -> List[RouteState]:
    routes: List[RouteState] = []
    for i in range(len(_gemini_keys())):
        routes.append({"provider": "gemini", "key_index": i})
    for i in range(len(_openai_keys())):
        routes.append({"provider": "openai", "key_index": i})
    if (os.getenv("BREAKFAST_AI_USE_HF") or "").strip().lower() in ("1", "true", "yes"):
        for i in range(len(_hf_keys())):
            routes.append({"provider": "huggingface", "key_index": i})
    return routes


def _route_key(route: RouteState) -> str:
    if route["provider"] == "gemini":
        keys = _gemini_keys()
    elif route["provider"] == "huggingface":
        keys = _hf_keys()
    else:
        keys = _openai_keys()
    idx = route["key_index"]
    if idx < 0 or idx >= len(keys):
        raise HTTPException(status_code=503, detail="Ключ для маршрута не найден")
    return keys[idx]


def _call_route(route: RouteState, history: List[Dict[str, str]], user_text: str, system: str) -> str:
    api_key = _route_key(route)
    if route["provider"] == "gemini":
        return _gemini_reply(api_key, history, user_text, system)
    if route["provider"] == "huggingface":
        return _huggingface_reply(api_key, history, user_text, system)
    return _openai_reply(api_key, history, user_text, system)


def _call_ai(history: List[Dict[str, str]], user_text: str, system: str) -> Optional[str]:
    errors: List[str] = []
    for route in _all_routes():
        try:
            raw = _call_route(route, history, user_text, system)
            reply = _sanitize_sveta_reply(raw)
            if not _reply_language_ok(reply):
                errors.append(f"{route['provider']}#{route['key_index']}: bad reply after sanitize")
                continue
            return reply
        except HTTPException:
            raise
        except Exception as e:
            err = str(e)
            errors.append(f"{route['provider']}#{route['key_index']}: {err[:160]}")
            if not _is_rotatable(err):
                break
    return None


def _normalize_guest_name(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "Гость"
    m = re.search(r"(?:меня\s+зовут|this\s+is)\s+([a-zA-Zа-яА-ЯёЁ\-]+)", s, re.I)
    if m:
        s = m.group(1)
    elif re.match(r"^я\s+", s, re.I):
        m2 = re.match(r"^я\s+([a-zA-Zа-яА-ЯёЁ\-]+)", s, re.I)
        if m2:
            s = m2.group(1)
    if len(s.split()) > 2:
        parts = s.split()
        if parts[-1].isalpha() and 2 <= len(parts[-1]) <= 20:
            s = parts[-1]
    return s[:1].upper() + s[1:].lower() if s else "Гость"


def _dreams_block(dreams: List[str]) -> str:
    return "\n".join(f"• {d}" for d in dreams) if dreams else "—"


def _barriers_block(barriers: List[str]) -> str:
    return "\n".join(f"• {b}" for b in barriers) if barriers else "—"


def _ai_system_extra(kind: AiKind, name: str, dreams: List[str], barriers: List[str]) -> tuple[str, str]:
    dreams_txt = _dreams_block(dreams)
    barriers_txt = _barriers_block(barriers)

    if kind == "dreams_reaction":
        user = f"Гость {name} написал о мечтах:\n{dreams_txt}"
        extra = (
            "Кратко и тепло отреагируй на мечты (2–4 предложения). Реагируй на конкретику. "
            "К мужчине — «рад», к женщине — «рада». "
            "ЗАПРЕЩЕНО спрашивать «добавишь ещё», «идём дальше», «какую мечту выбрать» — "
            "на сайте уже есть кнопки «Добавить мечту» и «Идём дальше». Не дублируй их текстом."
        )
        return user, extra

    if kind == "barriers_open":
        user = (
            f"Гость {name} нажал «Идём дальше» и перешёл к обсуждению барьеров.\n"
            f"Его мечты:\n{dreams_txt}"
        )
        extra = (
            "Сначала одним-двумя предложениями тепло прокомментируй мечты. "
            "Затем одним вопросом спроси, что сейчас мешает на пути к ним и какие ресурсы нужны. "
            "2–4 предложения всего, один вопрос в конце. "
            "ЗАПРЕЩЕНО просить добавить ещё мечты, выбрать одну мечту или спрашивать «идём дальше»."
        )
        return user, extra

    if kind == "barriers_reaction":
        user = f"Гость {name} написал о барьерах и ресурсах:\n{barriers_txt}\n\nМечты:\n{dreams_txt}"
        extra = (
            "Дай эмпатичный комментарий по сути (2–4 предложения). "
            "ЗАПРЕЩЕНО спрашивать «добавить ещё», «идём дальше» — "
            "на сайте кнопки «Добавить комментарий» и «Дальше». Не дублируй их."
        )
        return user, extra

    raise HTTPException(status_code=400, detail="Неизвестный ai_kind")


def _handle_ai(body: BreakfastChatRequest) -> BreakfastChatResponse:
    if not body.ai_kind:
        raise HTTPException(status_code=400, detail="Нужен ai_kind")
    name = _normalize_guest_name(body.user_name or "Гость")
    dreams = list(body.dreams or [])
    barriers = list(body.barriers or [])

    if body.ai_kind == "dreams_reaction":
        if not body.message or not body.message.strip():
            raise HTTPException(status_code=400, detail="Нужен message")
    elif body.ai_kind == "barriers_reaction":
        if not body.message or not body.message.strip():
            raise HTTPException(status_code=400, detail="Нужен message")

    user_text, extra = _ai_system_extra(body.ai_kind, name, dreams, barriers)
    if body.message and body.message.strip() and body.ai_kind in ("dreams_reaction", "barriers_reaction"):
        user_text += f"\n\nПоследнее сообщение гостя:\n{body.message.strip()}"
    system = _load_system_prompt() + f"\n\n---\nИмя гостя: {name}.\n\n{extra}\n\nОтвечай ТОЛЬКО на русском языке. Никаких иероглифов и английского."

    try:
        reply = _call_ai([], user_text, system)
    except HTTPException:
        reply = None
    if not reply:
        reply = _fallback_reply(body.ai_kind, name, dreams)
    return BreakfastChatResponse(reply=reply, ok=True)


def _apply_contacts(
    body: BreakfastChatRequest,
) -> tuple[Optional[str], Optional[str], bool]:
    """Собирает telegram/vk из списка contacts (или legacy single channel)."""
    telegram_parts: List[str] = []
    vk: Optional[str] = None
    need_phone = False

    items: List[ContactItem] = list(body.contacts or [])
    if not items and body.contact_channel:
        items.append(
            ContactItem(
                channel=body.contact_channel,
                value=(body.contact_value or body.email or "").strip() or None,
                phone_linked=body.phone_linked,
            )
        )

    for item in items:
        ch = item.channel
        val = (item.value or "").strip()
        if ch == "telegram" and val:
            telegram_parts.append(val if val.startswith("@") else f"@{val.lstrip('@')}")
            if item.phone_linked:
                need_phone = True
        elif ch == "max":
            if val:
                telegram_parts.append(f"max:{val}")
            elif item.phone_linked:
                telegram_parts.append("max:linked")
            if item.phone_linked:
                need_phone = True
        elif ch == "vk" and val:
            vk = val
        elif ch == "email" and val:
            telegram_parts.append(f"email:{val}")
        elif ch == "whatsapp":
            need_phone = True

    telegram = " | ".join(telegram_parts) if telegram_parts else None
    return telegram, vk, need_phone


def _persist_lead(body: BreakfastChatRequest) -> tuple[int, List[int]]:
    import bcrypt
    import psycopg2
    from psycopg2.extras import RealDictCursor

    from main import _bcrypt_password, _return_conn, get_db_connection

    name = _normalize_guest_name(body.name or "")
    city = (body.city or "").strip()
    phone = (body.phone or "").strip()
    dreams = [d.strip() for d in (body.dreams or []) if d and d.strip()]
    barriers = [b.strip() for b in (body.barriers or []) if b and b.strip()]

    if not name:
        raise HTTPException(status_code=400, detail="Укажите имя")
    if not city:
        raise HTTPException(status_code=400, detail="Укажите город")
    if not dreams:
        raise HTTPException(status_code=400, detail="Нет мечт для сохранения")

    telegram, vk, need_phone = _apply_contacts(body)

    if need_phone and not phone:
        raise HTTPException(status_code=400, detail="Укажите телефон")

    if not telegram and not vk and not need_phone:
        raise HTTPException(status_code=400, detail="Укажите хотя бы один способ связи")

    if not phone:
        phone = f"bf-{uuid.uuid4().hex[:12]}"

    phone_alt = ("+7" + phone[1:]) if phone.startswith("8") and len(phone) >= 11 else phone
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id FROM users WHERE phone = %s OR phone = %s LIMIT 1",
                (phone, phone_alt),
            )
            row = cur.fetchone()
            if row:
                user_id = row["id"]
                cur.execute(
                    "UPDATE users SET name = %s, city = %s, telegram = COALESCE(%s, telegram), vk = COALESCE(%s, vk) WHERE id = %s",
                    (name, city, telegram, vk, user_id),
                )
            else:
                temp_pass = bcrypt.hash(_bcrypt_password(os.urandom(9).hex()))
                cur.execute(
                    """
                    INSERT INTO users (name, surname, phone, city, password_hash, telegram, vk)
                    VALUES (%s, '', %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (name, phone, city, temp_pass, telegram, vk),
                )
                user_id = cur.fetchone()["id"]

            dream_ids: List[int] = []
            for i, dream_text in enumerate(dreams):
                note = ""
                if i == 0 and barriers:
                    note = "\n\n[барьеры]\n" + "\n".join(f"• {b}" for b in barriers)
                full_text = dream_text + note
                try:
                    cur.execute(
                        """
                        INSERT INTO dreams (user_id, dream, status_id, date, is_public)
                        VALUES (%s, %s, 1, CURRENT_DATE, false)
                        RETURNING id
                        """,
                        (user_id, full_text),
                    )
                except psycopg2.ProgrammingError:
                    conn.rollback()
                    cur.execute(
                        "INSERT INTO dreams (user_id, dream, date) VALUES (%s, %s, CURRENT_DATE) RETURNING id",
                        (user_id, full_text),
                    )
                dream_ids.append(cur.fetchone()["id"])
        conn.commit()
        return user_id, dream_ids
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=400, detail="Не удалось сохранить, попробуй еще раз")
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=503, detail=f"Не удалось сохранить, попробуй еще раз ({str(e)[:80]})")
    finally:
        if conn:
            _return_conn(conn)


def _handle_save(body: BreakfastChatRequest) -> BreakfastChatResponse:
    _persist_lead(body)
    return BreakfastChatResponse(ok=True)


def breakfast_chat(body: BreakfastChatRequest, request: Request) -> BreakfastChatResponse:
    _enforce_rate(request)
    if body.action == "ai":
        return _handle_ai(body)
    if body.action == "save":
        return _handle_save(body)
    raise HTTPException(status_code=400, detail="action: ai или save")
