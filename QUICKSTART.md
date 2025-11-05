# Быстрый старт

## Использование готового образа

Ваш API уже опубликован на Docker Hub: **alexbic/youtube-downloader-api**

### Запуск

```bash
docker run -d -p 5000:5000 --name youtube-api alexbic/youtube-downloader-api:latest
```

### Проверка

```bash
# Health check
curl http://localhost:5000/health

# Получить информацию о видео
curl -X POST http://localhost:5000/get_video_info \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"}'
```

## Результаты

✅ GitHub репозиторий создан: https://github.com/alexbic/youtube-downloader-api
✅ Docker образ опубликован: https://hub.docker.com/r/alexbic/youtube-downloader-api
✅ GitHub Actions настроен и работает
✅ Автоматическая сборка при каждом push
✅ Поддержка платформ: linux/amd64, linux/arm64
✅ API протестирован и работает

## Что создано

1. **Локальный репозиторий**: `/Users/bic/dev/youtube-downloader-api/`
2. **GitHub репозиторий**: https://github.com/alexbic/youtube-downloader-api
3. **Docker Hub образ**: alexbic/youtube-downloader-api
4. **GitHub Actions**: автоматическая публикация
5. **Документация**: README.md, SETUP-GUIDE.md

## Доступные теги

- `latest` - последняя стабильная версия из main
- `main` - последняя версия из main ветки
- `main-<commit>` - конкретный коммит

## Автоматическая публикация

Каждый push в main автоматически:
1. Собирает Docker образ
2. Публикует на Docker Hub
3. Обновляет описание
4. Поддерживает multi-arch (amd64, arm64)

## Примеры использования

### Docker

```bash
# Базовый запуск
docker run -d -p 5000:5000 alexbic/youtube-downloader-api:latest

# С volume для загрузок
docker run -d -p 5000:5000 \
  -v $(pwd)/downloads:/app/downloads \
  alexbic/youtube-downloader-api:latest
```

### Docker Compose

```yaml
version: '3.8'
services:
  youtube-api:
    image: alexbic/youtube-downloader-api:latest
    ports:
      - "5000:5000"
    volumes:
      - ./downloads:/app/downloads
    restart: unless-stopped
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: youtube-api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: youtube-api
  template:
    metadata:
      labels:
        app: youtube-api
    spec:
      containers:
      - name: youtube-api
        image: alexbic/youtube-downloader-api:latest
        ports:
        - containerPort: 5000
---
apiVersion: v1
kind: Service
metadata:
  name: youtube-api
spec:
  selector:
    app: youtube-api
  ports:
  - port: 80
    targetPort: 5000
  type: LoadBalancer
```

## API Endpoints

### 1. Health Check
```bash
GET /health
```

### 2. Получить информацию о видео
```bash
POST /get_video_info
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID"
}
```

### 3. Получить прямую ссылку
```bash
POST /get_direct_url
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "quality": "best[height<=720]"
}
```

### 4. Скачать видео на сервер
```bash
POST /download_video
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "quality": "best[height<=720]"
}
```

## Обновление

```bash
# В локальном репозитории
git pull origin main
docker pull alexbic/youtube-downloader-api:latest
```

## Мониторинг

Проверить статус сборки:
https://github.com/alexbic/youtube-downloader-api/actions

Проверить образ на Docker Hub:
https://hub.docker.com/r/alexbic/youtube-downloader-api

## Следующие шаги

1. ⬜ Добавить аутентификацию (JWT/API keys)
2. ⬜ Добавить rate limiting
3. ⬜ Настроить мониторинг (Prometheus/Grafana)
4. ⬜ Добавить очистку старых файлов
5. ⬜ Добавить поддержку плейлистов
6. ⬜ Добавить WebSocket для прогресса загрузки
7. ⬜ Добавить S3 storage для файлов

## Поддержка

- GitHub Issues: https://github.com/alexbic/youtube-downloader-api/issues
- GitHub Discussions: https://github.com/alexbic/youtube-downloader-api/discussions

---

Проект готов к использованию! 🚀
