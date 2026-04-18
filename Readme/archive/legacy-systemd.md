# Архив: systemd и наследие (до унификации на Docker)

**Актуальный пульт продакшена:** [RUNBOOK.md](../RUNBOOK.md). Прод на **188.225.44.48** переведён на **Docker Compose**; прежний `island.service` отключён.

Ниже сохранён снимок отчёта Atlas (2026-03-14) и связанные материалы для исторического контекста.

---

# Status Report для ATLAS — Production (ОСТРОВ)

**Сервер:** island (188.225.44.48, islanddream.ru)  
**Дата сбора данных:** 2026-03-14 (по выводу команд на сервере)

---

## 1. Systemd Unit: island.service

- **Файл:** `/etc/systemd/system/island.service`
- **Состояние:** загружен (LoadState=loaded), в автозагрузке.

**Текущее содержимое (на сервере):**

```ini
[Unit]
Description=ОСТРОВ — uvicorn (main:app)
After=network.target

[Service]
Type=simple
User=makc
Group=makc
WorkingDirectory=/home/makc/Apps/island
Environment=PATH=/home/makc/Apps/island/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/home/makc/Apps/island/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**Проблема:** `--host 0.0.0.0` — Uvicorn слушает все интерфейсы; порт 8000 доступен снаружи в обход Nginx. Подтверждено: `ss -tulpn | grep 8000` → `0.0.0.0:8000`.

**Рекомендация:** заменить на `--host 127.0.0.1` (команды — в конце отчёта).

---

## 2. Nginx Config

- **Конфиг:** `/etc/nginx/sites-available/island`
- **Включён:** симлинк в `sites-enabled/island` → `sites-available/island`.

**Содержимое (актуальное на сервере):**

- **server_name:** 188.225.44.48, islanddream.ru, www.islanddream.ru
- **location /** → `proxy_pass http://127.0.0.1:8000`; заголовки Host, X-Real-IP, X-Forwarded-For, X-Forwarded-Proto — настроены.
- **location /media/** → `alias /home/makc/Apps/island/media/`
- **listen 443 ssl** — сертификаты Let's Encrypt (Certbot):  
  `ssl_certificate` / `ssl_certificate_key` — `/etc/letsencrypt/live/islanddream.ru/`  
  Подключены `options-ssl-nginx.conf` и `ssl-dhparams.pem`.
- Отдельный **server** на порту 80: редирект HTTP → HTTPS (301) для islanddream.ru и www.islanddream.ru; для остального return 404.

Итог: Nginx корректен, весь трафик к приложению идёт через proxy на 127.0.0.1:8000. После смены binding Uvicorn на 127.0.0.1 доступ извне на :8000 исчезнет.

---

## 3. SSL / HTTPS

- **Инструмент:** Certbot 2.9.0 (`/usr/bin/certbot`).
- **Сертификат:** Let's Encrypt для islanddream.ru; конфиг продления: `/etc/letsencrypt/renewal/islanddream.ru.conf`.
- **Автопродление:**
  - **systemd:** таймер `certbot.timer` (активен, следующий запуск по расписанию).
  - **cron:** fallback в `/etc/cron.d/certbot` (каждые 12 часов при отсутствии systemd).

Настройка продления в порядке.

---

## 4. Слушающий порт 8000 (до правки)

```
tcp   LISTEN 0  2048  0.0.0.0:8000  0.0.0.0:*   users:(("uvicorn",pid=20080,fd=7))
```

Подтверждено: Uvicorn слушает **0.0.0.0:8000** — порт доступен снаружи. После смены на 127.0.0.1 ожидаем строку с `127.0.0.1:8000`.

---

## 5. Environment (секреты)

- **Файл:** `/home/makc/Apps/island/.env` — существует, приложение читает переменные через `load_dotenv()` в main.py (WorkingDirectory=/home/makc/Apps/island). В unit-файле секреты не прописаны, только `Environment=PATH=...`.
- **Права на .env:** `-rw-rw-r--` (664), владелец makc:makc. Пользователи из группы `makc` могут читать файл.

**Рекомендация (по возможности):** ограничить доступ: `chmod 600 /home/makc/Apps/island/.env`, чтобы читать мог только владелец.

---

## 6. Команды для Security Hardening (binding 127.0.0.1)

Выполнить на сервере под пользователем с sudo:

```bash
# 1. Заменить 0.0.0.0 на 127.0.0.1 в island.service
sudo sed -i 's/--host 0\.0\.0\.0/--host 127.0.0.1/' /etc/systemd/system/island.service

# 2. Проверить правку
grep ExecStart /etc/systemd/system/island.service
# Ожидается: ... --host 127.0.0.1 --port 8000

# 3. Применить и перезапустить службу
sudo systemctl daemon-reload
sudo systemctl restart island

# 4. Проверить статус и привязку порта
sudo systemctl status island
ss -tulpn | grep 8000
# Ожидается: 127.0.0.1:8000 (не 0.0.0.0)
```

Опционально (ужесточение прав на .env):

```bash
chmod 600 /home/makc/Apps/island/.env
```

---

**После выполнения команд** доступ к приложению возможен только через Nginx (80/443); прямой доступ на порт 8000 снаружи исключён.

---

## Выполнено (2026-03-14)

- В `/etc/systemd/system/island.service` заменён `--host 0.0.0.0` на `--host 127.0.0.1`.
- Выполнены `systemctl daemon-reload` и `systemctl restart island`.
- Права на `/home/makc/Apps/island/.env` ужесточены: `chmod 600`.

Проверено: `ss` → **127.0.0.1:8000**; `systemctl status island` → active (running). Кухонное окно закрыто.
