# YouTube Downloader API - Release Notes v1.0.0

**Release Date:** November 21, 2025  
**Version:** 1.0.0  
**Type:** Initial Public Release (Stepwise State Tracking & Redis-First Architecture)

---

## 🎉 Overview

Первый публичный релиз YouTube Downloader API - быстрого, надежного и отказоустойчивого сервиса для скачивания видео с YouTube через REST API.

**Ключевые особенности:**
- ✅ **Redis-first архитектура** - мгновенные ответы (< 1ms) для 99% запросов
- ✅ **Stepwise state tracking** - пошаговая фиксация состояний с верификацией
- ✅ **Recovery system** - полное восстановление из любой точки отказа
- ✅ Асинхронная и синхронная загрузка видео
- ✅ Webhook уведомления с retry механизмом
- ✅ Bearer token авторизация
- ✅ Docker-ready с автоматической очисткой
- ✅ **Унифицированная структура ответов** (input/output секции)

---

## 🏗️ Architecture

### Redis-First Caching

**Концепция:** Redis как fast cache (приоритет 1) + metadata.json как source of truth (приоритет 2)

**Преимущества:**
- ⚡ **Моментальные ответы:** 99% запросов отвечает Redis за < 1ms
- 💾 **Надёжность:** metadata.json на диске для восстановления
- 🔄 **Синхронизация:** Redis обновляется на каждом этапе выполнения
- 📦 **Ёмкость:** 256MB Redis = 128,000 задач (~128 дней при 1000 задач/день)

**Как работает:**

1. **Создание задачи:** metadata.json (queued) + Redis
2. **Скачивание:** metadata.json (downloading) + Redis  
3. **Обработка:** metadata.json (processing) + Redis
4. **Завершение:** metadata.json (completed) + Redis с полной структурой
5. **Запрос `/task_status`:**
   - Сначала Redis (< 1ms) - если есть, отдаём сразу ✅
   - Если нет (истёк TTL 24h) - читаем с диска (5ms)

### Stepwise State Tracking

Каждая задача проходит через контрольные точки с верификацией:

```
queued → downloading → processing → completed/error
  ✓         ✓            ✓             ✓
```

Каждый шаг:
1. Записывает metadata.json на диск
2. Верифицирует запись (читает и сравнивает)
3. Синхронизирует Redis
4. Логирует checkpoint (✓/✗ маркеры)

**Пример логов:**
```
✓ Initial metadata.json created and verified
✓ Metadata updated: queued -> downloading
✓ Metadata updated: video info added
✓ Final metadata.json saved and verified successfully
✓ Redis synchronized with metadata.json
```

**Recovery:** При сбое можно точно определить последнее корректное состояние и продолжить с этой точки.

Подробнее: [`docs/RECOVERY_SYSTEM.md`](./RECOVERY_SYSTEM.md)

---

## 🚀 Core Features

### 1. Video Download - `/download_video`

Основной endpoint для загрузки видео с YouTube.

**HTTP Method:** `POST`  
**Authentication:** Required (если установлены `API_KEY` и `PUBLIC_BASE_URL`)  
**Content-Type:** `application/json`

**Режимы работы:**
- **Синхронный** (по умолчанию) - возвращает результат сразу после загрузки
- **Асинхронный** (`async: true`) - создает задачу и возвращает task_id

#### Request Parameters

```json
{
  "url": "https://youtube.com/watch?v=VIDEO_ID",
  "quality": "best[height<=720]",
  "async": true,
  "client_meta": {"project": "my-app", "user_id": 123},
  "webhook": {
    "url": "https://your-webhook.com/callback",
    "headers": {
      "X-API-Key": "your-secret"
    }
  }
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | ✅ Yes | - | YouTube video URL |
| `quality` | string | No | `best[height<=720]` | Video quality (см. ниже) |
| `async` | boolean | No | `false` | Async mode |
| `client_meta` | object | No | - | Произвольные метаданные (max 4096 bytes) |
| `webhook` | object | No | - | Webhook configuration |
| `webhook.url` | string | No | - | Webhook URL (http(s)://, max 2048 chars) |
| `webhook.headers` | object | No | - | Custom headers для webhook |

**Supported Quality Values:**
- `best[height<=480]` - до 480p
- `best[height<=720]` - до 720p (по умолчанию)
- `best[height<=1080]` - до 1080p
- `best` - максимальное качество

#### Response Structure (Sync Mode)

```bash
curl -X POST http://localhost:5000/download_video \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"}'
```

**Response (200 OK) - Унифицированная структура:**
```json
{
  "task_id": "abc-123-def-456",
  "status": "completed",
  "created_at": "2025-11-21T15:30:00.123456",
  "completed_at": "2025-11-21T15:30:45.654321",
  "expires_at": "2025-11-22T15:30:00.123456",
  
  "input": {
    "video_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "operations": ["download_video"],
    "operations_count": 1,
    "video_id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up",
    "duration": 212,
    "resolution": "1280x720",
    "ext": "mp4"
  },
  
  "output": {
    "output_files": [
      {
        "filename": "video_20251121_153000.mp4",
        "download_path": "/download/abc-123-def-456/video_20251121_153000.mp4",
        "download_url_internal": "http://youtube-downloader:5000/download/abc-123-def-456/video_20251121_153000.mp4",
        "download_url": "https://api.yourdomain.com/download/abc-123-def-456/video_20251121_153000.mp4",
        "expires_at": "2025-11-22T15:30:00.123456"
      }
    ],
    "total_files": 1,
    "metadata_url": "https://api.yourdomain.com/download/abc-123-def-456/metadata.json",
    "metadata_url_internal": "http://youtube-downloader:5000/download/abc-123-def-456/metadata.json",
    "ttl_seconds": 86400,
    "ttl_human": "24h"
  
  "webhook": null,
  
  "client_meta": {
    "project": "my-app",
    "user_id": 123
  }
}
```

**Структура ответа:**
- **Task Info** (верхний уровень)
  - `task_id` - уникальный ID задачи
  - `status` - статус (`completed`)
  - `created_at`, `completed_at`, `expires_at` - временные метки

- **Input** - информация о входных данных
  - `video_url` - исходный URL
  - `operations` - выполненные операции
  - `video_id`, `title`, `duration`, `resolution`, `ext` - метаданные видео

- **Output** - результаты выполнения
  - `output_files[]` - массив файлов
    - `filename` - имя файла
    - `download_path` - путь для скачивания
    - `download_url_internal` - внутренний URL (всегда)
    - `download_url` - внешний URL (если PUBLIC_BASE_URL + API_KEY)
    - `expires_at` - дата истечения файла
  - `metadata_url` / `metadata_url_internal` - ссылки на метаданные
  - `ttl_seconds` / `ttl_human` - время жизни
  
- **Webhook** - конфигурация webhook (`null` если не использовался)

- **Client Meta** - пользовательские метаданные

#### Response Structure (Async Mode)

```bash
curl -X POST http://localhost:5000/download_video \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "async": true,
    "webhook": {
      "url": "https://n8n.example.com/webhook/ready",
      "headers": {"X-API-Key": "n8n-secret"}
    }
  }'
```

**Response (202 Accepted) - Минимальная структура для отслеживания:**
```json
{
  "task_id": "abc-123-def-456",
  "status": "processing",
  "check_status_url": "https://api.yourdomain.com/task_status/abc-123-def-456",
  "metadata_url": "https://api.yourdomain.com/download/abc-123-def-456/metadata.json",
  "check_status_url_internal": "http://youtube-downloader:5000/task_status/abc-123-def-456",
  "metadata_url_internal": "http://youtube-downloader:5000/download/abc-123-def-456/metadata.json",
  "webhook": {
    "url": "https://n8n.example.com/webhook/ready",
    "headers": {"X-API-Key": "***"}
  },
  "client_meta": {"project": "my-app"}
}
```

**Структура ответа:**
- `task_id` - ID для отслеживания задачи
- `status` - текущий статус (`processing`)
- `check_status_url` - внешний URL проверки статуса (если PUBLIC_BASE_URL)
- `metadata_url` - внешний URL метаданных (если PUBLIC_BASE_URL)
- `check_status_url_internal` - внутренний URL проверки статуса (Docker network)
- `metadata_url_internal` - внутренний URL метаданных (Docker network)
- `webhook` - конфигурация webhook (чувствительные headers маскируются как `***`)
- `client_meta` - пользовательские метаданные

**Важно:** Async mode возвращает минимальную структуру для отслеживания. Полная структура с секциями `input`/`output` доступна через:
- GET `/task_status/{task_id}` - при завершении задачи
- GET `/download/{task_id}/metadata.json` - файл с полными метаданными
- Webhook callback - получает полную структуру при завершении

---

### 2. Webhook Notifications

Автоматические уведомления о завершении загрузки.

**Формат webhook объекта:**
```json
{
  "webhook": {
    "url": "https://your-webhook.com/endpoint",
    "headers": {
      "X-API-Key": "secret-key",
      "X-User-ID": "12345"
    }
  }
}
```

**Валидация:**
- ✅ `webhook` должен быть объектом (не строкой)
- ✅ `webhook.url` обязателен, начинается с http(s)://
- ✅ `webhook.url` максимум 2048 символов
- ✅ `webhook.headers` опционален, объект с парами string:string
- ✅ Имя заголовка: максимум 256 символов
- ✅ Значение заголовка: максимум 2048 символов

**Payload отправляемый на webhook (унифицированная структура):**
```json
{
  "task_id": "abc-123-def-456",
  "status": "completed",
  "created_at": "2025-11-21T15:30:00.123456",
  "completed_at": "2025-11-21T15:30:45.654321",
  "expires_at": "2025-11-22T15:30:00.123456",
  
  "input": {
    "video_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "operations": ["download_video"],
    "operations_count": 1,
    "video_id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up",
    "duration": 212,
    "resolution": "1280x720",
    "ext": "mp4"
  },
  
  "output": {
    "output_files": [
      {
        "filename": "video_20251121_153000.mp4",
        "download_path": "/download/abc-123-def-456/video_20251121_153000.mp4",
        "download_url_internal": "http://youtube-downloader:5000/download/abc-123-def-456/video_20251121_153000.mp4",
        "download_url": "https://api.yourdomain.com/download/abc-123-def-456/video_20251121_153000.mp4",
        "expires_at": "2025-11-22T15:30:00.123456"
      }
    ],
    "total_files": 1,
    "metadata_url": "https://api.yourdomain.com/download/abc-123-def-456/metadata.json",
    "metadata_url_internal": "http://youtube-downloader:5000/download/abc-123-def-456/metadata.json",
    "ttl_seconds": 86400,
    "ttl_human": "24h"
  },
  
  "webhook": null,
  "client_meta": {"project": "my-app", "user_id": 123}
}
```

**Важно:** Webhook получает точно ту же структуру, что сохранена в metadata.json - никаких преобразований!

**Retry механизм:**
- 3 попытки доставки
- Интервал между попытками: 5 секунд
- Timeout каждого запроса: 8 секунд
- Фоновый resender: проверка каждые 15 минут (900 секунд)

**Отслеживание состояния:**
Состояние webhook сохраняется в `metadata.json`:
```json
{
  "webhook": {
    "url": "https://webhook.com/callback",
    "headers": {"X-API-Key": "***"},
    "status": "delivered",
    "attempts": 1,
    "last_attempt": "2025-11-21T15:30:01.456789",
    "last_status": 200,
    "last_error": null,
    "next_retry": null
  }
}
```

**Статусы webhook:**
- `pending` - ожидает доставки
- `delivered` - успешно доставлен (HTTP 200-299)
- `failed` - все попытки исчерпаны

---

### 3. Task Status - `/task_status/<task_id>`

Проверка статуса асинхронной задачи.

**Запрос:**
```bash
curl http://localhost:5000/task_status/abc-123-def
```

**Ответ (processing) - минимальная структура:**
```json
{
  "task_id": "abc-123-def",
  "status": "processing",
  "created_at": "2025-11-21T15:29:00.123456"
}
```

**Ответ (completed) - полная унифицированная структура из Redis/metadata.json:**
```json
{
  "task_id": "abc-123-def-456",
  "status": "completed",
  "created_at": "2025-11-21T15:30:00.123456",
  "completed_at": "2025-11-21T15:30:45.654321",
  "expires_at": "2025-11-22T15:30:00.123456",
  
  "input": {
    "video_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "operations": ["download_video"],
    "operations_count": 1,
    "video_id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up",
    "duration": 212,
    "resolution": "1280x720",
    "ext": "mp4"
  },
  
  "output": {
    "output_files": [
      {
        "filename": "video_20251121_153000.mp4",
        "download_path": "/download/abc-123-def-456/video_20251121_153000.mp4",
        "download_url_internal": "http://youtube-downloader:5000/download/abc-123-def-456/video_20251121_153000.mp4",
        "download_url": "https://api.yourdomain.com/download/abc-123-def-456/video_20251121_153000.mp4",
        "expires_at": "2025-11-22T15:30:00.123456"
      }
    ],
    "total_files": 1,
    "metadata_url": "https://api.yourdomain.com/download/abc-123-def-456/metadata.json",
    "metadata_url_internal": "http://youtube-downloader:5000/download/abc-123-def-456/metadata.json",
    "ttl_seconds": 86400,
    "ttl_human": "24h"
  },
  
  "webhook": null,
  "client_meta": {"project": "my-app"}
}
```

**Примечание:** При запросе `/task_status` для завершённых задач:
- Первые 24 часа (в TTL): ответ из Redis за < 1ms
- После TTL: ответ из metadata.json на диске за ~5ms
- Обе структуры идентичны (синхронизированы)

**Ответ (error) - структура ошибки:**
```json
{
  "task_id": "abc-123-def",
  "status": "error",
  "operation": "download_video_async",
  "error_type": "unavailable",
  "error_message": "Video is unavailable",
  "user_action": "Mark as unavailable - deleted or removed",
  "raw_error": "ERROR: [youtube] video_id: Video unavailable",
  "failed_at": "2025-11-21T15:29:15.123456",
  "client_meta": {"project": "my-app"}
}
```

---

### 4. Health Check - `/health`

Проверка работоспособности сервиса.

**Запрос:**
```bash
curl http://localhost:5000/health
```

**Ответ:**
```json
{
  "status": "healthy",
  "service": "youtube-downloader-api",
  "version": "public",
  "timestamp": "2025-11-21T15:30:00.123456",
  "auth": "enabled",
  "storage": "memory",
  "config": {
    "workers": 2,
    "redis": {
      "host": "127.0.0.1",
      "port": 6379,
      "db": 0,
      "maxmemory": "256MB",
      "embedded": true
    },
    "limits": {
      "task_ttl_seconds": 86400,
      "max_client_meta_bytes": 4096,
      "max_client_meta_depth": 5,
      "max_client_meta_keys": 50,
      "max_client_meta_string_length": 1024,
      "max_client_meta_list_length": 100
    },
    "webhook": {
      "retry_attempts": 3,
      "retry_interval_seconds": 5.0,
      "timeout_seconds": 8.0,
      "background_interval_seconds": 900.0
    }
  }
}
```

---

### 6. File Download - `/download/<task_id>/<filename>`

Скачивание готового файла.

**Запрос:**
```bash
curl -O http://localhost:5000/download/abc-123-def/video.mp4
```

**Метаданные задачи:**
```bash
curl http://localhost:5000/download/abc-123-def/metadata.json
```

---

## 📄 Metadata Structure

Каждая задача сохраняет детальные метаданные в файл `metadata.json` со структурированным форматом.

### Структура metadata.json

```json
[
  {
    "task_id": "abc-123-def-456",
    "status": "completed",
    "created_at": "2025-11-21T15:30:00.123456",
    "completed_at": "2025-11-21T15:30:45.654321",
    "expires_at": "2025-11-22T15:30:00.123456",
    
    "input": {
      "video_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
      "operations": ["download_video"],
      "operations_count": 1,
      "video_id": "dQw4w9WgXcQ",
      "title": "Rick Astley - Never Gonna Give You Up",
      "duration": 212,
      "resolution": "1280x720",
      "ext": "mp4"
    },
    
    "output": {
      "output_files": [
        {
          "filename": "video_20251121_153000.mp4",
          "download_path": "/download/abc-123-def-456/video_20251121_153000.mp4",
          "download_url_internal": "http://youtube-downloader:5000/download/abc-123-def-456/video_20251121_153000.mp4",
          "download_url": "https://api.yourdomain.com/download/abc-123-def-456/video_20251121_153000.mp4",
          "expires_at": "2025-11-22T15:30:00.123456"
        }
      ],
      "total_files": 1,
      "metadata_url": "https://api.yourdomain.com/download/abc-123-def-456/metadata.json",
      "metadata_url_internal": "http://youtube-downloader:5000/download/abc-123-def-456/metadata.json",
      "ttl_seconds": 86400,
      "ttl_human": "24h",
      "expires_at": "2025-11-22T15:30:00.123456"
    },
    
    "webhook": {
      "url": "https://webhook.com/callback",
      "headers": {"X-API-Key": "***"},
      "status": "delivered",
      "attempts": 1,
      "last_attempt": "2025-11-21T15:30:01.456789",
      "last_status": 200,
      "last_error": null,
      "next_retry": null,
      "task_id": "abc-123-def-456"
    },
    
    "client_meta": {
      "project": "my-app",
      "user_id": 123
    }
  }
]
```

**Секции metadata.json:**

1. **Task Info** - базовая информация о задаче
   - `task_id` - уникальный ID
   - `status` - статус выполнения
   - `created_at` - время создания (ISO 8601)
   - `completed_at` - время завершения (ISO 8601)
   - `expires_at` - время истечения TTL (ISO 8601)

2. **Input** - информация о входных данных
   - `video_url` - исходный URL видео
   - `operations` - массив выполненных операций
   - `operations_count` - количество операций
   - `video_id`, `title`, `duration`, `resolution`, `ext` - метаданные видео

3. **Output** - информация о результатах
   - `output_files` - массив выходных файлов
     - `filename` - имя файла
     - `download_path` - относительный путь
     - `download_url_internal` - внутренний URL (всегда)
     - `download_url` - внешний URL (если `PUBLIC_BASE_URL` и `API_KEY`)
     - `expires_at` - время истечения
   - `total_files` - количество файлов
   - `metadata_url` / `metadata_url_internal` - ссылки на метаданные
   - `ttl_seconds` - TTL в секундах (86400 = 24 часа)
   - `ttl_human` - TTL в читаемом формате (`24h`, `30m`, etc.)
   - `expires_at` - время истечения

4. **Webhook** - состояние webhook доставки (если был указан)
   - `url`, `headers` - конфигурация webhook
   - `status` - статус доставки (`pending`, `delivered`, `failed`)
   - `attempts` - количество попыток
   - `last_attempt`, `last_status`, `last_error` - информация о последней попытке
   - `next_retry` - время следующей попытки

5. **Client Meta** - пользовательские метаданные (если были переданы)

---

## 🔒 Authentication

### Режимы работы:

**1. Internal Mode (без авторизации)**
- Не указаны `API_KEY` и `PUBLIC_BASE_URL`
- Все endpoints доступны без токена
- Подходит для использования внутри Docker network

**2. Public Mode (с авторизацией)**
- Указаны `API_KEY` и `PUBLIC_BASE_URL`
- Требуется Bearer token для защищенных endpoints

**Защищенные endpoints:**
- `POST /download_video`

**Публичные endpoints:**
- `GET /health`
- `GET /task_status/<task_id>`
- `GET /download/<task_id>/<filename>`

**Формат авторизации:**
```bash
# Предпочтительный способ (Bearer token)
Authorization: Bearer YOUR_API_KEY

# Альтернативный способ (backward compatibility)
X-API-Key: YOUR_API_KEY
```

---

## 🐳 Docker Deployment

### Quick Start

```bash
docker run -d \
  -p 5000:5000 \
  -e API_KEY="your-secret-key" \
  -e PUBLIC_BASE_URL="https://api.yourdomain.com" \
  -v ./tasks:/app/tasks \
  alexbic/youtube-downloader-api:latest
```

### Docker Compose

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
      API_KEY: ${API_KEY}
      PUBLIC_BASE_URL: ${PUBLIC_BASE_URL}
      LOG_LEVEL: INFO
    restart: unless-stopped
```

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `API_KEY` | Bearer token для авторизации | - | Нет* |
| `PUBLIC_BASE_URL` | Внешний URL API (https://your-domain.com) | - | Нет* |
| `INTERNAL_BASE_URL` | Внутренний URL для Docker network | - | Нет |
| `LOG_LEVEL` | Уровень логирования (DEBUG/INFO/WARNING/ERROR) | INFO | Нет |

\* Авторизация включается только если указаны **оба** параметра: `API_KEY` и `PUBLIC_BASE_URL`

---

## 🔧 Technical Details

### Hardcoded Parameters

Следующие параметры зафиксированы:

**Storage:**
- Workers: 2 (hardcoded в Dockerfile)
- Redis: встроенный, 256MB памяти
- Task TTL: 24 часа (86400 секунд)
- Storage mode: memory (Redis)

**Limits:**
- `client_meta`: максимум 4096 байт
- Глубина вложенности `client_meta`: 5 уровней
- Максимум ключей в `client_meta`: 50
- Максимальная длина строки: 1024 символа
- Максимальная длина списка: 100 элементов

**Webhook:**
- Retry attempts: 3
- Retry interval: 5 секунд
- Timeout: 8 секунд
- Background resender: каждые 15 минут

**Logging:**
- Progress mode: off (без логов прогресса скачивания)
- yt-dlp warnings: disabled

### Automatic Cleanup

- Задачи автоматически удаляются через 24 часа
- Cleanup запускается при каждом новом запросе
- Удаляются как файлы, так и записи в Redis

### Cookies Support

Для обхода ограничений YouTube можно использовать cookies из браузера:

```json
{
  "url": "https://youtube.com/watch?v=VIDEO_ID"
}
```

Поддерживаемые браузеры: `chrome`, `firefox`, `edge`, `safari`, `opera`

---

## 📦 Client Meta

Произвольные метаданные для отслеживания задач в вашей системе.

**Пример:**
```json
{
  "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
  "client_meta": {
    "project": "my-video-app",
    "user_id": 12345,
    "campaign": "summer-2025",
    "tags": ["music", "viral"]
  }
}
```

**Ограничения:**
- Максимум 4096 байт в JSON
- Максимум 5 уровней вложенности
- Максимум 50 ключей
- Строки: до 1024 символов
- Массивы: до 100 элементов

`client_meta` возвращается в:
- Ответе `/download_video`
- Ответе `/task_status/<task_id>`
- Webhook payload
- `metadata.json`

---

## 🔥 Use Cases

### 1. Синхронная загрузка для небольших видео

```python
import requests

response = requests.post('http://localhost:5000/download_video', 
    headers={'Authorization': 'Bearer YOUR_KEY'},
    json={'url': 'https://youtube.com/watch?v=VIDEO_ID'}
)

data = response.json()
video_url = data['task_download_url']
print(f"Download: {video_url}")
```

### 2. Асинхронная загрузка с polling

```python
import requests
import time

# Создаем задачу
response = requests.post('http://localhost:5000/download_video',
    headers={'Authorization': 'Bearer YOUR_KEY'},
    json={
        'url': 'https://youtube.com/watch?v=VIDEO_ID',
        'async': True
    }
)

task_id = response.json()['task_id']

# Проверяем статус
while True:
    status = requests.get(f'http://localhost:5000/task_status/{task_id}')
    data = status.json()
    
    if data['status'] == 'completed':
        print(f"Download: {data['task_download_url']}")
        break
    elif data['status'] == 'error':
        print(f"Error: {data['error_message']}")
        break
    
    time.sleep(2)
```

### 3. Асинхронная загрузка с webhook (n8n)

```json
{
  "url": "https://youtube.com/watch?v=VIDEO_ID",
  "async": true,
  "quality": "best[height<=720]",
  "webhook": {
    "url": "https://n8n.example.com/webhook/video-ready",
    "headers": {
      "X-API-Key": "n8n-secret"
    }
  },
  "client_meta": {
    "workflow_id": "wf_123",
    "execution_id": "exec_456"
  }
}
```

---

## ⚠️ Known Limitations

- Workers: 2 (fixed)
- Task TTL: 24 hours (fixed)
- Redis: built-in, 256 MB (fixed)

---

## 🐛 Bug Reports & Support

- **GitHub Issues:** https://github.com/alexbic/youtube-downloader-api/issues
- **Documentation:** https://github.com/alexbic/youtube-downloader-api
- **Email:** support@alexbic.net

---

## 📝 License

MIT License - see LICENSE file for details

---

**Thank you for using YouTube Downloader API!** 🎬✨
