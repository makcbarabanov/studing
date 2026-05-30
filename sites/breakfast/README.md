# Завтрак, исполняющий желания

Лендинг и интерактивный диалог с **Светланой (Света)** — AI-ведущей проекта «Завтрак, исполняющий желания» в экосистеме [Остров](https://islanddream.ru).

Пользователь бережно формулирует мечты, осознаёт барьеры и оставляет контакт — команда получает готовый лид для дальнейшей работы.

**Прод:** https://islanddream.ru/breakfast/

---

## Описание

Веб-приложение на базе AI-агента Светланы. Проект помогает пользователям:

- сформулировать одну или несколько мечт в живом диалоге;
- пройти через этап осознания барьеров и нужных ресурсов;
- оставить контакт для связи с «творцом мечты».

Тон общения задаётся промптом [`prompts/sveta.md`](prompts/sveta.md) (редактирует **Морфеус**). Техническая реализация — зона **Forge** (`web-app` + этот лендинг).

---

## Архитектура

Проект разделён на две части:

| Часть | Путь | Назначение |
|-------|------|------------|
| **Фронт** | `sites/breakfast/` | Статика: лендинг, UI state machine, форма |
| **Бэкенд** | `web-app/breakfast_sveta.py` | Gemini, сохранение лида, JSONL-логи |

FastAPI монтирует лендинг на `/breakfast/` и отдаёт API:

- `POST /api/v1/funnel/breakfast/chat` — ответы Светы и финальное сохранение
- `POST /api/v1/funnel/breakfast/log` — события с фронта (сообщения, кнопки, state)

На проде статика лежит в `/home/makc/Apps/sites/breakfast/` и подключается в Docker volume.

---

## Сценарий (State Machine)

Логика диалога — в [`js/sveta-fsm.js`](js/sveta-fsm.js). Состояния **1–5** — inline-чат на лендинге, **6–7** — модалка поверх страницы.

| State | Название | Что происходит |
|-------|----------|----------------|
| 1 | Greeting | Света здоровается, просит имя |
| 2 | Dreams | Сбор мечт (текстом) |
| 3 | Reaction 1 | AI-реакция на мечты; кнопки «Добавить ещё» / «Идём дальше» |
| 4 | Barriers | AI спрашивает про барьеры и ресурсы |
| 5 | Reaction 2 | AI-реакция на барьеры; кнопки «Добавить комментарий» / «Дальше» |
| 6 | Form | Модалка: имя, город, телефон, **один** канал связи (переключатель) |
| 7 | Success | Благодарность, закрытие модалки |

Кнопки ведут сценарий; Света **не дублирует** в тексте вопросы, которые уже есть на кнопках (см. промпт).

---

## Функциональность

- **Интерактивный диалог** с ИИ (Gemini; при недоступности — русская заглушка, чат не ломается).
- **State Machine** на фронте — предсказуемый UX, независимо от задержек AI.
- **Аватар Светы** — короткие видео (`hello` / `listen` / `clap`) в блоке чата.
- **Форма State 6** — переключатель каналов (Telegram, Макс, VK, WhatsApp, Email): только один активен; зелёная галочка при валидном вводе; телефон обязателен для WhatsApp и для Telegram/Макс с чекбоксом «Привязано к номеру».
- **JSONL-логирование** всех диалогов в `web-app/logs/chat_sessions.jsonl` (для тестов и обучения промпта).
- **Адаптивный UI** — mobile-first, тёплая типографика (Literata + Source Sans 3).

---

## Структура проекта

```
sites/breakfast/
├── index.html           # лендинг + чат + модалка формы
├── css/main.css         # стили
├── js/
│   ├── main.js          # hero-слайдер, медиа-манифест, promo-video
│   └── sveta-fsm.js     # state machine Светы (States 1–7)
├── prompts/
│   └── sveta.md         # системный промпт для Gemini (Морфеус)
├── assets/
│   ├── images/          # hero, about, примеры
│   └── video/           # promo.mp4, sveta_hello/listen/clap.mp4
├── FORGE-TASK.md        # ТЗ и открытые вопросы
└── README.md            # этот файл

web-app/                 # бэкенд (отдельный git-репозиторий)
├── breakfast_sveta.py   # AI + save + JSONL
├── main.py              # mount /breakfast/ + API routes
└── logs/
    └── chat_sessions.jsonl
```

Папку `ChatExport_*/` в git **не коммитим** — это архив экспорта чата (~1 GB), только источник медиа.

---

## Запуск локально

### Рекомендуется (лендинг + API на одном порту)

```bash
cd /home/makc/Apps/OSTROV/web-app

# В .env минимум:
# GEMINI_API_KEY=...
# DB_* — если нужно сохранение в БД (см. ниже)

pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Открыть: **http://127.0.0.1:8000/breakfast/**

### Только статика (API отдельно)

```bash
cd sites/breakfast
python3 -m http.server 8080
# фронт по умолчанию ходит на тот же origin; для :8080 задай window.ISLAND_API_BASE = 'http://127.0.0.1:8000'
```

### Docker (как на проде)

```bash
cd web-app
docker compose up --build
# volume ../sites/breakfast → /app/sites/breakfast
```

---

## Переменные окружения (web-app `.env`)

| Переменная | Назначение |
|------------|------------|
| `GEMINI_API_KEY` | Ключ Google AI (основной) |
| `GEMINI_API_KEY_2`, … | Ротация при 429/quota |
| `GEMINI_MODEL` | По умолчанию `gemini-2.0-flash` |
| `BREAKFAST_SAVE_TO_DB` | `1` — писать лиды в PostgreSQL; **по умолчанию выкл.** (только JSONL) |
| `BREAKFAST_CHAT_LOG` | Путь к JSONL (default: `web-app/logs/chat_sessions.jsonl`) |
| `BREAKFAST_AI_USE_HF` | `1` — включить Hugging Face fallback |
| `BREAKFAST_DIR` | Путь к лендингу (Docker: `/app/sites/breakfast`) |

---

## Логирование (JSONL)

Каждое событие дописывается строкой в `chat_sessions.jsonl`:

- сообщения пользователя и Светы;
- смена state (1–7);
- нажатия кнопок;
- отправка формы с контактами (телефон, соцсети).

Формат — JSON Lines: одна строка = один объект. Файл **не коммитится** в git.

**На проде:** `/home/makc/Apps/island/logs/chat_sessions.jsonl`

---

## Сборка и деплой

### Build-версия

Файл [`version.json`](version.json) — `{"version": N}`. Число видно в **футере** лендинга (`v.N`).

Перед деплоем:

```bash
cd sites/breakfast
./scripts/bump-version.sh    # N → N+1
./scripts/deploy-prod.sh     # bump + rsync на прод
```

Если на сайте `v.11`, а локально `12` — фронт на прод **не обновился**.

### Деплой состоит из двух шагов

### 1. Бэкенд (git, на сервере)

```bash
cd /home/makc/Apps/island
git pull --ff-only origin main
docker compose up -d --build
mkdir -p logs
```

### 2. Фронт (rsync с ноута)

```bash
rsync -avz sites/breakfast/js/sveta-fsm.js \
  makc@188.225.44.48:/home/makc/Apps/sites/breakfast/js/

rsync -avz sites/breakfast/css/main.css \
  makc@188.225.44.48:/home/makc/Apps/sites/breakfast/css/

rsync -avz sites/breakfast/index.html \
  makc@188.225.44.48:/home/makc/Apps/sites/breakfast/
```

После деплоя — **Ctrl+Shift+R** в браузере (кэш `?v=` у скриптов).

Подробнее: `web-app/Readme/RUNBOOK.md`.

---

## Использование (для тестировщиков)

1. Открой https://islanddream.ru/breakfast/
2. Нажми **«Записать свою мечту»** или прокрути до блока чата.
3. Представься, напиши мечту(ы) — Света ответит (или шаблоном, если Gemini недоступен).
4. Используй кнопки «Добавить ещё» / «Идём дальше» / «Дальше» — они ведут сценарий.
5. В **State 6** заполни имя, город, выбери **один** канал связи, отправь форму.
6. Увидишь экран благодарности — готово.

---

## Медиа

| Слот | Файл | Примечание |
|------|------|------------|
| Hero | `assets/images/hero.jpg` | Фон первого экрана |
| О проекте | `assets/images/about.jpg` | Блок «О завтраке» |
| Примеры | `example-1.jpg` … `example-3.jpg` | Карточки историй |
| Промо | `assets/video/promo.mp4` | Видео в блоке «О проекте» |
| Аватар | `sveta_hello/listen/clap.mp4` | Отдельно от promo; не путать пути |

Имена слотов — в `MEDIA_MANIFEST` в [`js/main.js`](js/main.js).

---

## Роли в команде

| Кто | Зона |
|-----|------|
| **Макс (PO)** | продукт, приоритеты, тесты |
| **Морфеус** | промпт `prompts/sveta.md`, тон Светы |
| **Forge** | код лендинга + `breakfast_sveta.py` |
| **CRONOS** | прод, Docker, Nginx |

---

## Связанные документы

- `FORGE-TASK.md` — ТЗ, открытые вопросы по воронке
- `web-app/Readme/RUNBOOK.md` — деплой и smoke-check
- `../CONTEXT.md` (корень OSTROV) — handoff между сессиями Cursor

---

## Открытые задачи

- Включить живой Gemini на проде (сейчас возможен fallback при исчерпании квоты API).
- Решить, когда включать `BREAKFAST_SAVE_TO_DB=1` для записи лидов в PostgreSQL.
- Дописать контракт funnel в `island-bridge-contract/api.md` при стабилизации API.
