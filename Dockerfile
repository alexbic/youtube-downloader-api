FROM python:3.11-slim

WORKDIR /app

# ===== LAYER 1: System dependencies =====
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    git \
    ffmpeg \
    redis-server \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# ===== LAYER 1.5: Deno (yt-dlp signature solving) =====
RUN curl -fsSL https://deno.land/install.sh | sh \
    && ln -s /root/.deno/bin/deno /usr/local/bin/deno

# ===== LAYER 1.6: Node.js (bgutil PO Token provider) =====
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# ===== LAYER 1.7: bgutil PO Token provider (YouTube SABR bypass) =====
RUN git clone --depth 1 --branch 1.3.1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
    && cd /opt/bgutil/server \
    && npm install \
    && npx tsc \
    && echo "bgutil PO Token provider installed"

# ===== LAYER 2: Python dependencies =====
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ===== LAYER 3: Directories =====
RUN mkdir -p /app/tasks /var/log/supervisor /var/run/supervisor

# ===== LAYER 4: Supervisor config =====
RUN mkdir -p /etc/supervisor/conf.d && \
    printf '[supervisord]\n' > /etc/supervisor/conf.d/supervisord.conf && \
    printf 'nodaemon=true\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'silent=true\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'loglevel=error\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'user=root\n\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf '[program:bgutil]\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'command=/app/start-bgutil.sh\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'autostart=true\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'autorestart=true\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'priority=5\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'stdout_logfile=/dev/stdout\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'stdout_logfile_maxbytes=0\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'redirect_stderr=true\n\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf '[program:redis]\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'command=/app/start-redis.sh\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'autostart=true\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'autorestart=false\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'priority=10\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'stdout_logfile=/dev/stdout\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'stdout_logfile_maxbytes=0\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'redirect_stderr=true\n\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf '[program:orchestrator]\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'command=python /app/orchestrator.py\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'directory=/app\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'autostart=true\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'autorestart=true\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'priority=20\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'stdout_logfile=/dev/stdout\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'stdout_logfile_maxbytes=0\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'redirect_stderr=true\n\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf '[program:gunicorn]\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'command=/app/start-gunicorn.sh\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'directory=/app\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'autostart=true\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'autorestart=true\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'priority=40\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'stdout_logfile=/dev/stdout\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'stdout_logfile_maxbytes=0\n' >> /etc/supervisor/conf.d/supervisord.conf && \
    printf 'redirect_stderr=true\n' >> /etc/supervisor/conf.d/supervisord.conf

# ===== LAYER 5: Application code (changes often) =====
COPY app.py .
COPY api_commons.py .
COPY task_sync.py .
COPY bootstrap.py .
COPY gunicorn_config.py .
COPY orchestrator.py .
COPY start-bgutil.sh .
COPY start-redis.sh .
COPY start-gunicorn.sh .
RUN chmod +x start-bgutil.sh start-redis.sh start-gunicorn.sh

EXPOSE 5000

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
