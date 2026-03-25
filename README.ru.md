# YouTube Downloader API

REST API для скачивания видео с YouTube на основе yt-dlp, упакованный в standalone Docker-контейнер.

[![Docker Hub](https://img.shields.io/docker/v/alexbic/youtube-downloader-api?label=Docker%20Hub&logo=docker)](https://hub.docker.com/r/alexbic/youtube-downloader-api)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-2.0.0-blue)](docs/CHANGELOG.md)

[English](README.md) | **Русский**

---

## Возможности

- ⬇️ **Асинхронные загрузки** — отправь задачу, опрашивай статус, скачай файл
- 🔗 **Webhook уведомления** — POST-колбэк при завершении с автоматическими повторами
- 🔄 **Восстановление задач** — прерванные задачи повторно ставятся в очередь при перезапуске
- 🛡️ **bgutil PO Token** — обход YouTube SABR ограничений (требуется с 2024 года)
- 🔑 **Опциональная Bearer-аутентификация** — защита эндпоинтов API-ключом
- 🧹 **Автоочистка** — файлы удаляются через 24 часа
- 🐳 **Standalone контейнер** — Redis, bgutil, оркестратор и gunicorn в одном образе

---

## Быстрый старт

```bash
docker pull alexbic/youtube-downloader-api:latest
docker run -d -p 5000:5000 \
  -e SERVER_BASE_URL=http://localhost:5000 \
  --name ytdl alexbic/youtube-downloader-api:latest
```

**Проверка:**
```bash
curl http://localhost:5000/health
```

**Скачать видео:**
```bash
# Отправить задачу
curl -X POST http://localhost:5000/download_video \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# {"task_id": "abc123...", "status": "queued", ...}

# Проверить статус
curl http://localhost:5000/task_status/abc123...

# Скачать файл после завершения
curl -O -J "http://localhost:5000/download/abc123.../filename.webm"
```

---

## Docker Compose

```yaml
version: '3.8'
services:
  youtube-downloader:
    image: alexbic/youtube-downloader-api:latest
    ports:
      - "5000:5000"
    volumes:
      - ./tasks:/app/tasks
    environment:
      SERVER_BASE_URL: ${SERVER_BASE_URL:-http://localhost:5000}
      API_KEY: ${API_KEY:-}
    restart: unless-stopped
```

---

## API

### GET /health

```json
{
  "status": "ok",
  "redis": "ok",
  "active_tasks": 0,
  "queued_tasks": 0,
  "max_concurrent_tasks": 2,
  "worker_id": "worker-12",
  "timestamp": "2026-01-01T12:00:00Z"
}
```

---

### POST /download_video

**Запрос:**
```json
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "format": "bestvideo+bestaudio/best",
  "max_size_mb": 2048,
  "webhook_url": "https://your-server.com/webhook",
  "webhook_headers": {"Authorization": "Bearer secret"},
  "client_meta": {"user_id": 123}
}
```

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| `url` | string | ✅ | YouTube URL. Поддерживается только YouTube — любой другой домен возвращает `400 INVALID_URL` |
| `format` | string | — | yt-dlp format string (по умолчанию: лучшее в пределах лимита) |
| `max_size_mb` | int | — | Макс. размер файла в МБ (по умолчанию: 2048) |
| `webhook_url` | string | — | URL для POST-колбэка при завершении |
| `webhook_headers` | object | — | Заголовки для webhook-запроса |
| `client_meta` | object | — | Произвольный JSON, пробрасываемый в webhook/статус |

**Ответ `202`:**
```json
{
  "task_id": "b0b8d187-...",
  "status": "queued",
  "created_at": "2026-01-01T12:00:00"
}
```

**Ответ `400` — не YouTube URL:**
```json
{
  "error": {
    "code": "INVALID_URL",
    "message": "Only YouTube URLs are supported"
  }
}
```

---

### GET /task_status/\<task_id\>

**Ответ (processing):**
```json
{
  "task_id": "b0b8d187-...",
  "status": "processing",
  "started_at": "2026-01-01T12:00:01",
  "url": "https://www.youtube.com/watch?v=..."
}
```

**Ответ (completed):**
```json
{
  "task_id": "b0b8d187-...",
  "status": "completed",
  "created_at": "2026-01-01T12:00:00",
  "completed_at": "2026-01-01T12:00:09",
  "url": "https://www.youtube.com/watch?v=...",
  "result": {
    "filename": "Video Title.webm",
    "download_url": "http://localhost:5000/download/b0b8d187-.../Video Title.webm",
    "file_size_bytes": 47448900,
    "title": "Video Title",
    "duration": 212,
    "thumbnail": "https://i.ytimg.com/...",
    "uploader": "Channel Name"
  }
}
```

**Ответ (failed):**
```json
{
  "task_id": "b0b8d187-...",
  "status": "failed",
  "failed_at": "2026-01-01T12:00:05",
  "error": {
    "code": "VIDEO_UNAVAILABLE",
    "message": "..."
  }
}
```

**Статусы:** `queued` → `processing` → `completed` / `failed`

---

### GET /download/\<task_id\>/\<filename\>

Возвращает файл как вложение. Доступен 24 часа после завершения задачи.

---

### GET /api/version

```json
{
  "service": "youtube-downloader-api",
  "version": "2.0.0",
  "supported_platforms": ["YouTube"]
}
```

Все эндпоинты доступны также с префиксом `/api/v1/`.

---

## Конфигурация

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `SERVER_BASE_URL` | `http://localhost:5000` | Базовый URL для ссылок в `download_url` |
| `API_KEY` | — | Включает Bearer-аутентификацию если задан |
| `MAX_DOWNLOAD_VIDEO_SIZE_MB` | `2048` | Макс. размер видео в МБ |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `TASKS_DIR` | `/app/tasks` | Директория хранения задач |
| `REDIS_URL` | `redis://localhost:6379/0` | URL подключения к Redis |

**Фиксированные лимиты (не настраиваются):**
- Воркеры: 2
- TTL задач: 24 часа
- Redis: встроенный, 256 МБ

---

## Аутентификация

Если задан `API_KEY`, защищённые эндпоинты требуют:
```
Authorization: Bearer <API_KEY>
```

Защищённые: `POST /download_video`
Открытые: `GET /health`, `GET /task_status/<id>`, `GET /download/<path>`, `GET /api/version`

---

## Webhook

При указании `webhook_url` POST-запрос отправляется при завершении или ошибке задачи.

**Payload (completed):**
```json
{
  "task_id": "...",
  "status": "completed",
  "result": { "..." },
  "client_meta": { "..." }
}
```

**Payload (failed):**
```json
{
  "task_id": "...",
  "status": "failed",
  "error": { "code": "...", "message": "..." },
  "client_meta": { "..." }
}
```

Доставка: 3 немедленных попытки с экспоненциальной задержкой, затем фоновый resender каждые 15 минут до истечения TTL.

---

## Архитектура

Один Docker-образ, 4 процесса под управлением Supervisor:

```
bgutil (priority 5)        — Node.js сервер PO Token (порт 4416)
redis (priority 10)        — Встроенный Redis
orchestrator (priority 20) — Восстановление, определение сбоев, webhook resender
gunicorn (priority 40)     — Flask API, 2 воркера (стартует после оркестратора)
```

---

## Решение проблем

**YouTube 403 / «Подтвердите, что вы не бот»**
- bgutil обрабатывает PO Token автоматически — для публичных видео это не должно происходить
- Проверьте bgutil: `docker logs ytdl | grep bgutil`

**Задача застряла в `processing`**
- Оркестратор обнаруживает сбои через heartbeat (таймаут 90с) и автоматически перезапускает задачу
- Смотрите логи: `docker logs ytdl`

**Файл не найден (404)**
- Файлы автоматически удаляются через 24 часа после создания задачи
- Скачивайте сразу после получения статуса `completed`

**Redis недоступен**
- Redis встроен в контейнер — перезапустите: `docker restart ytdl`

---

## Сборка локально

```bash
git clone https://github.com/alexbic/youtube-downloader-api.git
cd youtube-downloader-api
docker build -t youtube-downloader-api:local .
docker run -d -p 5000:5000 -e SERVER_BASE_URL=http://localhost:5000 youtube-downloader-api:local
```

---

## Технологии

- Python 3.11 + Flask 3.0 + Gunicorn
- yt-dlp + FFmpeg
- bgutil-ytdlp-pot-provider (Node.js + Deno)
- Redis (встроенный)
- Supervisor

---

## Лицензия

MIT — см. [LICENSE](LICENSE)

---

## Поддержка

- Issues: [GitHub Issues](https://github.com/alexbic/youtube-downloader-api/issues)
- Email: support@alexbic.net
