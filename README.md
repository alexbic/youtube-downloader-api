# YouTube Downloader API

**Open Source** REST API for downloading YouTube videos and getting direct video links using yt-dlp.

[![Docker Hub](https://img.shields.io/docker/v/alexbic/youtube-downloader-api?label=Docker%20Hub&logo=docker)](https://hub.docker.com/r/alexbic/youtube-downloader-api)
[![GitHub Container Registry](https://img.shields.io/badge/ghcr.io-image-blue?logo=github)](https://github.com/alexbic/youtube-downloader-api/pkgs/container/youtube-downloader-api)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-1.0.0-blue)](docs/RELEASE_NOTES_v1.0.0.md)
[![Changelog](https://img.shields.io/badge/changelog-1.0.0-blue)](docs/CHANGELOG.md)

> ⚠️ **PUBLIC VERSION**: This is the free, limited version with hardcoded limits (2 workers, 24h TTL, 256MB Redis).
> 🚀 **Want more?** Check out [YouTube Downloader API Pro](https://github.com/alexbic/youtube-downloader-api-pro) - PostgreSQL storage, configurable TTL, processing results cache, and more!

**English** | [Русский](README.ru.md)

---

## Features

- 🎬 **Direct URL retrieval** - get direct video links without downloading
- ⬇️ **Server-side downloads** - download videos to server with quality selection (sync/async)
- 📊 **Video information** - get complete metadata
- 🔄 **Sync and async modes** - choose between immediate or background processing
- 🔗 **Webhook support** - POST notifications on task completion with automatic retries
- 🔁 **Webhook resender** - background service retries failed webhooks every 15 minutes
- 🔑 **Optional authentication** - Bearer token support for public deployments
- 🌐 **Absolute URLs** - internal and external URL support
- 📦 **Redis support** - multi-worker task storage (built-in embedded Redis)
- 🔒 **Cookie support** - bypass YouTube restrictions
- 🧹 **Auto cleanup** - automatic file deletion after 24 hours (fixed in public version)
- 🐳 **Docker ready** - multi-arch support (amd64, arm64)
- 📝 **Client metadata** - pass arbitrary JSON through the entire workflow

---

## Quick Start

### From Docker Hub (Public Version)

**Public version features:**
- ✅ Standalone container with built-in Redis
- ✅ Fixed limits: 2 workers, 24h TTL, 256MB Redis
- ✅ No external dependencies
- ⚠️ Not configurable (for flexible setup, use Pro version)

```bash
docker pull alexbic/youtube-downloader-api:latest
docker run -d -p 5000:5000 --name yt-downloader alexbic/youtube-downloader-api:latest
```

### Test the API

```bash
# Health check
curl http://localhost:5000/health

# Download video (sync)
curl -X POST http://localhost:5000/download_video \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# Get direct URL
curl -X POST http://localhost:5000/get_direct_url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

---

## Installation

### Docker Compose (Custom Setup)

> ⚠️ **Note**: The public version has embedded Redis. This example is for custom deployments only.

```yaml
version: '3.8'
services:
  youtube-downloader:
    image: alexbic/youtube-downloader-api:latest
    ports:
      - "5000:5000"
    volumes:
      - ./tasks:/app/tasks
      # - ./cookies.txt:/app/cookies.txt  # optional
    environment:
      # Public base URL for external links (https://yourdomain.com/api)
      PUBLIC_BASE_URL: ${PUBLIC_BASE_URL}
      # API Key for authentication (Bearer token)
      API_KEY: ${API_KEY}
    restart: unless-stopped
```

### Local Development

```bash
git clone https://github.com/alexbic/youtube-downloader-api.git
cd youtube-downloader-api
pip install -r requirements.txt
python app.py
```

---

## API Endpoints

### 1. Health Check

```bash
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.123456",
  "auth": "enabled|disabled",
  "storage": "redis|memory"
}
```

### 2. Download Video (Sync/Async)

```bash
POST /download_video
Content-Type: application/json
```

**Request (async):**
```json
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "async": true,
  "quality": "best[height<=720]",
  "webhook_url": "https://your-webhook.com/callback",
  "client_meta": {"user_id": 123, "project": "demo"}
}
```

**Request (sync):**
```json
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "quality": "best[height<=720]",
  "client_meta": {"user_id": 123}
}
```

**Parameters:**
- `url` (required, string) - YouTube video URL
- `async` (optional, boolean) - async mode (default: false)
- `quality` (optional, string) - video quality (default: `best[height<=720]`)
  - `best[height<=480]` - 480p
  - `best[height<=720]` - 720p
  - `best[height<=1080]` - 1080p
  - `best` - maximum quality
- `webhook_url` (optional, string) - webhook callback URL (async mode)
- `client_meta` (optional, object) - arbitrary JSON metadata (max 16KB)
- `cookiesFromBrowser` (optional, string) - browser to extract cookies from (chrome/firefox/safari/edge, local only)

**Response (sync):**
```json
{
  "task_id": "abc123...",
  "status": "completed",
  "video_id": "VIDEO_ID",
  "title": "Video Title",
  "filename": "video_20250116_120000.mp4",
  "file_size": 15728640,
  "download_endpoint": "/download/abc123.../video_20250116_120000.mp4",
  "storage_rel_path": "abc123.../video_20250116_120000.mp4",
  "task_download_url": "http://public.example.com/download/abc123.../video_20250116_120000.mp4",
  "task_download_url_internal": "http://service.local:5000/download/abc123.../video_20250116_120000.mp4",
  "metadata_url": "http://public.example.com/download/abc123.../metadata.json",
  "metadata_url_internal": "http://service.local:5000/download/abc123.../metadata.json",
  "duration": 180,
  "resolution": "1280x720",
  "ext": "mp4",
  "processed_at": "2025-01-16T12:00:00.123456",
  "client_meta": {"user_id": 123}
}
```

**Response (async):**
```json
{
  "task_id": "abc123...",
  "status": "processing",
  "check_status_url": "http://public.example.com/task_status/abc123...",
  "check_status_url_internal": "http://service.local/task_status/abc123...",
  "metadata_url": "http://public.example.com/download/abc123.../metadata.json",
  "metadata_url_internal": "http://service.local/download/abc123.../metadata.json",
  "client_meta": {"user_id": 123}
}
```

**Important:** In async mode, errors (private video, deleted, blocked, etc.) are returned only via `/task_status/<task_id>`. The initial POST response always contains only task_id and status.

### 3. Get Task Status

```bash
GET /task_status/<task_id>
```

**Response (processing):**
```json
{
  "task_id": "abc123...",
  "status": "processing"
}
```

**Response (completed):**
```json
{
  "task_id": "abc123...",
  "status": "completed",
  "video_id": "VIDEO_ID",
  "title": "Video Title",
  "filename": "video_20250116_120000.mp4",
  "file_size": 15728640,
  "download_endpoint": "/download/abc123.../video_20250116_120000.mp4",
  "storage_rel_path": "abc123.../video_20250116_120000.mp4",
  "task_download_url": "http://public.example.com/download/abc123.../video_20250116_120000.mp4",
  "task_download_url_internal": "http://service.local:5000/download/abc123.../video_20250116_120000.mp4",
  "metadata_url": "http://public.example.com/download/abc123.../metadata.json",
  "metadata_url_internal": "http://service.local:5000/download/abc123.../metadata.json",
  "duration": 180,
  "resolution": "1280x720",
  "ext": "mp4",
  "created_at": "2025-01-16T12:00:00.123456",
  "completed_at": "2025-01-16T12:00:10.123456",
  "expires_at": "2025-01-17T12:00:00.123456",
  "client_meta": {"user_id": 123}
}
```

**Response (error):**
```json
{
  "task_id": "abc123...",
  "status": "error",
  "operation": "download_video_async",
  "error_type": "private_video|unavailable|deleted|...",
  "error_message": "Error description",
  "user_action": "Recommended action",
  "raw_error": "...",
  "failed_at": "2025-01-16T12:00:00.123456",
  "client_meta": {"user_id": 123}
}
```

### 4. Download File or Metadata

```bash
GET /download/<task_id>/<filename>
GET /download/<task_id>/metadata.json
```

### 5. Get Direct URL

```bash
POST /get_direct_url
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "quality": "best[height<=720]"
}
```

**Response:**
```json
{
  "video_id": "VIDEO_ID",
  "title": "Video Title",
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

**Warning:** Direct URLs have limited lifetime and may return 403 Forbidden. For reliable downloads, use `/download_video`.

### 6. Get Video Info

```bash
POST /get_video_info
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID"
}
```

**Response:**
```json
{
  "video_id": "VIDEO_ID",
  "title": "Video Title",
  "description": "Description...",
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

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| **Authentication & URLs** |||
| `API_KEY` | — | Enables public mode (Bearer required). When unset, internal mode (no auth). |
| `PUBLIC_BASE_URL` | — | External base for absolute URLs (https://domain.com/api). Used only if `API_KEY` is set. |
| `INTERNAL_BASE_URL` | — | Base for background URL generation (webhooks, Docker network). |
| **Worker Configuration** |||
| ~~`WORKERS`~~ | `2` | ❌ **Not configurable** in public version. Fixed at 2 workers. |
| `GUNICORN_TIMEOUT` | `300` | Gunicorn timeout (seconds). |
| **Redis Configuration** |||
| ~~`REDIS_HOST`~~ | `localhost` | ❌ **Not configurable** in public version. Embedded Redis. |
| ~~`REDIS_PORT`~~ | `6379` | ❌ **Not configurable** in public version. Embedded Redis. |
| ~~`REDIS_DB`~~ | `0` | ❌ **Not configurable** in public version. Embedded Redis. |
| ~~`REDIS_INIT_RETRIES`~~ | `10` | ❌ **Not configurable** in public version. Embedded Redis. |
| ~~`REDIS_INIT_DELAY_SECONDS`~~ | `1` | ❌ **Not configurable** in public version. Embedded Redis. |
| **Task Management** |||
| ~~`CLEANUP_TTL_SECONDS`~~ | `86400` | ❌ **Not configurable** in public version. Fixed at 24 hours. |
| **Webhook Configuration** |||
| `WEBHOOK_RETRY_ATTEMPTS` | `3` | Max webhook delivery attempts (immediate retries on error). |
| `WEBHOOK_RETRY_INTERVAL_SECONDS` | `5` | Delay between immediate webhook retries (seconds). |
| `WEBHOOK_TIMEOUT_SECONDS` | `8` | Webhook request timeout (seconds). |
| ~~`WEBHOOK_BACKGROUND_INTERVAL_SECONDS`~~ | `900` | ❌ **Not configurable** in public version. Background resender scans every 15 minutes (fixed). |
| `DEFAULT_WEBHOOK_URL` | — | Fallback webhook URL (async). Used when request has no `webhook_url`. Must start with http(s)://, < 2048 chars. |
| `WEBHOOK_HEADERS` | — | Extra headers for webhook POST. JSON object or list: `{"Authorization":"Bearer XXX","X-Source":"ytdl"}` OR `Authorization: Bearer XXX; X-Source: ytdl`. Sensitive headers (Authorization, X-API-Key, X-Auth-Token) masked in startup logs. |
| **Logging** |||
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). |
| `PROGRESS_LOG` | `off` | yt-dlp progress logging (off, compact, full). |
| `PROGRESS_STEP` | `10` | Progress step in % for compact mode. |
| `LOG_YTDLP_OPTS` | `false` | Log yt-dlp options (debug). |
| `LOG_YTDLP_WARNINGS` | `false` | Forward yt-dlp warnings to app logs. |
| **Client Metadata Limits** |||
| `MAX_CLIENT_META_BYTES` | `16384` | Max size for `client_meta` (bytes). |
| `MAX_CLIENT_META_DEPTH` | `5` | Max nesting depth for `client_meta`. |
| `MAX_CLIENT_META_KEYS` | `200` | Max keys in `client_meta` object. |
| `MAX_CLIENT_META_STRING_LENGTH` | `1000` | Max string value length. |
| `MAX_CLIENT_META_LIST_LENGTH` | `200` | Max list length. |

### URL Configuration

**Internal mode (auth=disabled):**
- No `API_KEY` and no `PUBLIC_BASE_URL`
- URLs built from `request.host_url` or `INTERNAL_BASE_URL`
- No authentication required

**Public mode (auth=enabled):**
- Both `PUBLIC_BASE_URL` and `API_KEY` are set
- External URLs use `PUBLIC_BASE_URL`
- Internal URLs use `INTERNAL_BASE_URL` or `request.host_url`
- Authentication required: `Authorization: Bearer <API_KEY>`

### File Storage

```
/app/tasks/{task_id}/
  ├── video_*.mp4       # Downloaded video files (TTL: 24 hours in public version)
  └── metadata.json     # Task metadata (TTL: 24 hours in public version)
```

**Cleanup (Public Version):**
- ⚠️ **Fixed at 24 hours** - not configurable in public version
- Files automatically deleted 24 hours after download
- For configurable TTL, use [YouTube Downloader API Pro](https://github.com/alexbic/youtube-downloader-api-pro)

### Webhook Resender

The public version includes a **background webhook resender service** that automatically retries failed webhook deliveries:

**How it works:**
- Scans all tasks every **15 minutes** (fixed interval, not configurable)
- Retries webhooks for tasks with status `completed` or `error` that haven't received successful delivery (HTTP 200-299)
- Continues retrying until task is deleted by TTL cleanup (24 hours)
- Webhook URL is persisted in task metadata (`webhook_url` field in `/task/{task_id}` response)

**Delivery attempts:**
1. **Immediate retries**: 3 attempts with 5-second intervals (on task completion)
2. **Background retries**: Every 15 minutes until successful or TTL expires

**Configuration:**
- Use `DEFAULT_WEBHOOK_URL` to set fallback webhook for all async tasks without explicit `webhook_url`
- Use `WEBHOOK_HEADERS` to add authentication headers: `{"Authorization": "Bearer XXX"}`
- Monitor webhook delivery in logs (set `LOG_LEVEL=DEBUG` for detailed webhook payload preview)

**Example with default webhook:**
```yaml
environment:
  DEFAULT_WEBHOOK_URL: "https://your-server.com/webhooks/ytdl"
  WEBHOOK_HEADERS: '{"Authorization": "Bearer secret123"}'
```

---

## Cookies Setup (YouTube Restrictions Bypass)

YouTube may block downloads requiring authentication. Use cookies to bypass this.

**Important:**
- YouTube rotates cookies in regular browser tabs
- Export cookies from **private/incognito window** using special method

### Method 1: Browser Extension (Recommended)

**Step 1: Enable extension in incognito mode**

**Chrome:**
1. Open `chrome://extensions/`
2. Find [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
3. Click **"Details"**
4. Enable **"Allow in incognito"**

**Firefox:**
1. Open `about:addons`
2. Find [cookies.txt](https://addons.mozilla.org/en/firefox/addon/cookies-txt/)
3. Enable **"Run in Private Windows"**

**Step 2: Export cookies**

1. Open **new private/incognito window** and log in to YouTube
2. Navigate to `https://www.youtube.com/robots.txt`
3. Export cookies for `youtube.com` using the extension
4. **Immediately close** the private window

### Method 2: DevTools (No Extension)

1. Open **new private/incognito window** and log in to YouTube
2. Navigate to `https://www.youtube.com/robots.txt`
3. Open **DevTools** (F12 or Cmd+Option+I)
4. Go to **Console** tab
5. Copy and execute:

```javascript
copy(document.cookie.split('; ').map(c => {
  const [name, ...v] = c.split('=');
  return `.youtube.com\tTRUE\t/\tTRUE\t0\t${name}\t${v.join('=')}`;
}).join('\n'))
```

6. Cookies copied to clipboard - paste into `cookies.txt`
7. **Add to file start:** `# Netscape HTTP Cookie File`
8. **Immediately close** the private window

### Using Cookies

1. Place `cookies.txt` next to `docker-compose.yml`
2. Uncomment volume in compose:

```yaml
volumes:
  - ./cookies.txt:/app/cookies.txt
```

3. Restart: `docker-compose up -d`

**Done!** API automatically uses cookies and updates timestamp before each request.

### PO Token (Modern Videos)

YouTube is gradually requiring "PO Token" for downloads. If cookies don't help:
- Check [PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)
- Recommended: use `mweb` client with PO Token
- Some formats may be unavailable without token

**Additional Resources:**
- [Export YouTube Cookies Guide](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)
- [Common YouTube Errors](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#common-youtube-errors)
- Recommended: 5-10 second delay between requests
- Rate limits: ~300 videos/hour (guests), ~2000 videos/hour (accounts)

---

## Webhook Support

If `webhook_url` is provided in `POST /download_video`, the service POSTs to the URL on task completion.

### Default Webhook URL

Set `DEFAULT_WEBHOOK_URL` to avoid specifying `webhook_url` in every async request:

```yaml
environment:
  DEFAULT_WEBHOOK_URL: "https://hooks.internal/downloader"
```

If the request body omits `webhook_url`, the fallback is used. If both are set, the explicit `webhook_url` in the request overrides the default.

Validation rules:
- Must start with `http://` or `https://`
- Length < 2048 chars
- Applied only for async tasks (`"async": true`)

### Custom Webhook Headers

Use `WEBHOOK_HEADERS` to inject auth or tracing headers into every webhook POST without modifying client requests.

Allowed formats:
1. JSON object (preferred)
   ```bash
   WEBHOOK_HEADERS='{"Authorization":"Bearer abc123","X-Source":"ytdl"}'
   ```
2. Delimited list (`;`, `,` or newlines)
   ```bash
   WEBHOOK_HEADERS='Authorization: Bearer abc123; X-Source: ytdl'
   ```

Parsing rules:
- Each entry: `Key: Value` or `Key=Value`
- Quotes around values are stripped
- Invalid fragments are ignored silently
- `Content-Type` in `WEBHOOK_HEADERS` is ignored (service always sends `application/json`)

Security & Observability:
- Startup logs mask values for headers: `Authorization`, `X-API-Key`, `X-Auth-Token`
- Use HTTPS for external endpoints
- Prefer secrets/secure env injection for tokens (Docker secrets, orchestrator vaults)

### Per-Request Webhook Headers

You can specify custom headers for a specific webhook using the `webhook_headers` parameter in the request body. These headers override global `WEBHOOK_HEADERS` for that specific webhook.

```json
{
  "url": "https://youtube.com/watch?v=...",
  "async": true,
  "webhook_url": "https://your-webhook.com/endpoint",
  "webhook_headers": {
    "X-API-Key": "your-secret-key",
    "Authorization": "Bearer token123",
    "X-Custom-Header": "custom-value"
  }
}
```

Validation rules:
- Must be a JSON object/dict with string keys and values
- Header name max length: 256 characters
- Header value max length: 2048 characters
- `Content-Type` is always `application/json` and cannot be overridden
- Priority: per-request `webhook_headers` > global `WEBHOOK_HEADERS`

Use cases:
- Different API keys for different webhooks
- Request-specific authorization tokens
- Custom tracing/correlation IDs
- Client-specific identification headers

Example docker-compose override:
```yaml
services:
  youtube-downloader:
    environment:
      DEFAULT_WEBHOOK_URL: "http://webhook:9001/webhook"
      WEBHOOK_HEADERS: '{"Authorization":"Bearer local-test-token","X-Source":"ytdl"}'
```

Resulting webhook request headers (simplified):
```
Content-Type: application/json
Authorization: Bearer local-test-token
X-Source: ytdl
```

Note: Delivery uses retry policy (`WEBHOOK_RETRY_ATTEMPTS`, `WEBHOOK_RETRY_INTERVAL_SECONDS`, `WEBHOOK_TIMEOUT_SECONDS`). Failures never abort the main download process.

**Success payload:**
```json
{
  "task_id": "...",
  "status": "completed",
  "video_id": "...",
  "title": "...",
  "filename": "...mp4",
  "download_endpoint": "/download/.../...mp4",
  "storage_rel_path": ".../...mp4",
  "duration": 213,
  "resolution": "640x360",
  "ext": "mp4",
  "created_at": "2025-01-16T06:18:46.629918",
  "completed_at": "2025-01-16T06:18:56.338989",
  "expires_at": "2025-01-17T06:18:46.629918",
  "task_download_url_internal": "http://service.local:5000/download/...",
  "metadata_url_internal": "http://service.local:5000/download/.../metadata.json",
  "client_meta": {"your":"meta"},
  "webhook": {
    "url": "http://n8n:5678/webhook/...",
    "headers": {"X-API-Key": "secret123"},
    "status": "delivered",
    "attempts": 1,
    "last_attempt": "2025-01-16T06:18:56.500000",
    "last_status": 200,
    "last_error": null,
    "next_retry": null
  }
}
```

**Error payload:**
```json
{
  "task_id": "...",
  "status": "error",
  "operation": "download_video_async",
  "error_type": "private_video|unavailable|deleted|...",
  "error_message": "...",
  "user_action": "...",
  "failed_at": "2025-01-16T06:20:00.000000",
  "client_meta": {"your":"meta"}
}
```

**Configuration:**
- `webhook_url` must start with http(s):// and be < 2048 characters
- Timeout: `WEBHOOK_TIMEOUT_SECONDS` (default: 8s)
- Retry attempts: `WEBHOOK_RETRY_ATTEMPTS` (default: 3)
- Retry interval: `WEBHOOK_RETRY_INTERVAL_SECONDS` (default: 5s)
- Delivery is best-effort (errors don't fail the main process)

---

## Integration Examples

### cURL

```bash
# Get direct URL (no auth)
curl -X POST http://localhost:5000/get_direct_url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# With auth (Bearer)
curl -X POST http://localhost:5000/get_direct_url \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# Download video
curl -X POST http://localhost:5000/download_video \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "quality": "best[height<=480]"}'
```

### Python

```python
import requests

# Get direct URL
response = requests.post('http://localhost:5000/get_direct_url', json={
    'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    'quality': 'best[height<=720]'
})

data = response.json()
print(f"Direct URL: {data['direct_url']}")

# Download video
response = requests.post('http://localhost:5000/download_video', json={
    'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    'client_meta': {'project': 'demo', 'user_id': 123}
})

data = response.json()
print(f"Download URL: {data['task_download_url']}")
```

### JavaScript (Node.js)

```javascript
const axios = require('axios');

// Get direct URL
async function getDirectUrl(videoUrl) {
  const response = await axios.post('http://localhost:5000/get_direct_url', {
    url: videoUrl,
    quality: 'best[height<=720]'
  });

  return response.data.direct_url;
}

// Download video (async mode)
async function downloadVideo(videoUrl) {
  const response = await axios.post('http://localhost:5000/download_video', {
    url: videoUrl,
    async: true,
    client_meta: {project: 'demo'}
  });

  const taskId = response.data.task_id;
  console.log('Task started:', taskId);

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

    await new Promise(r => setTimeout(r, 2000)); // wait 2s
  }
}
```

### n8n Workflow

**Recommended Schema:**

**Step 0: Configure n8n for large files**

Add to your n8n docker-compose.yml:
```yaml
services:
  n8n:
    environment:
      - N8N_DEFAULT_BINARY_DATA_MODE=filesystem
```

**Option A (sync, simpler):**
1. POST `http://youtube_downloader:5000/download_video` with body `{"url": "..."}`
2. Use `task_download_url` from response to download file (Response Format: File, Binary Property: data)

**Option B (async, more reliable):**
1. POST `/download_video` with `{"url":"...","async":true}` - get `task_id`
2. Poll `/task_status/{{task_id}}` until `status=completed`
3. Download `{{ $json.task_download_url }}` (Response Format: File, Binary Property: data)

**Critical:**
1. n8n must have `N8N_DEFAULT_BINARY_DATA_MODE=filesystem`
2. Set "Response Format" to "File" in download node
3. Without proper config, n8n will try to load video into memory and fail with "Cannot create a string longer than 0x1fffffe8 characters"

---

## Troubleshooting

### Common Issues

#### 1. YouTube blocks downloads

**Problem:** `Sign in to confirm you're not a bot` or `Private video`

**Solutions:**
- Use cookies from private/incognito window (see Cookies Setup section)
- Add 5-10 second delay between requests
- Consider using PO Token for modern videos
- Check if video is actually private/deleted/age-restricted

#### 2. n8n Error: "Cannot create a string longer than 0x1fffffe8 characters"

**Problem:** n8n tries to load large video into memory

**Solutions:**
1. Configure n8n: `N8N_DEFAULT_BINARY_DATA_MODE=filesystem` (recommended)
2. Set "Response Format" to "File" in HTTP Request node
3. Use "Binary Property": `data`

#### 3. Webhook not received

**Problem:** Webhook payload not arriving

**Solutions:**
- Check webhook URL is accessible from container
- API retries 3 times with 5s interval
- Check container logs: `docker logs youtube-downloader`
- Verify webhook endpoint accepts POST requests
- Use absolute URLs (http/https)

#### 4. Direct URL returns 403 Forbidden

**Problem:** Direct URL expired or blocked

**Solutions:**
- Direct URLs have limited lifetime (few hours)
- Use `/download_video` instead for reliable downloads
- Download immediately after receiving direct URL
- Add required http_headers from response

#### 5. Redis connection failed

**Problem:** `Could not connect to Redis`

**Note:** Public version has **embedded Redis** - this error should not occur. If you see this error:
- Restart the container: `docker restart yt-downloader`
- Check container logs: `docker logs yt-downloader`
- For external Redis configuration, use [YouTube Downloader API Pro](https://github.com/alexbic/youtube-downloader-api-pro)

#### 6. Files not found after download

**Problem:** `404 File not found`

**Solutions:**
- Files auto-delete after 24 hours in public version (not configurable)
- Download immediately after `status: "completed"`
- For configurable TTL or permanent storage, use [YouTube Downloader API Pro](https://github.com/alexbic/youtube-downloader-api-pro)

#### 7. Authentication errors

**Problem:** `401 Unauthorized` or `Invalid API key`

**Solutions:**
- If `API_KEY` is set, all protected endpoints require `Authorization: Bearer <key>`
- Protected endpoints: `/download_video`, `/get_direct_url`, `/get_video_info`
- Public endpoints (no auth): `/health`, `/task_status`, `/download`
- If using internal Docker mode, unset `API_KEY` entirely

#### 8. Client metadata validation errors

**Problem:** `client_meta validation failed` or `client_meta too large`

**Solutions:**
- Max size: 16 KB (JSON UTF-8)
- Max depth: 5 levels
- Max keys: 200 total
- Max string length: 1000 characters
- Max list length: 200 items
- Use flat structure when possible

### Logging

**View container logs:**
```bash
# Real-time logs
docker logs -f youtube-downloader

# Last 100 lines
docker logs --tail 100 youtube-downloader

# With timestamps
docker logs -t youtube-downloader
```

**Log levels:**
- `DEBUG` - verbose logging including yt-dlp options
- `INFO` - standard logging (default)
- `WARNING` - warnings only
- `ERROR` - errors only
- `CRITICAL` - critical errors only

**Progress logging modes:**
- `off` (default) - no progress spam
- `compact` - compact progress every N% (configurable via `PROGRESS_STEP`)
- `full` - detailed yt-dlp progress (very verbose)

---

## Development

### Local Build

```bash
git clone https://github.com/alexbic/youtube-downloader-api.git
cd youtube-downloader-api
docker build -t youtube-downloader:local .
docker run -p 5000:5000 youtube-downloader:local
```

### Local Run (without Docker)

```bash
pip install -r requirements.txt
python app.py
```

---

## CI/CD

GitHub Actions automatically builds and publishes Docker images on every push to `main`:

1. Builds for platforms: linux/amd64, linux/arm64
2. Publishes to Docker Hub: `alexbic/youtube-downloader-api`
3. Publishes to GitHub Container Registry: `ghcr.io/alexbic/youtube-downloader-api`
4. Updates Docker Hub description

Build status: [GitHub Actions](https://github.com/alexbic/youtube-downloader-api/actions)

---

## Technologies

- Python 3.11
- Flask 3.0.0
- yt-dlp (latest)
- FFmpeg
- Gunicorn
- Redis (optional)
- Docker

---

## License

MIT License - see [LICENSE](LICENSE) file

---

## 🚀 YouTube Downloader API Pro

**Coming Soon!** The Pro version is currently in development and will be available shortly.

### What's Coming in Pro Version

The Pro version will include:

- 🗄️ **PostgreSQL Storage** - Persistent task history and metadata
- ⚙️ **Fully Configurable** - Customize workers (1-10+), TTL (hours to months), external Redis
- 📊 **Processing Results Cache** - Store and query yt-dlp output for analytics
- 🔍 **Advanced Search & Filtering** - Query tasks by status, date range, client_meta fields
- 📈 **Task Statistics** - Track success rate, processing time, bandwidth usage
- 🔄 **Priority Queue** - VIP task processing with configurable priorities
- 📧 **Email Notifications** - Task completion alerts
- 👨‍💼 **Priority Support** - Direct email and GitHub support
- 📚 **Extended Documentation** - Detailed guides and best practices

### Distribution Model (In Development)

We're currently evaluating the best way to deliver the Pro version:

**Option 1: GitHub Private Repository (Subscription)**
- Access via GitHub team/organization membership
- Clone repository with your credentials
- Automatic updates via git pull
- Pro: Simple, familiar workflow for developers
- Con: Requires GitHub account

**Option 2: Docker Registry (License Key)**
- Pull Pro image from private registry with license key
- `docker pull pro.yourdomain.com/youtube-downloader-api-pro:latest`
- License validation on startup
- Pro: No source code exposure, easy deployment
- Con: Requires license server infrastructure

**Option 3: npm/PyPI Private Package**
- Install via private package registry
- `pip install --extra-index-url https://pypi.yourdomain.com youtube-downloader-api-pro`
- Pro: Standard package management
- Con: Additional infrastructure needed

**Option 4: Landing Page with Direct Downloads**
- Purchase on landing page → receive download link
- Manual updates via re-download
- Pro: Simple, no infrastructure
- Con: Manual update process

**Option 5: Hybrid Approach**
- Landing page for purchase and license key generation
- Private Docker registry for Pro images
- GitHub private repo for enterprise customers
- Pro: Flexible, caters to different customer needs
- Con: More complex to maintain

### Current Status

🔨 **In Active Development**
- Core Pro features are being implemented in `youtube-downloader-api-pro` repository
- Testing deployment and licensing models
- Preparing documentation and landing page

📧 **Get Notified**
Interested in the Pro version? Contact us to be notified when it launches:
- Email: support@alexbic.net
- GitHub: Watch the repository for announcements

### Pricing (Preliminary)

We're considering the following pricing tiers:

- **Individual License**: $XX/month or $XXX/year - Single deployment
- **Team License**: $XXX/month or $XXXX/year - Up to 5 deployments
- **Enterprise License**: Custom pricing - Unlimited deployments + SLA

*Pricing is subject to change before official launch*

---

## Support

- GitHub: [@alexbic](https://github.com/alexbic)
- Issues: [GitHub Issues](https://github.com/alexbic/youtube-downloader-api/issues)
- Pro Version Inquiries: support@alexbic.net

---

## Disclaimer

This tool is for personal use. Ensure you comply with YouTube's Terms of Service and copyright laws when downloading content.
