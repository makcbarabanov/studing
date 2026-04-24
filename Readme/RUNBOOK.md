# RUNBOOK — запуск и деплой (ОСТРОВ)

Единый операционный документ: **локальная песочница** и **прод** работают через **Docker Compose**. Прод на **188.225.44.48** (islanddream.ru) — контейнер `app` за Nginx; старый `island.service` не используется.

**Связанные файлы:** [docker-compose.yml](../docker-compose.yml), [docker-compose.dev.yml](../docker-compose.dev.yml), [Dockerfile](../Dockerfile). Секреты и `DB_*` — только в **`.env`** (не коммитить).

---

## Принципы безопасного релиза

- **Git** переносит только **код и документацию**. Данные БД песка и прода **не** синхронизируются через `git pull`.
- Релизы на прод — только проверенные коммиты (префикс `prod:` по согласованию с владельцем репозитория).
- Синхронизация **данных** БД (песок ↔ прод) — только **отдельными дампами** и явной процедурой с бэкапом.

---

## Локальная песочница (Forge)

Не коммить `.env`.

### 1. Проверь `DB_HOST` в `.env`

| Условие | Команда запуска |
|--------|------------------|
| `DB_HOST=db` | Нужен локальный Postgres в Compose: **оба** файла compose. |
| `DB_HOST` — внешний хост (не `db`) | Только базовый compose **без** `docker-compose.dev.yml`. |

### 2. Запуск с локальной БД в Docker (типичный песок)

```bash
cd ~/Apps/island
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build --remove-orphans
```

### 3. Только приложение в Docker, БД снаружи

```bash
docker compose up --build
```

### 4. Smoke-check после старта

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8000/dreams?user_id=1"
```

Ожидаемо: контейнер `db` = `healthy` (если используется dev-файл), `GET /dreams` = `200`.

### 5. Миграции и схема

- SQL в **`_sql/`** — в репозитории; применение:  
  `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python3 run_migrate.py _sql/имя_файла.sql`
- После `pg_restore` многострочные миграции иногда удобнее через `psql` в контейнере `db` (см. п. 105 в [CHANGELOG.md](CHANGELOG.md)).
- Первичная схема: `init.sql`, дамп из `db_backups/*.dump`, затем миграции — по ситуации ([PROJECT.md](PROJECT.md)).

### 6. Запрос агенту в чате (шаблон)

«Подними сервер по RUNBOOK: проверь `DB_HOST` в `.env`, выбери правильный compose (с dev-файлом или без), после старта проверь `/dreams` и дай статус».

---

## Прод (Продагент), Docker

Каталог на сервере: **`/home/makc/Apps/island`**. В команде **не** должно быть `-f docker-compose.dev.yml`.

### Перед обновлением

```bash
cd /home/makc/Apps/island
git status
git rev-parse --short HEAD
git fetch origin
git log --oneline HEAD..origin/main
```

Если рабочее дерево не чистое — `git stash push -u -m "pre-deploy-$(date +%F)"`, затем деплой.

### Обновление кода и перезапуск стека

```bash
git pull --ff-only origin main
docker compose up -d --build
```

### Smoke-check

```bash
curl -sk https://islanddream.ru/index.html | grep -o '<span class="app-version"[^>]*>[0-9]*</span>' | head -1
```

Проверить вручную: логин, мечты, шаги, аватар.

### Откат (если что-то пошло не так)

```bash
cd /home/makc/Apps/island
git reflog -10
git reset --hard <предыдущий_коммит>
docker compose up -d --build
```

### Чеклист роли Продагента

1. Сверить diff `HEAD` и `origin/main`.
2. Убедиться, что релиз согласован (`prod-safe`).
3. `git pull --ff-only` и `docker compose up -d --build`.
4. Smoke-check и отчёт.

Продагент **не** правит код на сервере вручную и не смешивает песочные и продовые конфиги.

### Два окна Cursor (чтобы не отправить задачу «не тому»)

Оба окна видят **один репозиторий** — Cursor **не знает** сам, Forge ты или Продагент.

- В **прод-окне:** включи правило **`.cursor/rules/island-prodagent-readonly.mdc`** и начинай сообщения с тега **`[ПРОД]`** (первая строка). Тогда агент не будет менять код без переспроса «МАКС, ЭТО ПРОД! …» и ответа **`ДА ПРОД`**.
- В **окне Forge:** это правило **не** включай, тег **`[ПРОД]`** не пиши.

Подробнее: **[AGENTS.md](../AGENTS.md)** в корне репозитория.

---

## Nginx и TLS (на хосте сервера)

Трафик снаружи идёт через **Nginx** → `proxy_pass` на приложение (контейнер слушает на хосте, например `127.0.0.1:8000`). Конфиг обычно в `/etc/nginx/sites-available/island`.

### Загрузка аватара (лимит тела запроса)

В приложении лимит аватара до **20 МБ**; в Nginx задай **`client_max_body_size`** не меньше (например **`25m`**), иначе возможна ошибка **413**.

### Раздача `media/`

```nginx
location /media/ {
    alias /home/makc/Apps/island/media/;
}
```

Права на каталоги для чтения процессом nginx (часто `www-data`):

```bash
chmod 755 /home/makc /home/makc/Apps/island /home/makc/Apps/island/media /home/makc/Apps/island/media/avatars
chmod 644 /home/makc/Apps/island/media/avatars/* 2>/dev/null || true
```

После правок конфига: `sudo nginx -t && sudo systemctl reload nginx`.

### HTTPS

Для islanddream.ru — типично **Certbot** (Let's Encrypt), конфиг в `sites-available` с `listen 443 ssl`. Секреты приложения — в **`.env`** на сервере (`chmod 600`).

### Лендинг Bridge: `/landing`

Статика в каталоге `landing/`. Публичный URL вида `https://www.islanddream.ru/landing/`. Форма «Творец» может использовать Google Apps Script URL в `landing/index.html` (см. комментарии в файле).

---

## Синхронизация данных БД (отдельно от кода)

1. Продагент: при необходимости свежий dump на проде.  
2. Перенос дампа в песочницу.  
3. Forge: restore в Docker-БД песка.  
4. Проверка пользователей / мечт / аватаров.

### Политика хранения бэкапов (порядок в репозитории)

- Активные дампы хранить **вне репозитория**: `~/Backups/island`.
- Именование источника обязательно: `prod_<db>_YYYYMMDD_HHMMSS.dump` или `sandbox_<db>_YYYYMMDD_HHMMSS.dump`.
- В git хранить только скрипты и документацию; сами `.dump` и папки `db_backups*` не коммитить.
- Недельный чек: есть свежий дамп и тестовый `pg_restore` проходит в песочнице.
- Скрипт `db_backups/bu_db.sh` поддерживает переменные:
  - `BACKUP_DIR` (по умолчанию `~/Backups/island`)
  - `BACKUP_SOURCE` (`prod`/`sandbox`, по умолчанию `prod`)
  - `PG_HOST`, `PG_USER`, `PG_DB`, `PGPASSWORD`

---

## Архив

Исторические инструкции (в т.ч. старый **systemd** и копии прежних `DEPLOY` / `sync-prod-with-sandbox`): [Readme/archive/](archive/).
