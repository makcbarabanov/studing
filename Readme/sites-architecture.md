# Архитектура подсайтов Острова

## Целевая модель (канон)

```
web-app/                          ← репозиторий island (git)
├── main.py                       ← FastAPI, mount /breakfast/, /landing/
├── sites/
│   ├── breakfast/                ← islanddream.ru/breakfast/
│   └── landing/                  ← islanddream.ru/landing/
```

Папка **`sites/`** внутри репозитория = **внутренние подсайты проекта Остров**, не клиентские сайты.

## Три разных «sites» — не путать

| Путь | Назначение |
|------|------------|
| `web-app/sites/` (в git) | Подсайты Острова: breakfast, landing |
| `/home/makc/Apps/sites/` (прод, legacy) | **Устарело.** Был rsync breakfast; Docker больше не использует |
| `Projects/sites/` (вне git) | Клиентские сайты (proftour78, codex, bk…) |

## Как отдаётся контент

| URL | Каталог в git | Кто отдаёт |
|-----|---------------|------------|
| `/breakfast/` | `sites/breakfast/` | FastAPI `StaticFiles` + volume в Docker |
| `/landing/` | `sites/landing/` | FastAPI `StaticFiles` + volume в Docker |

## Деплой (актуально)

1. **Forge (песок):** правки в `web-app/sites/…` → commit → push `main`
2. **Продагент:** `git pull --ff-only origin main` → `docker compose up -d --build`

**Не использовать:** rsync в `/home/makc/Apps/sites/breakfast/` — legacy, дубликат.

## Legacy на проде

`/home/makc/Apps/sites/breakfast` — копия вне git, **не используется** при текущем Docker (volume из `island/sites/breakfast`). Можно удалить после бэкапа — только по команде Макса `[ПРОД]`.

## Монорепо OSTROV (ноут)

На ноуте также есть `OSTROV/sites/breakfast/` — зеркало/рабочая копия для разработки лендингов. **Канон для деплоя:** `OSTROV/web-app/sites/`.
