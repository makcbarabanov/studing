# Единый образ для песочницы и прода: зависимости + код + uvicorn (см. docker-compose.yml).
FROM python:3.11-slim

# Устанавливаем системные зависимости (если нужны для БД)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Команда запуска (поменяем, если у тебя не main.py или нужен gunicorn)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
