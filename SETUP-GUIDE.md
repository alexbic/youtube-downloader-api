# Полное руководство по настройке и публикации

## Шаг 1: Создание репозитория на GitHub

1. Перейдите на [GitHub](https://github.com) и войдите в аккаунт
2. Нажмите "New repository" (зеленая кнопка)
3. Заполните данные:
   - Repository name: `youtube-downloader-api`
   - Description: `REST API для скачивания YouTube видео с Docker и GitHub Actions`
   - Выберите Public (для публичного Docker Hub образа)
   - НЕ добавляйте README, .gitignore или лицензию (они уже созданы)
4. Нажмите "Create repository"

## Шаг 2: Настройка Docker Hub

1. Создайте аккаунт на [Docker Hub](https://hub.docker.com) (если еще нет)
2. Войдите в аккаунт
3. Перейдите в Account Settings → Security
4. Нажмите "New Access Token"
5. Заполните:
   - Token description: `github-actions-youtube-downloader`
   - Access permissions: `Read, Write, Delete`
6. Нажмите "Generate"
7. **ВАЖНО:** Скопируйте токен (он больше не будет показан!)

## Шаг 3: Добавление секретов в GitHub

1. Откройте ваш GitHub репозиторий
2. Перейдите в Settings → Secrets and variables → Actions
3. Нажмите "New repository secret"
4. Добавьте первый секрет:
   - Name: `DOCKER_USERNAME`
   - Secret: ваш Docker Hub username (например: `alexbic`)
5. Нажмите "Add secret"
6. Добавьте второй секрет:
   - Name: `DOCKER_TOKEN`
   - Secret: скопированный Access Token из Docker Hub
7. Нажмите "Add secret"

## Шаг 4: Связывание локального репозитория с GitHub

```bash
# Перейдите в директорию проекта
cd /Users/bic/dev/youtube-downloader-api

# Переименуйте ветку в main (если нужно)
git branch -M main

# Добавьте remote (замените ВАШЕ_ИМЯ на ваш GitHub username)
git remote add origin https://github.com/ВАШЕ_ИМЯ/youtube-downloader-api.git

# Отправьте код на GitHub
git push -u origin main
```

Пример для пользователя `alexbic`:
```bash
git remote add origin https://github.com/alexbic/youtube-downloader-api.git
git push -u origin main
```

## Шаг 5: Проверка автоматической сборки

1. После push в GitHub, перейдите на вкладку "Actions" в вашем репозитории
2. Вы увидите запущенный workflow "Build and Push Docker Image"
3. Кликните на него чтобы увидеть прогресс
4. Сборка займет 5-10 минут
5. После успешной сборки, образ появится на Docker Hub

## Шаг 6: Проверка на Docker Hub

1. Перейдите на [Docker Hub](https://hub.docker.com)
2. Откройте ваш профиль
3. Вы увидите новый репозиторий: `ваше_имя/youtube-downloader-api`
4. Откройте его и проверьте:
   - Есть ли теги `latest`, `main`
   - Обновилось ли описание из README.md
   - Есть ли поддержка платформ: `linux/amd64`, `linux/arm64`

## Шаг 7: Тестирование Docker образа

```bash
# Скачайте образ (замените на ваш username)
docker pull alexbic/youtube-downloader-api:latest

# Запустите контейнер
docker run -d -p 5000:5000 --name yt-api alexbic/youtube-downloader-api:latest

# Проверьте что работает
curl http://localhost:5000/health

# Тест получения прямой ссылки
curl -X POST http://localhost:5000/get_direct_url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# Остановите и удалите контейнер
docker stop yt-api
docker rm yt-api
```

## Структура проекта

```
youtube-downloader-api/
├── .github/
│   └── workflows/
│       └── docker-build.yml    # GitHub Actions workflow
├── .dockerignore               # Исключения для Docker build
├── .gitignore                  # Исключения для Git
├── Dockerfile                  # Конфигурация Docker образа
├── app.py                      # Flask приложение
├── requirements.txt            # Python зависимости
├── README.md                   # Документация
└── SETUP-GUIDE.md             # Это руководство
```

## Автоматическая публикация

Теперь каждый раз когда вы делаете push в ветку `main`:
1. GitHub Actions автоматически запустит сборку
2. Соберет Docker образ для двух платформ (amd64, arm64)
3. Опубликует на Docker Hub с тегами:
   - `latest` - для последней версии из main
   - `main` - для main ветки
   - Другие теги для версий и PR

## Ручная сборка локально (опционально)

```bash
# Сборка образа
docker build -t youtube-downloader-api .

# Запуск
docker run -d -p 5000:5000 youtube-downloader-api

# Тегирование для Docker Hub
docker tag youtube-downloader-api alexbic/youtube-downloader-api:latest

# Публикация (требуется docker login)
docker login
docker push alexbic/youtube-downloader-api:latest
```

## Обновление версии

### Способ 1: Commit в main
```bash
# Внесите изменения в код
git add .
git commit -m "feat: добавлена новая функция"
git push origin main
# Автоматически соберется и опубликуется
```

### Способ 2: Версионные теги
```bash
# Создайте тег версии
git tag v1.0.0
git push origin v1.0.0
# Соберется с тегами: v1.0.0, v1.0, v1, latest
```

## Устранение проблем

### Ошибка: "Authentication required"
- Проверьте что добавили `DOCKER_USERNAME` и `DOCKER_TOKEN` в GitHub Secrets
- Убедитесь что токен актуален (не истек)

### Ошибка: "Permission denied"
- Проверьте права доступа Docker Hub токена (должны быть Read, Write)

### Сборка зависла или долго выполняется
- Первая сборка может занять 10-15 минут
- Последующие сборки будут быстрее благодаря кешу

### Образ не появляется на Docker Hub
- Проверьте логи в GitHub Actions
- Убедитесь что workflow завершился успешно (зеленая галочка)

## Полезные команды

```bash
# Посмотреть статус git
git status

# Посмотреть логи
git log --oneline

# Посмотреть remote
git remote -v

# Посмотреть все ветки
git branch -a

# Посмотреть теги
git tag

# Посмотреть Docker образы локально
docker images

# Посмотреть запущенные контейнеры
docker ps

# Посмотреть логи контейнера
docker logs yt-api

# Войти в контейнер
docker exec -it yt-api bash
```

## Следующие шаги

1. ✅ Создали проект
2. ✅ Настроили Docker
3. ✅ Настроили GitHub Actions
4. ✅ Опубликовали на Docker Hub
5. ⬜ Добавьте аутентификацию
6. ⬜ Добавьте rate limiting
7. ⬜ Настройте мониторинг
8. ⬜ Добавьте автоматическую очистку старых файлов

## Поддержка

Если что-то не работает:
1. Проверьте все шаги по порядку
2. Посмотрите логи в GitHub Actions
3. Проверьте настройки секретов
4. Убедитесь что Docker Hub токен актуален

Готово! Ваш API теперь автоматически публикуется на Docker Hub при каждом push в main.
