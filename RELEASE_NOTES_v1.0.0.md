# YouTube Downloader API — Release Notes v1.0.0 (2025-01-16)

**Open Source YouTube Video Downloader API** - Initial stable release.

---

## Highlights

### Core Features
- ✅ **Direct URL retrieval** - get YouTube direct links without downloading
- ✅ **Server-side downloads** - sync and async modes with quality selection
- ✅ **Video information** - complete metadata extraction
- ✅ **Webhook support** - POST callbacks on task completion
- ✅ **Redis integration** - multi-worker task storage
- ✅ **Cookie support** - bypass YouTube restrictions
- ✅ **Auto cleanup** - configurable TTL for task files

### Production Ready
- 🐳 **Docker multi-arch** - amd64, arm64 support
- 🔑 **Optional authentication** - Bearer token for public deployments
- 🌐 **URL flexibility** - internal and external URL support
- 📝 **Client metadata** - arbitrary JSON passthrough
- 🔄 **Auto retries** - webhook delivery with configurable attempts
- 🧹 **Cleanup system** - automatic task file deletion

---

## Features

### 1. Video Download Modes

**Sync mode:**
```json
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "quality": "best[height<=720]"
}
```
Returns immediately with download URL.

**Async mode:**
```json
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "async": true,
  "webhook_url": "https://your-webhook.com/callback"
}
```
Returns task_id for status polling, sends webhook on completion.

### 2. Direct URL Retrieval

Get YouTube direct links without server-side download:
```bash
POST /get_direct_url
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "quality": "best[height<=720]"
}
```

**Warning:** Direct URLs expire in a few hours.

### 3. Video Information

Extract complete video metadata:
```bash
POST /get_video_info
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID"
}
```

Returns: title, description, duration, views, likes, uploader, tags, etc.

### 4. Webhook Callbacks

Async tasks support webhook notifications:
- Configurable retry attempts (default: 3)
- Configurable retry interval (default: 5s)
- Configurable timeout (default: 8s)
- Best-effort delivery (errors don't fail main process)

### 5. Client Metadata

Pass arbitrary JSON through entire workflow:
```json
{
  "url": "...",
  "client_meta": {
    "user_id": 123,
    "project": "demo",
    "custom_field": "value"
  }
}
```

Returned in: responses, webhooks, metadata.json

**Limits:**
- Max size: 16 KB (JSON UTF-8)
- Max depth: 5 levels
- Max keys: 200 total
- Max string length: 1000 characters
- Max list length: 200 items

### 6. Cookie Support

Bypass YouTube restrictions with cookies:
- Automatic timestamp refresh before each request
- Support for Netscape cookie format
- Private/incognito window export recommended
- See documentation for detailed setup

### 7. File Storage

```
/app/tasks/{task_id}/
  ├── video_*.mp4       # Downloaded video
  └── metadata.json     # Task metadata
```

**Cleanup:**
- TTL controlled by `CLEANUP_TTL_SECONDS` (default: 3600s)
- Set to `0` to disable cleanup
- Deletes entire task directory after TTL

---

## Configuration

### Environment Variables (25 Total)

| Category | Variables |
|----------|-----------|
| **Authentication & URLs** | API_KEY, PUBLIC_BASE_URL, INTERNAL_BASE_URL |
| **Worker Configuration** | WORKERS, GUNICORN_TIMEOUT |
| **Redis Configuration** | REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_INIT_RETRIES, REDIS_INIT_DELAY_SECONDS |
| **Task Management** | CLEANUP_TTL_SECONDS |
| **Webhook Configuration** | WEBHOOK_RETRY_ATTEMPTS, WEBHOOK_RETRY_INTERVAL_SECONDS, WEBHOOK_TIMEOUT_SECONDS |
| **Logging** | LOG_LEVEL, PROGRESS_LOG, PROGRESS_STEP, LOG_YTDLP_OPTS, LOG_YTDLP_WARNINGS |
| **Client Metadata Limits** | MAX_CLIENT_META_BYTES, MAX_CLIENT_META_DEPTH, MAX_CLIENT_META_KEYS, MAX_CLIENT_META_STRING_LENGTH, MAX_CLIENT_META_LIST_LENGTH |

See [README.md](README.md) for complete table.

### Authentication Modes

**Internal mode (auth=disabled):**
- No `API_KEY` set
- No authentication required
- URLs built from `request.host_url` or `INTERNAL_BASE_URL`
- Suitable for Docker internal networks

**Public mode (auth=enabled):**
- Both `PUBLIC_BASE_URL` and `API_KEY` set
- Bearer authentication required: `Authorization: Bearer <key>`
- External URLs use `PUBLIC_BASE_URL`
- Internal URLs use `INTERNAL_BASE_URL`
- Suitable for public deployments behind reverse proxy

---

## API Endpoints

### Protected Endpoints (require auth if enabled)
- `POST /download_video` - Download video to server
- `POST /get_direct_url` - Get direct YouTube link
- `POST /get_video_info` - Get video metadata

### Public Endpoints (no auth)
- `GET /health` - Health check
- `GET /task_status/<task_id>` - Check task status
- `GET /download/<task_id>/<filename>` - Download file
- `GET /download/<task_id>/metadata.json` - Download metadata

---

## Docker Deployment

### Quick Start

```bash
docker pull alexbic/youtube-downloader-api:latest
docker run -d -p 5000:5000 alexbic/youtube-downloader-api:latest
```

### Production Setup (with Redis)

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
      PUBLIC_BASE_URL: https://yourdomain.com/api
      API_KEY: ${API_KEY}
      WORKERS: 2
      REDIS_HOST: redis
      REDIS_PORT: 6379
      CLEANUP_TTL_SECONDS: 3600
      PROGRESS_LOG: off
      LOG_LEVEL: INFO
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped
```

### Available Tags

- `latest` - latest stable version from main
- `main` - latest version from main branch
- `sha-<commit>` - specific commit
- Multi-arch: `amd64`, `arm64`

---

## Integration Examples

### Python

```python
import requests

# Download video (async)
response = requests.post('http://localhost:5000/download_video',
    headers={'Authorization': 'Bearer YOUR_API_KEY'},
    json={
        'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'async': True,
        'client_meta': {'user_id': 123}
    }
)

task_id = response.json()['task_id']

# Poll status
while True:
    status = requests.get(f'http://localhost:5000/task_status/{task_id}')
    data = status.json()

    if data['status'] == 'completed':
        print(f"Download URL: {data['task_download_url']}")
        break
    elif data['status'] == 'error':
        print(f"Error: {data['error_message']}")
        break

    time.sleep(2)
```

### JavaScript (Node.js)

```javascript
const axios = require('axios');

async function downloadVideo(url) {
  // Start download
  const response = await axios.post('http://localhost:5000/download_video', {
    url: url,
    async: true,
    client_meta: {project: 'demo'}
  }, {
    headers: {'Authorization': 'Bearer YOUR_API_KEY'}
  });

  const taskId = response.data.task_id;

  // Poll status
  while (true) {
    const status = await axios.get(`http://localhost:5000/task_status/${taskId}`);

    if (status.data.status === 'completed') {
      console.log('Download URL:', status.data.task_download_url);
      break;
    } else if (status.data.status === 'error') {
      console.error('Error:', status.data.error_message);
      break;
    }

    await new Promise(r => setTimeout(r, 2000));
  }
}
```

### n8n Workflow

**Configuration:**
1. Set `N8N_DEFAULT_BINARY_DATA_MODE=filesystem` in n8n docker-compose
2. Use HTTP Request node with "Response Format: File"
3. Set "Binary Property: data"

**Async workflow:**
1. POST to `/download_video` with `{"url":"...", "async":true}`
2. Poll `/task_status/{task_id}` until `status=completed`
3. Download from `task_download_url`

---

## Troubleshooting

### Common Issues

#### YouTube blocks downloads
- Use cookies from private/incognito window
- Add 5-10 second delay between requests
- Consider PO Token for modern videos

#### n8n "Cannot create a string longer than..." error
- Set `N8N_DEFAULT_BINARY_DATA_MODE=filesystem`
- Use "Response Format: File" in HTTP Request node

#### Direct URL returns 403 Forbidden
- Direct URLs expire in a few hours
- Use `/download_video` for reliable downloads

#### Files not found after download
- Files auto-delete after TTL (default: 3600s)
- Set `CLEANUP_TTL_SECONDS=0` to disable cleanup

#### Redis connection failed
- Check `REDIS_HOST` and `REDIS_PORT`
- API falls back to memory mode automatically

---

## Technology Stack

- Python 3.11
- Flask 3.0.0
- yt-dlp (latest)
- FFmpeg
- Gunicorn
- Redis (optional)
- Docker

---

## CI/CD

GitHub Actions automatically builds and publishes:
- Multi-arch Docker images (amd64, arm64)
- Docker Hub: `alexbic/youtube-downloader-api`
- GitHub Container Registry: `ghcr.io/alexbic/youtube-downloader-api`

Build status: [GitHub Actions](https://github.com/alexbic/youtube-downloader-api/actions)

---

## Statistics

**Configuration:**
- Environment variables: 25 total
- API endpoints: 6 (3 protected, 3 public)
- Supported platforms: amd64, arm64
- Languages: EN, RU (fully synchronized documentation)

**Limits:**
- Client metadata: 16 KB max
- Webhook retries: 3 attempts
- Cleanup TTL: 3600s default (configurable)

---

## Resources

- **GitHub Repository:** https://github.com/alexbic/youtube-downloader-api
- **Docker Hub:** https://hub.docker.com/r/alexbic/youtube-downloader-api
- **GitHub Container Registry:** https://github.com/alexbic/youtube-downloader-api/pkgs/container/youtube-downloader-api
- **Documentation:** [README.md](README.md) (English) | [README.ru.md](README.ru.md) (Russian)
- **License:** MIT License (see [LICENSE](LICENSE) file)
- **Issues:** https://github.com/alexbic/youtube-downloader-api/issues

---

## Next Steps

After deploying v1.0.0:

1. ✅ Configure authentication if needed (`PUBLIC_BASE_URL` + `API_KEY`)
2. ✅ Set up cookies for YouTube restrictions bypass
3. ✅ Configure cleanup TTL based on storage requirements
4. ✅ Set up Redis for multi-worker deployments
5. ✅ Configure webhooks for async workflows
6. ✅ Review troubleshooting guide for optimization tips

---

## Acknowledgments

Special thanks to:
- yt-dlp project for the excellent YouTube download library
- Flask community for the web framework
- All users who tested and provided feedback

---

**Thanks for using YouTube Downloader API!** 🎬✨

Questions? Open an issue on GitHub or check the comprehensive documentation in README.md.
