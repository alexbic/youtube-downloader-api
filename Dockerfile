FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости + Redis для встроенного кеша
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    redis-server \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаем пользователя без привилегий и нужные директории
RUN groupadd -r app && useradd -r -g app -d /app -s /usr/sbin/nologin app \
    && mkdir -p /app/downloads /app/tasks \
    && chown -R app:app /app \
    && mkdir -p /var/log/supervisor /var/run/supervisor \
    && chown -R app:app /var/log/supervisor /var/run/supervisor

# Supervisor конфиг для Redis + Gunicorn
RUN echo '[supervisord]' > /etc/supervisor/conf.d/supervisord.conf && \
    echo 'nodaemon=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'user=root' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '[program:redis]' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'user=app' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'command=redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru --save ""' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autostart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autorestart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'stdout_logfile=/dev/stdout' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'stdout_logfile_maxbytes=0' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'stderr_logfile=/dev/stderr' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'stderr_logfile_maxbytes=0' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo '[program:gunicorn]' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'user=app' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'command=gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 600 app:app' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'directory=/app' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autostart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'autorestart=true' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'stdout_logfile=/dev/stdout' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'stdout_logfile_maxbytes=0' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'stderr_logfile=/dev/stderr' >> /etc/supervisor/conf.d/supervisord.conf && \
    echo 'stderr_logfile_maxbytes=0' >> /etc/supervisor/conf.d/supervisord.conf

EXPOSE 5000

# Entrypoint: fix permissions on mounted volumes, then start supervisor
USER root
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
ENTRYPOINT ["/docker-entrypoint.sh"]
