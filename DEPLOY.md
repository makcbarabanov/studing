# Деплой на продакшен

Что копировать: main.py, index.html, requirements.txt, каталоги media/ и examples/. На сервере создать .env (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, SECRET_KEY, при облачной БД — DB_SSLMODE=require).

Сервер: Python 3.10+, venv, pip install -r requirements.txt. Запуск: uvicorn main:app --host 127.0.0.1 --port 8000. Nginx на порту 80: proxy_pass http://127.0.0.1:8000; location /media/ — alias на каталог media/.

Главная страница — index.html (дизайн бывшего index2). Особые правила шагов (книги, финансы) отключены: в index.html переменная ENABLE_SPECIAL_STEPS_BOOKS_FINANCE = false; чтобы включить — поставить true.

## Nginx: загрузка аватара и раздача media

Чтобы загрузка аватара (до 2 МБ) не давала 413, в блок server добавь client_max_body_size. Чтобы аватары отдавались без 403, nginx должен иметь право читать каталог media (часто nginx работает от www-data).

Пример блока server (в /etc/nginx/sites-available/island):

    server {
        listen 80;
        server_name 188.225.44.48;
        client_max_body_size 5M;
        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
        location /media/ {
            alias /home/makc/app/media/;
        }
    }

После правки: sudo nginx -t && sudo systemctl reload nginx.

Права на сервере, чтобы nginx (www-data) мог читать аватары:

    chmod 755 /home/makc /home/makc/app /home/makc/app/media /home/makc/app/media/avatars
    chmod 644 /home/makc/app/media/avatars/* 2>/dev/null || true

## Лендинг Bridge: `/landing`

Статика в каталоге `landing/` (репозиторий). После `git pull` перезапусти сервис приложения. Доступ: `https://www.islanddream.ru/landing/` (без слэша редирект на со слэшем).

- **Форма «Творец»:** на Python-хостинге PHP не выполняется. Задай URL веб-приложения Google Apps Script в `landing/index.html` (перед `</body>`), например:
  `<script>window.ISLAND_GOOGLE_APPS_SCRIPT_URL = 'https://script.google.com/macros/s/.../exec';</script>`
  Либо Formspree / свой webhook — см. комментарии в `index.html`.
- В архиве видео было `scrieen1.mp4`, в разметке — `screen1.mp4`; при копировании файл переименован в `screen1.mp4`.
- Папка `landing/` с `screen1.mp4` (~10 МБ): при необходимости используй Git LFS или выноси тяжёлые файлы на CDN.

Nginx менять не нужно: всё идёт в `proxy_pass` на uvicorn.

## Безопасность (Production)

- **Uvicorn** должен слушать только **127.0.0.1:8000**, чтобы трафик шёл только через Nginx (proxy). На проде используется **island.service** (см. [Readme/Contex.md](Readme/Contex.md)). В репо — `island.service` с `--host 127.0.0.1`. На сервере после правки: `sudo systemctl daemon-reload && sudo systemctl restart island`.
- **Секреты:** приложение читает переменные из `.env` в рабочем каталоге (`load_dotenv()` в main.py). Файл `.env` не должен быть в репозитории; на сервере: `chmod 600 /home/makc/app/.env`.
- **SSL:** для islanddream.ru типично Certbot (Let's Encrypt) + автопродление (cron или systemd timer). Конфиг Nginx — в `sites-available` с `listen 443 ssl` и путями к сертификатам.
