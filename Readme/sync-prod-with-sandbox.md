# Приведение прода к виду песка (одна версия через GitHub)

**Цель:** прод показывал тот же интерфейс, что и песок (мечты | шаги | витрина в шапке, без блока «1/12 сбылось» и «Витрина мечт (N)» в хедере на странице мечт). Песок — источник правды.

---

## Шаг 1. Песок (локально): всё в GitHub

На своём компе, в каталоге проекта (песок):

```bash
cd /home/makc/Apps/island   # или где у тебя проект
git status
git diff --stat     # посмотреть, что изменено
```

Если есть незакоммиченные правки — добавь нужные файлы (код и доки; дампы БД и логи лучше не коммитить):

```bash
git add index.html index2.html main.py requirements.txt DEPLOY.md ostrov.service
git add Readme/server-prompt.md Readme/sync-prod-with-sandbox.md Readme/structure.md
git status   # проверь список
git commit -m "Актуальный интерфейс: мечты | шаги | витрина, бэкенд (SSL БД, bcrypt, избранные)"
git push origin main
```

(Если основная ветка называется `master` — подставь её вместо `main`.)

Проверь на GitHub в браузере: последний коммит должен содержать твой код.

---

## Шаг 2. Прод (сервер): бэкап и переключение на GitHub

Зайди на сервер по SSH.

**2.1. Бэкап текущего состояния (чтобы можно было откатиться):**

```bash
cd ~/app
git status
git branch backup-prod-$(date +%Y%m%d)   # ветка с текущим состоянием
git tag backup-prod-$(date +%Y%m%d)      # тег на тот же коммит
```

Так у тебя останутся ветка и тег с тем, что сейчас на проде. Откат: `git checkout backup-prod-YYYYMMDD`.

**2.2. Взять с GitHub ровно то, что в песке:**

```bash
git fetch origin
git checkout main
git reset --hard origin/main
```

(Если основная ветка `master`: `git checkout master` и `git reset --hard origin/master`.)

**2.3. Перезапустить приложение:**

```bash
sudo systemctl restart island
```

---

## Шаг 3. Проверка

Открой прод в браузере. Должно быть как в песке:

- В шапке: **мечты | шаги | витрина** (и ФИО, колокольчик, аватар бадди).
- На странице мечт — заголовок **«Мои мечты»**, таблица мечт, без блока «Витрина мечт (216)» и счётчиков в шапке.

Если что-то пошло не так — на сервере откат:

```bash
cd ~/app
git checkout backup-prod-YYYYMMDD   # подставь дату из тега/ветки
sudo systemctl restart island
```

---

## Дальше

Правки только в песке → `git push` → на сервере `git pull` (и при необходимости `sudo systemctl restart island`). На проде код вручную не правим.
