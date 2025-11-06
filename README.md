# YouTube Downloader API

Простой и мощный REST API для скачивания видео с YouTube и получения прямых ссылок на видеофайлы.

[![Docker Hub](https://img.shields.io/docker/v/alexbic/youtube-downloader-api?label=Docker%20Hub&logo=docker)](https://hub.docker.com/r/alexbic/youtube-downloader-api)
[![GitHub Container Registry](https://img.shields.io/badge/ghcr.io-image-blue?logo=github)](https://github.com/alexbic/youtube-downloader-api/pkgs/container/youtube-downloader-api)
[![Build Status](https://img.shields.io/github/actions/workflow/status/alexbic/youtube-downloader-api/docker-build.yml?branch=main)](https://github.com/alexbic/youtube-downloader-api/actions)

## Возможности

- Получение прямой ссылки на видео без загрузки на сервер
- Скачивание видео на сервер с выбором качества
- Получение полной информации о видео
- Поддержка различных форматов и качества
- Health check endpoint для мониторинга
- Автоматическая публикация на Docker Hub и GitHub Container Registry
- Поддержка платформ: linux/amd64, linux/arm64

## Установка

### Из Docker Hub

```bash
docker pull alexbic/youtube-downloader-api:latest
```

### Из GitHub Container Registry

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
```

### Запуск через Docker Compose

```yaml
version: '3.8'
services:
  youtube-downloader:
    image: alexbic/youtube-downloader-api:latest
    # или используйте GitHub Container Registry:
    # image: ghcr.io/alexbic/youtube-downloader-api:latest
    ports:
      - "5000:5000"
    volumes:
      - ./downloads:/app/downloads
    restart: unless-stopped
```

## API Endpoints

### 1. Health Check

```bash
GET /health
```

Ответ:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.123456"
}
```

### 2. Получить прямую ссылку на видео

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
  "success": true,
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
  "http_headers": {...},
  "expiry_warning": "URL expires in a few hours. Use immediately or call /download_video to save permanently.",
  "processed_at": "2024-01-15T10:30:00.123456"
}
```

**Важно:** Прямые ссылки имеют ограниченный срок действия и могут выдать 403 Forbidden при скачивании. Для гарантированного скачивания используйте `/download_direct` или `/download_video`.

### 3. Скачать видео напрямую (рекомендуется для n8n)

```bash
POST /download_direct
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "quality": "best[height<=720]"
}
```

Ответ:
```json
{
  "success": true,
  "video_id": "VIDEO_ID",
  "title": "Название видео",
  "filename": "video_20240115_103000.mp4",
  "file_path": "/app/downloads/video_20240115_103000.mp4",
  "file_size": 15728640,
  "download_url": "http://youtube_downloader:5000/download_file/video_20240115_103000.mp4",
  "download_path": "/download_file/video_20240115_103000.mp4",
  "duration": 180,
  "resolution": "1280x720",
  "ext": "mp4",
  "note": "Use download_url (full URL) or download_path (relative) to get the file. File will auto-delete after 1 hour.",
  "processed_at": "2024-01-15T10:30:00.123456"
}
```

**Обратите внимание**:
- `filename` короткое безопасное имя в формате `video_YYYYMMDD_HHMMSS.ext`
- Оригинальное название сохраняется в поле `title`
- Файлы сохраняются напрямую в `/app/downloads/` без дополнительных папок
- Файлы имеют правильные права доступа (644) для чтения из n8n
- `download_url` содержит полный URL для использования в n8n

Этот endpoint решает проблему 403 Forbidden. Скачивает видео на сервер и возвращает `download_url` для получения файла. Идеально для n8n и других инструментов автоматизации.

**Использование в n8n:**

**Шаг 0: Настройте n8n для работы с большими файлами**

Добавьте в docker-compose.yml вашего n8n стека:
```yaml
services:
  n8n:
    environment:
      - N8N_DEFAULT_BINARY_DATA_MODE=filesystem
```

Перезапустите n8n после изменения конфигурации.

**Шаг 1: HTTP Request Node (Получить URL)**
```
Method: POST
URL: http://youtube_downloader:5000/download_direct
Body: {"url": "https://youtube.com/watch?v=..."}
Response Format: JSON
```

**Шаг 2: HTTP Request Node (Скачать файл)**
```
Method: GET
URL: {{ $json.download_url }}
Response Format: File  ⚠️ ВАЖНО: Выберите "File", НЕ "String"!
Binary Property: data
```

**Критически важно**:
1. n8n должен быть настроен с `N8N_DEFAULT_BINARY_DATA_MODE=filesystem`
2. В Node 2 установите "Response Format" в значение "File"
3. Без правильной конфигурации n8n будет пытаться загрузить видео в память и выдаст ошибку "Cannot create a string longer than 0x1fffffe8 characters"

API автоматически вернёт полный URL с правильным хостом (например: `http://youtube_downloader:5000/download_file/video_20240115_103000.mp4`)

### 5. Скачать видео на сервер

```bash
POST /download_video
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "quality": "best[height<=720]"
}
```

Ответ:
```json
{
  "success": true,
  "video_id": "VIDEO_ID",
  "title": "Название видео",
  "filename": "video.mp4",
  "file_path": "/app/downloads/tmp123/video.mp4",
  "file_size": 15728640,
  "download_url": "/download_file/tmp123/video.mp4",
  "duration": 180,
  "processed_at": "2024-01-15T10:30:00.123456"
}
```

### 6. Скачать файл с сервера

```bash
GET /download_file/<filename>
```

Возвращает файл для скачивания. Пример: `/download_file/video_20240115_103000.mp4`

### 7. Получить информацию о видео

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
  "success": true,
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
# Получить прямую ссылку
curl -X POST http://localhost:5000/get_direct_url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# Скачать видео
curl -X POST http://localhost:5000/download_video \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "quality": "best[height<=480]"}'

# Получить информацию
curl -X POST http://localhost:5000/get_video_info \
  -H "Content-Type: application/json" \
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
docker build -t youtube-downloader-api .
docker run -p 5000:5000 youtube-downloader-api
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

**Решение**: Используйте поле `download_url` из ответа, а не `download_path`:
```
Правильно: {{ $json.download_url }}
Неправильно: {{ $json.download_path }}
```

### Ошибка: "HTTP Error 403: Forbidden"

**Причина**: YouTube блокирует прямые ссылки после истечения срока действия.

**Решение**: Используйте endpoint `/download_direct` вместо `/get_direct_url`. Первый скачивает видео на сервер, второй дает только прямую ссылку.

## Безопасность

- API не хранит персональные данные пользователей
- Загруженные файлы хранятся во временных папках
- Рекомендуется использовать за reverse proxy (nginx/traefik)
- Добавьте rate limiting для production использования

## Лицензия

MIT License

## Поддержка

Если возникли проблемы:
1. Проверьте логи контейнера: `docker logs <container_id>`
2. Убедитесь что URL видео доступен
3. Проверьте наличие свободного места для загрузок
4. Создайте issue в GitHub repository

## TODO

- [ ] Добавить аутентификацию
- [ ] Добавить rate limiting
- [ ] Добавить очистку старых файлов
- [ ] Добавить поддержку плейлистов
- [ ] Добавить webhook уведомления
- [ ] Добавить queue для больших загрузок

## Автор

Создано с использованием yt-dlp и Flask

## Disclaimer

Этот инструмент предназначен для личного использования. Убедитесь, что вы соблюдаете условия использования YouTube и авторские права при скачивании контента.
