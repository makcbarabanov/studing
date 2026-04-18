# ОСТРОВ (The Island)

Социальная сеть для целеустремлённых людей: мечты, шаги, витрина, поддержка окружения. Стек: **FastAPI** + статический **HTML/JS/CSS**, **PostgreSQL**. Веб на проде: **Docker Compose** + **Nginx** + TLS (islanddream.ru, хост **188.225.44.48**).

---

## Как запустить и задеплоить?

Читай **[Readme/RUNBOOK.md](Readme/RUNBOOK.md)** — единый пульт: песочница с `docker-compose.dev.yml`, прод с `docker compose up -d --build`, без legacy-systemd в операционном контуре.

---

## Роли ИИ-семьи и топология

- **Forge** (Cursor) — Lead Developer в песочнице `~/Apps/island`: код, миграции, документация. Подробнее: [Readme/Forge.md](Readme/Forge.md).
- **Продагент** — только на прод-сервере (тот же репозиторий): `git pull`, Docker, проверки. Не смешивать с Forge (см. [Readme/PROJECT.md](Readme/PROJECT.md)).
- Внешний контекст семьи (Bloom и др.) — в Forge.md и bridge-контракте.

**Топология (справочно):** приложение и БД могут быть на разных хостах; переменные `DB_*` в `.env` на машине, где крутится контейнер `app`. Детали — [Readme/PROJECT.md](Readme/PROJECT.md) и RUNBOOK.

---

## Щупальца документации (`Readme/`)

| Документ | Зачем |
|----------|--------|
| **[Readme/RUNBOOK.md](Readme/RUNBOOK.md)** | Запуск, деплой, Nginx, smoke |
| **[Readme/PROJECT.md](Readme/PROJECT.md)** | Миссия, роли, правила, бэкапы, миграции |
| **[Readme/CHANGELOG.md](Readme/CHANGELOG.md)** | История изменений («что сделано») |
| **[Readme/UI-standards.md](Readme/UI-standards.md)** | UI-канон |
| **[Readme/tables.md](Readme/tables.md)** | Схема БД |
| **[Readme/rules.md](Readme/rules.md)** | Правила по типам мечт / `steps_rules` |
| **[Readme/structure.md](Readme/structure.md)** | ЛК, вёрстка, логика экранов |

Дополнительно: `migrations_applied.md`, `help_flow_spec.md`, `steps-editing-rfc.md`, `delete_users.md`, `archive-special-rules.md`, `Forge.md`. Архив наследия: **[Readme/archive/](Readme/archive/)**.

---

*Счётчик сборки в UI: элемент `.app-version` в `index.html`.*
