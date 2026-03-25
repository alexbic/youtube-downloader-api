# YouTube Downloader API

REST API for downloading YouTube videos using yt-dlp, packaged as a standalone Docker container.

[![Docker Hub](https://img.shields.io/docker/v/alexbic/youtube-downloader-api?label=Docker%20Hub&logo=docker)](https://hub.docker.com/r/alexbic/youtube-downloader-api)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-2.0.0-blue)](docs/CHANGELOG.md)

**English** | [Русский](README.ru.md)

---

## Features

- ⬇️ **Async downloads** — submit a task, poll status, download the file
- 🔗 **Webhook notifications** — POST callback on completion with automatic retries
- 🔄 **Task recovery** — interrupted tasks are re-enqueued on container restart
- 🛡️ **bgutil PO Token** — bypasses YouTube SABR restrictions (required since 2024)
- 🔑 **Optional Bearer auth** — protect endpoints with an API key
- 🧹 **Auto cleanup** — files deleted after 24 hours
- 🐳 **Standalone container** — Redis, bgutil, orchestrator, gunicorn all in one image

---

## Quick Start

```bash
docker pull alexbic/youtube-downloader-api:latest
docker run -d -p 5000:5000 \
  -e SERVER_BASE_URL=http://localhost:5000 \
  --name ytdl alexbic/youtube-downloader-api:latest
```

**Health check:**
```bash
curl http://localhost:5000/health
```

**Download a video:**
```bash
# Submit task
curl -X POST http://localhost:5000/download_video \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# {"task_id": "abc123...", "status": "queued", ...}

# Poll status
curl http://localhost:5000/task_status/abc123...

# Download file when completed
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

## API Reference

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

**Request:**
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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | ✅ | YouTube URL |
| `format` | string | — | yt-dlp format string (default: best within size limit) |
| `max_size_mb` | int | — | Max file size in MB (default: 2048) |
| `webhook_url` | string | — | POST callback URL on completion |
| `webhook_headers` | object | — | Custom headers for webhook request |
| `client_meta` | object | — | Arbitrary JSON passed through to webhook/status |

**Response `202`:**
```json
{
  "task_id": "b0b8d187-...",
  "status": "queued",
  "created_at": "2026-01-01T12:00:00",
  "platform": "YouTube"
}
```

---

### GET /task_status/\<task_id\>

**Response (processing):**
```json
{
  "task_id": "b0b8d187-...",
  "status": "processing",
  "started_at": "2026-01-01T12:00:01",
  "platform": "YouTube",
  "url": "https://www.youtube.com/watch?v=..."
}
```

**Response (completed):**
```json
{
  "task_id": "b0b8d187-...",
  "status": "completed",
  "created_at": "2026-01-01T12:00:00",
  "completed_at": "2026-01-01T12:00:09",
  "platform": "YouTube",
  "url": "https://www.youtube.com/watch?v=...",
  "result": {
    "filename": "Video Title.webm",
    "download_url": "http://localhost:5000/download/b0b8d187-.../Video Title.webm",
    "file_size_bytes": 47448900,
    "title": "Video Title",
    "duration": 212,
    "thumbnail": "https://i.ytimg.com/...",
    "uploader": "Channel Name",
    "platform": "YouTube"
  }
}
```

**Response (failed):**
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

**Status values:** `queued` → `processing` → `completed` / `failed`

---

### GET /download/\<task_id\>/\<filename\>

Returns the file as an attachment. File is available for 24 hours after task completion.

---

### GET /api/version

```json
{
  "service": "youtube-downloader-api",
  "version": "2.0.0",
  "supported_platforms": ["YouTube"]
}
```

All endpoints are also available under `/api/v1/` prefix.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_BASE_URL` | `http://localhost:5000` | Base URL used in `download_url` links |
| `API_KEY` | — | Enables Bearer token auth when set |
| `MAX_DOWNLOAD_VIDEO_SIZE_MB` | `2048` | Max video size in MB |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `TASKS_DIR` | `/app/tasks` | Task storage directory |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |

**Fixed limits (not configurable):**
- Workers: 2
- Task TTL: 24 hours
- Redis: built-in, 256 MB

---

## Authentication

When `API_KEY` is set, protected endpoints require:
```
Authorization: Bearer <API_KEY>
```

Protected: `POST /download_video`
Public: `GET /health`, `GET /task_status/<id>`, `GET /download/<path>`, `GET /api/version`

---

## Webhook

When `webhook_url` is provided, a POST is sent on task completion or failure.

**Payload (completed):**
```json
{
  "task_id": "...",
  "status": "completed",
  "result": { ... },
  "client_meta": { ... }
}
```

**Payload (failed):**
```json
{
  "task_id": "...",
  "status": "failed",
  "error": { "code": "...", "message": "..." },
  "client_meta": { ... }
}
```

Delivery: 3 immediate attempts with exponential backoff, then background resender every 15 minutes until TTL expires.

---

## Architecture

Single Docker image running 4 processes via Supervisor:

```
bgutil (priority 5)        — Node.js PO Token server (port 4416)
redis (priority 10)        — Built-in Redis
orchestrator (priority 20) — Recovery, crash detection, webhook resender
gunicorn (priority 40)     — Flask API, 2 workers (starts after orchestrator)
```

Gunicorn waits for `/tmp/system-ready` written by orchestrator before accepting connections.

---

## Troubleshooting

**YouTube 403 / "Sign in to confirm you're not a bot"**
- bgutil handles PO Token automatically — this should not occur for public videos
- Check bgutil is running: `docker logs ytdl | grep bgutil`

**Task stuck in `processing`**
- Orchestrator detects crashes via heartbeat (90s timeout) and re-enqueues automatically
- Check logs: `docker logs ytdl`

**File not found (404)**
- Files are auto-deleted 24 hours after task creation
- Download immediately after status becomes `completed`

**Redis unavailable**
- Redis is embedded in the container — restart the container: `docker restart ytdl`

---

## Build Locally

```bash
git clone https://github.com/alexbic/youtube-downloader-api.git
cd youtube-downloader-api
docker build -t youtube-downloader-api:local .
docker run -d -p 5000:5000 -e SERVER_BASE_URL=http://localhost:5000 youtube-downloader-api:local
```

---

## Technologies

- Python 3.11 + Flask 3.0 + Gunicorn
- yt-dlp + FFmpeg
- bgutil-ytdlp-pot-provider (Node.js + Deno)
- Redis (embedded)
- Supervisor

---

## License

MIT — see [LICENSE](LICENSE)

---

## Support

- Issues: [GitHub Issues](https://github.com/alexbic/youtube-downloader-api/issues)
- Email: support@alexbic.net
