FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаем папку для загрузок
RUN mkdir -p /app/downloads

EXPOSE 5000

# Настройка воркеров/таймаутов через переменные окружения
# WORKERS (default: 1), GUNICORN_TIMEOUT (default: 300)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:5000 --workers ${WORKERS:-1} --timeout ${GUNICORN_TIMEOUT:-300} app:app"]
