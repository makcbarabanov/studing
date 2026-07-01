# Уведомления бадди о шагах и отчётах

Спецификация фичи **Buddy Alerts**: бадди видит в колокольчике (🔔) прогресс связанного пользователя за день.

Согласовано с Максом (2026-06-28). Phase A — только схема и документация.

---

## Поведение (продукт)

| Событие | Когда | Кому | Условие |
|---------|-------|------|---------|
| **100% шагов** | Сразу после последнего ✓ | Все активные бадди с доступом | `alert_steps_enabled` на связи; 100% = все шаги дня с ✓ (не −) |
| **Не сделал шаги** | Ежедневно в `buddy_alert_daily_at` (по умолчанию 23:00) | Те же бадди | Эффективность &lt; 100%; список пропущенных шагов в тексте |
| **Не отправил отчёт** | То же время, что digest | Те же бадди | День 100% ✓, но нет записи в `buddy_step_daily_reports`; `alert_reports_enabled` |

**Отчёт «отправлен»:** 📋 копирование **или** ✈️ share в центре отчётов (раньше только `localStorage`).

**Канал доставки v1:** только in-app 🔔 (без Telegram).

**Часовой пояс v1:** `Europe/Moscow` (константа в cron/конфиге). Колонка `users.timezone` — задел на v2.

---

## Настройки в кабинете (UI, русский)

Аккордеон **«3. Уведомления для бадди»** (Phase C):

| Строка | Смысл |
|--------|--------|
| Сообщать бадди о моих **шагах** / **отчётах** | Исходящие: subject → все активные связи |
| Получать сообщения о **шагах** / **отчётах** бадди | Входящие: viewer → все активные связи |

Слова **шагах** и **отчётах** — кликабельные переключатели:

- **Зелёный** — включено  
- **Красный** — выключено  

**Синхронизация:** одна правда на связи `user_buddy_links`. Если Макс включает «сообщать о шагах», у бадди автоматически отображается включённое «получать о шагах» (и наоборот — тот же флаг).

Глобальный переключатель в UI обновляет **все** активные связи пользователя (`status = 'active'`).

---

## Тексты в колокольчике (черновик)

| `alert_type` | Текст |
|--------------|-------|
| `steps_success_100` | `{Имя} выполнил(а) все шаги на 100% за {дата}` |
| `steps_missed` | `{Имя} не выполнил(а): 1. … 2. …` |
| `report_not_sent` | `{Имя} не отправил(а) отчёт за {дата} (шаги — 100%)` |

---

## Схема БД

Миграция: `_sql/mig_buddy_alerts.sql`.

| Объект | Назначение |
|--------|------------|
| `user_buddy_links.alert_steps_enabled` | Шаги: subject разрешает viewer уведомления |
| `user_buddy_links.alert_reports_enabled` | Отчёты: то же |
| `users.buddy_alert_daily_at` | Время digest (TIME, default 23:00) |
| `users.timezone` | IANA TZ (v2; NULL = Moscow) |
| `buddy_step_daily_reports` | Факт отправки отчёта за день |
| `buddy_alert_notifications` | Записи для 🔔 |
| `buddy_daily_digest_runs` | Идемпотентность cron (не слать дважды) |

Подробные колонки — [tables.md](tables.md) §7a, §9.2–9.4.

### Примеры `payload` (JSONB)

```json
{"efficiency_pct": 100, "completed": 7, "total": 7, "subject_name": "Макс"}
```

```json
{"efficiency_pct": 57, "completed": 4, "total": 7, "missed_steps": [
  {"step_id": 101, "title": "Зарядка"},
  {"step_id": 102, "title": "Чтение"}
], "subject_name": "Макс"}
```

---

## SRE: ежедневный digest (без HTTP)

> **Критично:** не создавать `POST /internal/buddy-daily-digest` в `main.py`.  
> Внутренний HTTP-endpoint для cron — риск безопасности (обход auth, лишняя attack surface).

### Как запускать

Скрипт **`scripts/run_buddy_daily_digest.py`** (Phase B):

1. Запускается **на хосте ОС** (systemd timer / cron), **не** через uvicorn.
2. Подключается к PostgreSQL **напрямую** через переменные окружения (те же, что у приложения):

   `DB_HOST`, `DB_USER`, `DB_PASS`, `DB_NAME`, `DB_PORT`

3. Читает `.env` из корня проекта (как `run_migrate.py`).
4. В транзакции для каждого subject с шагами за «сегодня» (дата в `Europe/Moscow`):
   - считает эффективность (только ✓);
   - при &lt; 100% → `steps_missed` + запись в `buddy_daily_digest_runs`;
   - при 100% без отчёта → `report_not_sent` + digest run;
   - вставляет строки в `buddy_alert_notifications` для viewers с включёнными флагами;
   - `UNIQUE` на notifications и digest_runs защищает от дублей при повторном запуске.

### Пример cron (prod, Moscow)

```cron
# Каждый час — скрипт сам проверяет, у кого наступило buddy_alert_daily_at
0 * * * * cd /home/makc/Apps/island && /home/makc/Apps/island/venv/bin/python scripts/run_buddy_daily_digest.py >> logs/buddy_digest.log 2>&1
```

Альтернатива: один запуск в 23:05 MSK, если все пользователи на default 23:00.

### Мгновенный alert 100%

Создаётся в **`main.py`** при `PATCH /dreams/{id}/steps/{step_id}` (Phase B) — в рамках обычного API, без отдельного cron.

---

## API (Phase B — план, без internal route)

| Method | Path | Назначение |
|--------|------|------------|
| GET | `/users/me/buddy-alert-settings?user_id=` | Настройки для кабинета |
| PATCH | `/users/me/buddy-alert-settings?user_id=` | Обновить toggles + время |
| POST | `/users/me/daily-report-sent?user_id=` | `{ report_date, send_method }` |
| GET | `/users/me/buddy-alerts/unread-count?user_id=` | Счётчик для 🔔 |
| PATCH | `/users/me/buddy-alerts/{id}/read?user_id=` | Прочитано |
| PATCH | `/dreams/{id}/steps/{step_id}` | *(modify)* fan-out `steps_success_100` |
| GET | `/dreams/notifications?user_id=` | *(modify)* merge buddy alerts |
| GET | `/dreams/showcase/counts?user_id=` | *(modify)* поле `buddy_alerts_unread` |

**Не делать:** `POST /internal/buddy-daily-digest` — digest только `scripts/run_buddy_daily_digest.py` → PostgreSQL.

---

## Статус внедрения

| Phase | Статус |
|-------|--------|
| A — schema + docs | ✅ |
| B — API + cron script | ✅ (`buddy_alerts_core.py`, `main.py`, `scripts/run_buddy_daily_digest.py`) |
| C — UI (кабинет, 🔔) | ✅ |
| D — RUNBOOK cron | ✅ (см. [RUNBOOK.md](RUNBOOK.md) § Buddy digest) |

Применение миграции на песке:

```bash
python run_migrate.py _sql/mig_buddy_alerts.sql
```

---

## Связанные документы

- [tables.md](tables.md) — DDL-справочник  
- [migrations_applied.md](migrations_applied.md) — журнал миграций  
- [UI-standards.md](UI-standards.md) — центр отчётов, эффективность vs «день закрыт»  
- [business_logic.md](business_logic.md) — шаги и дневник  
