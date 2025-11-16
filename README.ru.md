# YouTube Downloader API

**Open Source** REST API для скачивания видео с YouTube и получения прямых ссылок на видеофайлы.

[![Docker Hub](https://img.shields.io/docker/v/alexbic/youtube-downloader-api?label=Docker%20Hub&logo=docker)](https://hub.docker.com/r/alexbic/youtube-downloader-api)
[![GitHub Container Registry](https://img.shields.io/badge/ghcr.io-image-blue?logo=github)](https://github.com/alexbic/youtube-downloader-api/pkgs/container/youtube-downloader-api)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-1.0.0-blue)](RELEASE_NOTES_v1.0.0.md)

[English](README.md) | **Русский**

---

## Возможности

- Получение прямой ссылки на видео без загрузки на сервер
- Скачивание видео на сервер с выбором качества (sync/async)
- Получение полной информации о видео
- Поддержка различных форматов и качества
- Health check endpoint для мониторинга
- Автоматическая публикация на Docker Hub и GitHub Container Registry
- Поддержка платформ: linux/amd64, linux/arm64
- Абсолютные ссылки как для внешнего, так и для внутреннего контура
- Поддержка webhook-уведомлений в async-режиме (POST на `webhook_url` по завершении)
- Консервативный порядок ключей в JSON (поле `client_meta` всегда последним)
- Гибкая конфигурация внутренних/внешних URL: `PUBLIC_BASE_URL`/`INTERNAL_BASE_URL`
- Контролируемая очистка старых задач: `CLEANUP_TTL_SECONDS` (0 = отключено)
- Опциональное хранилище задач в Redis; без Redis — in-memory

## Установка

### Из Docker Hub

```bash
docker pull alexbic/youtube-downloader-api:latest
```
```bash
docker pull ghcr.io/alexbic/youtube-downloader-api:latest
```

## Быстрый старт

### Запуск через Docker (Docker Hub)

```bash
docker run -d -p 5000:5000 --name yt-downloader alexbic/youtube-downloader-api:latest
```

### Запуск через Docker (GitHub Container Registry)

```bash
docker run -d -p 5000:5000 --name yt-downloader ghcr.io/alexbic/youtube-downloader-api:latest

### Запуск с cookies для обхода защиты YouTube

YouTube может периодически блокировать загрузки, требуя авторизацию.

**⚠️ Важно про cookies:**
- YouTube ротирует cookies в открытых вкладках как меру безопасности
- Cookies, экспортированные из обычной вкладки, быстро протухают
- Нужно экспортировать через **приватное окно** по специальной методике

#### Метод 1: Через расширение браузера (рекомендуется)

**Шаг 1. Включите расширение в режиме инкогнито:**

**Chrome:**
1. Откройте `chrome://extensions/`
2. Найдите расширение [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
3. Нажмите **"Подробнее"** (Details)
4. Включите **"Разрешить использование в режиме инкогнито"** (Allow in incognito)

**Firefox:**
1. Откройте `about:addons`
2. Найдите расширение [cookies.txt](https://addons.mozilla.org/ru/firefox/addon/cookies-txt/)
3. Включите **"Выполнять в приватных окнах"** (Run in Private Windows)

**Шаг 2. Экспортируйте cookies:**

1. Откройте **новое приватное/инкогнито окно** и залогиньтесь на YouTube
2. Перейдите на `https://www.youtube.com/robots.txt`
3. Экспортируйте cookies для `youtube.com` через расширение (теперь оно работает!)
4. **Сразу закройте** приватное окно

#### Метод 2: Через DevTools (без расширений)

1. Откройте **новое приватное/инкогнито окно** и залогиньтесь на YouTube
2. Перейдите на `https://www.youtube.com/robots.txt`
3. Откройте **DevTools** (F12 или Cmd+Option+I)
4. Перейдите на вкладку **Console**
5. Скопируйте и выполните команду:

```javascript
copy(document.cookie.split('; ').map(c => {
  const [name, ...v] = c.split('=');
  return `.youtube.com\tTRUE\t/\tTRUE\t0\t${name}\t${v.join('=')}`;
}).join('\n'))
```

6. Cookies скопированы в буфер обмена — вставьте в файл `cookies.txt`
7. **Добавьте в начало файла:** `# Netscape HTTP Cookie File`
8. **Сразу закройте** приватное окно

**Примечания:**
- НЕ используйте `--cookies-from-browser` — он берёт cookies из обычного браузера
- DevTools даёт базовый формат; для продакшена лучше расширение

#### Использование cookies:

1. Положите `cookies.txt` рядом с `docker-compose.yml`
2. Раскомментируйте строку:

```yaml
volumes:
  - ./cookies.txt:/app/cookies.txt
```

3. Перезапустите: `docker-compose up -d`

**Готово!** API автоматически использует cookies и обновляет timestamp перед каждым запросом.

#### PO Token (для современных видео):

YouTube постепенно вводит обязательное использование "PO Token" для скачивания. Если cookies не помогают:
- Изучите [PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)
- Рекомендуется использовать `mweb` клиент с PO Token
- По умолчанию yt-dlp пытается использовать клиенты без токена, но некоторые форматы могут быть недоступны

**Дополнительная информация:**
- [Как правильно экспортировать YouTube cookies](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)
- [Типичные ошибки YouTube](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#common-youtube-errors)
- Рекомендуется добавить задержку 5-10 секунд между запросами
- Лимит для гостей: ~300 видео/час, для аккаунтов: ~2000 видео/час

### Запуск через Docker Compose

```yaml
version: '3.8'
services:
  youtube-downloader:
    # image: ghcr.io/alexbic/youtube-downloader-api:latest
    ports:
      - "5000:5000"
    volumes:
      - ./tasks:/app/tasks
      # - ./cookies.txt:/app/cookies.txt  # при необходимости
    environment:
      # Public base URL for generating absolute download links (no trailing slash)
      # Example for reverse-proxy on a subpath:
      PUBLIC_BASE_URL: ${PUBLIC_BASE_URL}
      # Optional internal base URL for links inside your private network (Docker/k8s)
      INTERNAL_BASE_URL: ${INTERNAL_BASE_URL}
      # API Key for authentication (Bearer token)
      # If not set, API will work without authentication (not recommended for production)
      # Generate secure key: openssl rand -hex 32
      API_KEY: ${API_KEY}

      # Progress logging for yt-dlp: off|compact|full (default: off)
      PROGRESS_LOG: ${PROGRESS_LOG}
      # Forward yt-dlp warnings to app logs (optional)
      LOG_YTDLP_WARNINGS: ${LOG_YTDLP_WARNINGS}

      # Redis configuration (enable multi-worker mode)
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_DB: 0  # По умолчанию DB 0; если делите Redis с видеопроцессором — смените на 1

      # Cleanup TTL (seconds). 0 — не удалять задачи
      CLEANUP_TTL_SECONDS: 3600

      # Gunicorn workers / timeout
      WORKERS: 2  # Can use 2+ workers with Redis
      GUNICORN_TIMEOUT: 600
    restart: unless-stopped
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    restart: unless-stopped
```

## API Endpoints

### 1. Health Check

```bash
GET /health
```

Ответ (поля могут отличаться в зависимости от конфигурации):
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.123456",
  "auth": "enabled|disabled",
  "storage": "redis|memory"
}
```

### 2. Скачать видео (sync/async)

```bash
POST /download_video
Content-Type: application/json
```

Пример валидного JSON (async):
```json
{
  "url": "https://www.youtube.com/watch?v=pj8lIC7kP6I",
  "async": true,
  "quality": "best[height<=720]",
  "client_meta": {"videoId": "pj8lIC7kP6I"}
}
```

Пример валидного JSON (sync):
```json
{
  "url": "https://www.youtube.com/watch?v=pj8lIC7kP6I",
  "quality": "best[height<=720]",
  "client_meta": {"videoId": "pj8lIC7kP6I"}
}
```

Параметры:
- `url` (обязательный) — ссылка на YouTube
- `async` (опциональный, bool) — если true, задача выполняется асинхронно, иначе синхронно
- `quality` (опциональный, string) — формат yt-dlp, по умолчанию `best[height<=720]`
- `cookiesFromBrowser` (опциональный, string) — браузер для извлечения cookies (`chrome`, `firefox`, `safari`, `edge`; работает только локально, не в Docker)
- `client_meta` (опциональный, object) — любые ваши метаданные; сохраняются в `metadata.json` и возвращаются в ответе
- `webhook_url` (опциональный, string) — URL (http/https) для callback в async-режиме; по завершении отправляется POST с JSON (см. раздел Webhook)

Аутентификация, если включена (см. PUBLIC_BASE_URL + API_KEY): используйте заголовок
`Authorization: Bearer <API_KEY>` (или совместимый `X-API-Key`).


#### Пример ответа (sync):
```json
{
  "task_id": "ab12cd34-...",
  "status": "completed",
  "video_id": "pj8lIC7kP6I",
  "title": "Название видео",
  "filename": "video_20251114_212811.mp4",
  "file_size": 15728640,
  "download_endpoint": "/download/ab12cd34.../output/video_20251114_212811.mp4",
  "storage_rel_path": "ab12cd34.../output/video_20251114_212811.mp4",
  "task_download_url": "http://public.example.com/download/ab12cd34.../output/video_20251114_212811.mp4",
  "task_download_url_internal": "http://service.local:5000/download/ab12cd34.../output/video_20251114_212811.mp4",
  "metadata_url": "http://public.example.com/download/ab12cd34.../metadata.json",
  "metadata_url_internal": "http://service.local:5000/download/ab12cd34.../metadata.json",
  "duration": 180,
  "resolution": "1280x720",
  "ext": "mp4",
  "client_meta": {"videoId": "pj8lIC7kP6I"},
  "processed_at": "2025-11-14T21:28:11.123456"
}
```

#### Пример ответа (async):
```json
{
  "task_id": "ab12cd34-...",
  "status": "processing",
  "check_status_url": "http://public.example.com/task_status/ab12cd34-...",
  "check_status_url_internal": "http://service.local/task_status/ab12cd34-...",
  "metadata_url": "http://public.example.com/download/ab12cd34.../metadata.json",
  "metadata_url_internal": "http://service.local/download/ab12cd34.../metadata.json",
  "client_meta": {"videoId": "pj8lIC7kP6I"}
}
```

> **Важно:** В async-режиме ошибки (например, если видео приватное, удалено, заблокировано и т.д.) возвращаются только через `/task_status/<task_id>`. Сам ответ на POST всегда содержит только task_id и статус. Для получения результата или ошибки опрашивайте `/task_status/<task_id>`.

В sync-режиме ошибка возвращается сразу с HTTP 400 и описанием ошибки.

### 3. Проверить статус задачи

```bash
GET /task_status/<task_id>
```

Ответ (варианты):
- status=processing: `{ "task_id": "...", "status": "processing" }`
- status=completed: включает поля `download_endpoint`, `storage_rel_path`, `task_download_url(_internal)`, `metadata_url(_internal)`, а также медиа-поля (`filename`, `duration`, `resolution`, `ext`, `title`, `video_id`, `created_at`, `completed_at`).
- status=error: включает `error_type`, `error_message`, `user_action`, по возможности `raw_error`.

Поле `client_meta` возвращается последним (сохраняется порядок ключей JSON).

### 4. Скачать результат или метаданные

```bash
GET /download/<task_id>/output/<file>
GET /download/<task_id>/metadata.json
```

### 5. Получить прямую ссылку на видео

```bash
POST /get_direct_url
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "quality": "best[height<=720]"
}
```

Параметры:
- `url` (обязательный) - URL видео YouTube
- `quality` (опциональный) - качество видео (по умолчанию: `best[height<=720]`)
  - `best[height<=720]` - лучшее до 720p
  - `best[height<=480]` - лучшее до 480p
  - `best[height<=1080]` - лучшее до 1080p
  - `best` - максимальное качество

Ответ:
```json
{
  "video_id": "VIDEO_ID",
  "title": "Название видео",
  "direct_url": "https://...",
  "duration": 180,
  "filesize": 15728640,
  "ext": "mp4",
  "resolution": "1280x720",
  "fps": 30,
  "thumbnail": "https://...",
  "uploader": "Channel Name",
  "upload_date": "20240115",
  "http_headers": {"User-Agent": "..."},
  "expiry_warning": "URL expires in a few hours. Use immediately or call /download_video to save permanently.",
  "processed_at": "2024-01-15T10:30:00.123456"
}
```

**Важно:** Прямые ссылки имеют ограниченный срок действия и могут выдать 403 Forbidden при скачивании. Для гарантированного скачивания используйте `/download_video` (async или sync).

### 6. n8n: рекомендуемая схема (через /download_video)

**Шаг 0: Настройте n8n для работы с большими файлами**

Добавьте в docker-compose.yml вашего n8n стека:
```yaml
services:
  n8n:
    environment:
      - N8N_DEFAULT_BINARY_DATA_MODE=filesystem
```

Перезапустите n8n после изменения конфигурации.

Вариант A (sync, проще):
1) POST http://youtube_downloader:5000/download_video (Body: `{ "url": "..." }`)
2) В ответе используйте `task_download_url` для загрузки файла (Response Format: File, Binary Property: data)

Вариант B (async, надёжнее для длительных задач):
1) POST /download_video c `{"url":"...","async":true}` — получить `task_id`
2) Циклически опрашивать `/task_status/{{task_id}}` до `status=completed`
3) Скачать `{{ $json.task_download_url }}` (Response Format: File, Binary Property: data)

**Критически важно**:
1. n8n должен быть настроен с `N8N_DEFAULT_BINARY_DATA_MODE=filesystem`
2. В Node 2 установите "Response Format" в значение "File"
3. Без правильной конфигурации n8n будет пытаться загрузить видео в память и выдаст ошибку "Cannot create a string longer than 0x1fffffe8 characters"

API автоматически вернёт абсолютные URL. Для внутренних сценариев есть дублирующие поля `*_internal`.

Про `client_meta` в n8n: передавайте объект/массив как есть (не строку). Если формируете через Expression — не заключайте выражение в кавычки, чтобы избежать `"[object Object]"`.

### 7. Webhook callbacks (async)

Если в `POST /download_video` передан `webhook_url` (или алиасы `webhook`, `callback_url`), сервис по завершении задачи делает `POST` на указанный URL с `Content-Type: application/json`.

Успешный payload (поля как в `task_status`, `client_meta` — последним):
```json
{
  "task_id": "...",
  "status": "completed",
  "video_id": "...",
  "title": "...",
  "filename": "...mp4",
  "download_endpoint": "/download/.../output/...mp4",
  "storage_rel_path": ".../output/...mp4",
  "duration": 213,
  "resolution": "640x360",
  "ext": "mp4",
  "created_at": "2025-11-15T06:18:46.629918",
  "completed_at": "2025-11-15T06:18:56.338989",
  "task_download_url_internal": "http://service.local:5000/download/...",
  "metadata_url_internal": "http://service.local:5000/download/.../metadata.json",
  "client_meta": {"your":"meta"}
}
```

Ошибка:
```json
{
  "task_id": "...",
  "status": "error",
  "operation": "download_video_async",
  "error_type": "private_video|unavailable|deleted|...",
  "error_message": "...",
  "user_action": "...",
  "failed_at": "2025-11-15T06:20:00.000000",
  "client_meta": {"your":"meta"}
}
```

Технические детали:
- `webhook_url` должен начинаться с http(s):// и быть короче 2048 символов
- Таймаут на отправку: по умолчанию 8 секунд (настраивается `WEBHOOK_TIMEOUT_SECONDS`)
- Повторы доставки: по умолчанию 3 попытки с интервалом 5 секунд
  - `WEBHOOK_RETRY_ATTEMPTS` — число попыток (default: 3)
  - `WEBHOOK_RETRY_INTERVAL_SECONDS` — интервал между попытками (default: 5)
  - Ошибка доставки не прерывает основной процесс (best-effort)

### 8. Получить информацию о видео

```bash
POST /get_video_info
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID"
}
```

Ответ:
```json
{
  "video_id": "VIDEO_ID",
  "title": "Название видео",
  "description": "Описание...",
  "duration": 180,
  "view_count": 1000000,
  "like_count": 50000,
  "uploader": "Channel Name",
  "upload_date": "20240115",
  "thumbnail": "https://...",
  "tags": ["tag1", "tag2"],
  "available_formats": 25,
  "processed_at": "2024-01-15T10:30:00.123456"
  "video_id": "VIDEO_ID",
  "title": "Название видео",
  "description": "Описание...",
  "duration": 180,
  "view_count": 1000000,
  "like_count": 50000,
  "uploader": "Channel Name",
  "upload_date": "20240115",
  "thumbnail": "https://...",
  "tags": ["tag1", "tag2"],
  "available_formats": 25,
  "processed_at": "2024-01-15T10:30:00.123456"
}
```

## Примеры использования

### cURL

```bash
# Получить прямую ссылку (без auth)
curl -X POST http://localhost:5000/get_direct_url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# То же с включенной auth (Bearer)
curl -X POST http://localhost:5000/get_direct_url \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# Скачать видео
curl -X POST http://localhost:5000/download_video \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "quality": "best[height<=480]"}'

# Получить информацию
curl -X POST http://localhost:5000/get_video_info \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

### Python

```python
import requests

# Получить прямую ссылку
response = requests.post('http://localhost:5000/get_direct_url', json={
    'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    'quality': 'best[height<=720]'
})

data = response.json()
print(f"Direct URL: {data['direct_url']}")

# Скачать видео
response = requests.post('http://localhost:5000/download_video', json={
    'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
})

data = response.json()
download_url = f"http://localhost:5000{data['download_url']}"
print(f"Download URL: {download_url}")
```

### JavaScript (Node.js)

```javascript
const axios = require('axios');

// Получить прямую ссылку
async function getDirectUrl(videoUrl) {
  const response = await axios.post('http://localhost:5000/get_direct_url', {
    url: videoUrl,
    quality: 'best[height<=720]'
  });

  return response.data.direct_url;
}

// Использование
getDirectUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
  .then(url => console.log('Direct URL:', url))
  .catch(err => console.error('Error:', err));
```

## Разработка

### Локальная сборка

```bash
git clone https://github.com/alexbic/youtube-downloader-api.git
cd youtube-downloader-api
docker build -t yt-dl-api:test .
docker run -p 5000:5000 yt-dl-api:test
```

### Локальный запуск без Docker

```bash
pip install -r requirements.txt
python app.py
```

## CI/CD

Проект настроен с автоматической сборкой и публикацией через GitHub Actions.

При каждом push в `main` ветку автоматически:
1. Собирается Docker образ для платформ linux/amd64 и linux/arm64
2. Публикуется на Docker Hub: `alexbic/youtube-downloader-api`
3. Публикуется на GitHub Container Registry: `ghcr.io/alexbic/youtube-downloader-api`
4. Обновляется описание на Docker Hub

Статус сборки можно посмотреть на [странице Actions](https://github.com/alexbic/youtube-downloader-api/actions)

## Технологии

- Python 3.11
- Flask 3.0.0
- yt-dlp (latest)
- FFmpeg
- Gunicorn
- Docker

## Конфигурация и аутентификация

- `PUBLIC_BASE_URL`: если задан вместе с `API_KEY`, API включает аутентификацию и возвращает абсолютные внешние ссылки по этому базовому URL. Если `PUBLIC_BASE_URL` задан без `API_KEY`, публичный режим не активируется (auth=disabled), ссылки будут внутренние.
- `API_KEY`: секретный ключ. Используйте заголовок `Authorization: Bearer <API_KEY>` (поддерживается и `X-API-Key`).
- `INTERNAL_BASE_URL`: опциональный базовый URL внутреннего контура (Docker/k8s). Если не задан, внутренние ссылки строятся от `request.host_url`.
- `CLEANUP_TTL_SECONDS`: TTL в секундах для автоочистки старых задач в `/app/tasks` (0 — отключить очистку). По умолчанию 3600 сек.
- `WORKERS`: число воркеров Gunicorn. Для 2+ воркеров рекомендуется Redis.
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`: конфигурация Redis. По умолчанию используется DB 0. Если вы делите один Redis с другим сервисом (например, видеопроцессор использует DB 0), задайте отдельную DB (например, 1).

### Как строятся ссылки
- Относительный путь до файла: `download_endpoint` (HTTP endpoint) и `storage_rel_path` (относительный путь на диске)
- Абсолютные внешние ссылки: `task_download_url`, `metadata_url` (используют `PUBLIC_BASE_URL` при активной auth)
- Абсолютные внутренние ссылки: `task_download_url_internal`, `metadata_url_internal` (используют `INTERNAL_BASE_URL`, если задан; иначе `request.host_url`)

### Режимы
- Internal (auth=disabled): без `API_KEY` и без активного `PUBLIC_BASE_URL`. Ссылки будут строиться от `request.host_url`.
- Public (auth=enabled): `PUBLIC_BASE_URL` + `API_KEY` заданы. Возвращаются внешние и внутренние абсолютные URL.

Дополнительно:
- Порядок ключей JSON сохраняется, поле `client_meta` добавляется последним для удобства восприятия

## Quick Config

Рекомендуемые быстрые конфигурации для типичных сценариев.

### Production за reverse-proxy (публичный доступ)
- `PUBLIC_BASE_URL`: публичный URL вашего сервиса, например `https://yt.example.com`
- `API_KEY`: обязательный — включает авторизацию (Bearer)
- `PROGRESS_LOG=off`: чтобы не засорять логи прогрессом
- `LOG_LEVEL=INFO` (или `ERROR` для ещё тише)
- `WORKERS=2`+ и Redis (для параллельных задач)

Docker Compose пример:
```yaml
services:
  youtube-downloader:
    image: alexbic/youtube-downloader-api:latest
    environment:
      PUBLIC_BASE_URL: https://yt.example.com
      API_KEY: ${API_KEY}
      WORKERS: 2
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_DB: 0
      PROGRESS_LOG: off
      LOG_LEVEL: INFO
    ports:
      - "5000:5000"
    volumes:
      - ./tasks:/app/tasks
      # - ./cookies.txt:/app/cookies.txt  # при необходимости
    depends_on:
      - redis
  redis:
    image: redis:7-alpine
```

### Внутренний контур (только из вашей сети)
- Без `API_KEY` и без `PUBLIC_BASE_URL` (auth=disabled)
- `INTERNAL_BASE_URL` опционально — если нужно отдавать абсолютные внутренние ссылки
- `PROGRESS_LOG=off`, `LOG_LEVEL=INFO`

Docker run пример:
```bash
docker run -d -p 5000:5000 \
  -e PROGRESS_LOG=off -e LOG_LEVEL=INFO \
  -e CLEANUP_TTL_SECONDS=0 \
  -v $(pwd)/tasks:/app/tasks \
  alexbic/youtube-downloader-api:latest
```

### Отладка
- Включить подробный прогресс и отладочный уровень:
```bash
docker run -d -p 5000:5000 \
  -e PROGRESS_LOG=full -e LOG_LEVEL=DEBUG -e LOG_YTDLP_OPTS=true \
  alexbic/youtube-downloader-api:latest
```

### Логирование
- `LOG_LEVEL`: уровень логов приложения. Значения: `DEBUG`, `INFO` (по умолчанию), `WARNING`, `ERROR`, `CRITICAL`.
- `PROGRESS_LOG`: управление логами прогресса скачивания yt-dlp.
  - `off` (по умолчанию): полностью подавляет прогресс-спам (включаются quiet/noprogress у yt-dlp).
  - `compact`: компактные логи только по шагам (каждые `PROGRESS_STEP`%), например: `[abcd1234] progress: 20%`.
  - `full`: подробные логи yt-dlp как есть (может быть очень многословно).
- `PROGRESS_STEP`: шаг в процентах для `compact`-режима (по умолчанию 10).
- `LOG_YTDLP_OPTS`: если `true`, логирует применённые опции yt-dlp (для отладки).
- `LOG_YTDLP_WARNINGS`: если `true`, предупреждения yt-dlp будут попадать в логи приложения.

Примеры запуска:

```bash
# Полное подавление прогресса (рекомендуется для production)
docker run -d -p 5000:5000 \
  -e PROGRESS_LOG=off -e LOG_LEVEL=INFO \
  alexbic/youtube-downloader-api:latest

# Компактные логи прогресса каждые 20%
docker run -d -p 5000:5000 \
  -e PROGRESS_LOG=compact -e PROGRESS_STEP=20 \
  alexbic/youtube-downloader-api:latest

# Полные логи прогресса (для отладки)
docker run -d -p 5000:5000 \
  -e PROGRESS_LOG=full -e LOG_LEVEL=DEBUG \
  alexbic/youtube-downloader-api:latest
```

---

## Решение проблем

### Частые проблемы

#### 1. YouTube блокирует загрузку

**Проблема:** `Sign in to confirm you're not a bot` или `Private video`

**Решения:**
- Используйте cookies из приватного/инкогнито окна (см. секцию "Запуск с cookies")
- Добавьте задержку 5-10 секунд между запросами
- Рассмотрите использование PO Token для современных видео
- Проверьте, не является ли видео приватным/удалённым/с возрастным ограничением

#### 2. Redis не подключается

**Проблема:** `Could not connect to Redis`

**Решения:**
- Проверьте переменные `REDIS_HOST` и `REDIS_PORT`
- Убедитесь что контейнер Redis запущен: `docker ps | grep redis`
- API автоматически переключается на режим памяти если Redis недоступен
- Для multi-worker режима (2+ workers) требуется Redis

#### 3. Файлы не найдены после загрузки

**Проблема:** `404 File not found`

**Решения:**
- Файлы автоматически удаляются после истечения TTL (по умолчанию: 3600 секунд)
- Проверьте настройку `CLEANUP_TTL_SECONDS`
- Скачивайте сразу после `status: "completed"`
- Установите `CLEANUP_TTL_SECONDS=0` чтобы отключить автоудаление

#### 4. Webhook не получен

**Проблема:** Webhook payload не приходит

**Решения:**
- Убедитесь что webhook URL доступен из контейнера
- API повторяет попытки 3 раза с интервалом 5 секунд
- Проверьте логи контейнера: `docker logs youtube-downloader`
- Убедитесь что webhook endpoint принимает POST запросы
- Используйте абсолютные URL (http/https)

#### 5. Прямая ссылка возвращает 403 Forbidden

**Проблема:** Прямая ссылка протухла или заблокирована

**Решения:**
- Прямые ссылки имеют ограниченный срок действия (несколько часов)
- Используйте `/download_video` для надёжного скачивания
- Скачивайте сразу после получения прямой ссылки
- Добавьте необходимые http_headers из ответа

#### 6. Ошибки аутентификации

**Проблема:** `401 Unauthorized` или `Invalid API key`

**Решения:**
- Если `API_KEY` задан, все защищённые endpoints требуют `Authorization: Bearer <key>`
- Защищённые endpoints: `/download_video`, `/get_direct_url`, `/get_video_info`
- Публичные endpoints (без авторизации): `/health`, `/task_status`, `/download`
- Если используется внутренний Docker режим, полностью уберите `API_KEY`

#### 7. Ошибки валидации client_meta

**Проблема:** `client_meta validation failed` или `client_meta too large`

**Решения:**
- Макс. размер: 16 КБ (JSON UTF-8)
- Макс. вложенность: 5 уровней
- Макс. количество ключей: 200 всего
- Макс. длина строки: 1000 символов
- Макс. длина списка: 200 элементов
- Используйте плоскую структуру когда возможно

### Логирование

**Просмотр логов контейнера:**
```bash
# Логи в реальном времени
docker logs -f youtube-downloader

# Последние 100 строк
docker logs --tail 100 youtube-downloader

# Логи с временными метками
docker logs -t youtube-downloader
```

**Уровни логирования:**
- `DEBUG` - подробное логирование включая опции yt-dlp
- `INFO` - стандартное логирование (по умолчанию)
- `WARNING` - только предупреждения
- `ERROR` - только ошибки
- `CRITICAL` - только критические ошибки

**Режимы логирования прогресса:**
- `off` (по умолчанию) - без спама прогресса
- `compact` - компактный прогресс каждые N% (настраивается через `PROGRESS_STEP`)
- `full` - подробный прогресс yt-dlp (очень многословно)

---

## Troubleshooting для n8n

### Ошибка: "Cannot create a string longer than 0x1fffffe8 characters"

**Причина**: n8n работает в режиме `binaryDataMode: "default"`, который хранит бинарные данные в памяти. Для больших файлов (>500MB) память переполняется.

**Решение 1: Настроить n8n для работы с большими файлами (РЕКОМЕНДУЕТСЯ)**

Добавьте переменную окружения в ваш docker-compose.yml или docker run:

```yaml
# docker-compose.yml
services:
  n8n:
    environment:
      - N8N_DEFAULT_BINARY_DATA_MODE=filesystem
      # ... другие переменные
```

Или для docker run:
```bash
docker run -e N8N_DEFAULT_BINARY_DATA_MODE=filesystem ...
```

После этого перезапустите n8n. Теперь бинарные данные будут сохраняться на диск вместо памяти.

**Решение 2: Настройки HTTP Request node**

В ноде скачивания файла (Node 2):
1. Откройте настройки HTTP Request node
2. Найдите параметр **"Response Format"**
3. Измените с "String" на **"File"**
4. Убедитесь что указано "Binary Property": **data**

**⚠️ Важно**: Если вы используете queue mode в n8n, режим filesystem не поддерживается. В этом случае рассмотрите использование S3 (`N8N_DEFAULT_BINARY_DATA_MODE=s3`).

### Ошибка: "Invalid URL: /download_file/..."

**Причина**: Используется относительный путь вместо полного URL.

**Решение**: Используйте поле `task_download_url` из ответа статуса/синхронного запроса:
```
Правильно: {{ $json.task_download_url }}
Неправильно: {{ $json.task_download_path }}
```

### Ошибка: "HTTP Error 403: Forbidden"

**Причина**: YouTube блокирует прямые ссылки после истечения срока действия.

**Решение**: Используйте endpoint `/download_video` вместо `/get_direct_url`. Первый скачивает видео на сервер (и возвращает ссылку на сохранённый файл), второй даёт только прямую ссылку, которая может быстро протухать.

## Безопасность

- API не хранит персональные данные пользователей
- Загруженные файлы хранятся во временных папках
- Рекомендуется использовать за reverse proxy (nginx/traefik)
- Добавьте rate limiting для production использования

---

## Разработка

### Локальная сборка

```bash
git clone https://github.com/alexbic/youtube-downloader-api.git
cd youtube-downloader-api
docker build -t youtube-downloader:local .
docker run -p 5000:5000 youtube-downloader:local
```

### Локальный запуск (без Docker)

```bash
pip install -r requirements.txt
python app.py
```

---

## CI/CD

GitHub Actions автоматически собирает и публикует Docker образы при каждом push в `main`:

1. Собирает для платформ: linux/amd64, linux/arm64
2. Публикует на Docker Hub: `alexbic/youtube-downloader-api`
3. Публикует на GitHub Container Registry: `ghcr.io/alexbic/youtube-downloader-api`
4. Обновляет описание на Docker Hub

Статус сборки: [GitHub Actions](https://github.com/alexbic/youtube-downloader-api/actions)

---

## Технологии

- Python 3.11
- Flask 3.0.0
- yt-dlp (latest)
- FFmpeg
- Gunicorn
- Redis (опционально)
- Docker

---

## Лицензия

MIT License - см. файл [LICENSE](LICENSE)

---

## Поддержка

- GitHub: [@alexbic](https://github.com/alexbic)
- Issues: [GitHub Issues](https://github.com/alexbic/youtube-downloader-api/issues)

## Disclaimer

Этот инструмент предназначен для личного использования. Убедитесь, что вы соблюдаете условия использования YouTube и авторские права при скачивании контента.
