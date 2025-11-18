# YouTube Downloader API — Release v1.0.0 (2025-11-18)

## 🎉 First Official Release - Public Version

**Production-ready Docker container** for downloading YouTube videos with embedded Redis and hardcoded limits.

This is the **free, open-source version** optimized for standalone deployment without external dependencies.

---

## 📦 What's Included

### Core Features

#### Video Processing
- 🎬 **Direct URL retrieval** - get YouTube direct links without downloading to server
- ⬇️ **Server-side downloads** - download videos with quality selection
- 📊 **Video information** - extract complete metadata (title, duration, views, uploader, etc.)
- 🔄 **Sync/Async modes** - choose immediate or background processing
- 📝 **Client metadata** - pass custom JSON data through entire workflow

#### Webhook System
- 🔗 **Webhook support** - POST notifications on task completion
- 🔁 **Background resender** - automatic retry of failed webhooks every 15 minutes
- ⚙️ **Configurable retries** - 3 immediate attempts with 5-second intervals
- 🎯 **Default webhook URL** - fallback for tasks without explicit webhook
- 🔐 **Custom headers** - authentication support for webhook endpoints

#### Infrastructure
- 🐳 **Docker ready** - single standalone container
- 📦 **Embedded Redis** - 256MB, no external dependencies
- 🧹 **Auto cleanup** - tasks deleted after 24 hours
- 🔒 **Cookie support** - bypass YouTube restrictions
- 🔑 **Optional auth** - Bearer token for public deployments

---

## 🔧 Public Version Specifications

### Hardcoded Limits (Not Configurable)

The public version has the following **fixed parameters** that cannot be changed:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| **Workers** | `2` | Gunicorn workers for concurrent requests |
| **TTL** | `24 hours` | Automatic file cleanup interval |
| **Redis** | `localhost:6379` | Embedded Redis (256MB memory limit) |
| **Webhook Resender** | `15 minutes` | Background scan interval |

These limits are hardcoded in the application code to simplify deployment and ensure consistent behavior.

### Configurable Parameters

You **can** configure:
- ✅ `API_KEY` - Bearer token for authentication
- ✅ `PUBLIC_BASE_URL` - External URL for absolute links
- ✅ `INTERNAL_BASE_URL` - Internal URL for webhooks
- ✅ `LOG_LEVEL` - Logging verbosity (DEBUG, INFO, WARNING, ERROR)
- ✅ `WEBHOOK_RETRY_ATTEMPTS` - Immediate retry count (default: 3)
- ✅ `WEBHOOK_RETRY_INTERVAL_SECONDS` - Retry delay (default: 5s)
- ✅ `WEBHOOK_TIMEOUT_SECONDS` - Request timeout (default: 8s)
- ✅ `DEFAULT_WEBHOOK_URL` - Fallback webhook for async tasks
- ✅ `WEBHOOK_HEADERS` - Custom headers for webhook POSTs
- ✅ `MAX_CLIENT_META_*` - Client metadata validation limits

See [README.md](README.md) for complete environment variables reference.

---

## 🆚 Public vs Pro Version

### Public Version (This Release)
- ✅ **Free and open-source** (MIT License)
- ✅ **Standalone container** - no external dependencies
- ✅ **Embedded Redis** - 256MB, localhost:6379
- ✅ **Fixed limits** - 2 workers, 24h TTL
- ✅ **Basic features** - download, direct URLs, webhooks
- ⚠️ **Not configurable** - hardcoded for simplicity

### Pro Version (Commercial)
- 💰 **Paid license** with priority support
- 🗄️ **PostgreSQL storage** - persistent task history
- ⚙️ **Fully configurable** - workers, TTL, Redis
- 📊 **Processing results cache** - store yt-dlp output
- 🔍 **Advanced search** - filter by status, date, metadata
- 📈 **Analytics** - track success rate, processing time
- 👨‍💼 **Priority support** - email and GitHub

🚀 **Upgrade to Pro:** https://github.com/alexbic/youtube-downloader-api-pro

---

## 🐛 Critical Bug Fixes

### 1. TTL Cleanup Reliability

**Problem:**
Cleanup function used directory `mtime` (modification time) to determine task age. When Docker container restarts, volume remount resets `mtime`, causing incorrect age calculation.

**Example:**
- Task created: 2025-11-17 05:17 UTC (17 hours ago)
- Container restarted: 2025-11-17 22:53 UTC
- Directory `mtime`: 2025-11-17 20:54 UTC (2 hours ago) ❌
- Result: Task not deleted for another 22 hours (incorrect!)

**Solution:**
- ✅ Read `created_at` timestamp from `metadata.json`
- ✅ Fall back to `mtime` only if metadata missing
- ✅ Added DEBUG logging for cleanup decisions

**Impact:**
Tasks are now deleted at correct intervals (24 hours from creation, not from container restart).

**Commit:** [48bacfc](https://github.com/alexbic/youtube-downloader-api/commit/48bacfc)

---

### 2. Orphaned Tasks Cleanup

**Problem:**
Some tasks get stuck without `metadata.json` file (failed downloads, crashes, etc.) and can't be properly aged by the new cleanup logic. They accumulate indefinitely using unreliable `mtime` fallback.

**Solution:**
- ✅ Detect orphaned tasks (no `metadata.json`)
- ✅ Delete orphaned tasks after **1 hour** (vs 24 hours for normal tasks)
- ✅ Add reason logging: `"removing orphaned task"` vs `"removing expired task"`

**Rationale:**
Normal tasks always create `metadata.json` immediately. If it's missing after 1 hour, the task is definitely broken.

**Impact:**
Automatic cleanup of stuck downloads, preventing disk space issues.

**Commit:** [9c8a7fa](https://github.com/alexbic/youtube-downloader-api/commit/9c8a7fa)

---

## 📚 Documentation

### README Files
- ✅ [README.md](README.md) - Complete English documentation
- ✅ [README.ru.md](README.ru.md) - Full Russian translation
- ✅ Both synchronized and up-to-date

### Guides
- ✅ **Quick Start** - Docker run command and testing
- ✅ **Installation** - Docker Compose examples
- ✅ **Configuration** - Environment variables reference
- ✅ **API Endpoints** - Complete API documentation
- ✅ **Webhook System** - Setup and troubleshooting
- ✅ **Cookie Setup** - Bypass YouTube restrictions
- ✅ **Troubleshooting** - Common issues and solutions
- ✅ **Integration Examples** - Python, JavaScript, n8n

### Code Documentation
- ✅ Fully commented `docker-compose.yml`
- ✅ Inline code comments for hardcoded limits
- ✅ Clear section markers in configuration

---

## 🚀 Quick Start

### Pull and Run

```bash
# Pull from Docker Hub
docker pull alexbic/youtube-downloader-api:latest

# Run container
docker run -d \
  -p 5000:5000 \
  --name yt-downloader \
  alexbic/youtube-downloader-api:latest
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

## 🐳 Docker Deployment

### Minimal Setup (Internal Use)

```yaml
version: '3.8'
services:
  youtube-downloader:
    image: alexbic/youtube-downloader-api:latest
    ports:
      - "5000:5000"
    volumes:
      - ./tasks:/app/tasks
    restart: unless-stopped
```

### Production Setup (Public Deployment)

```yaml
version: '3.8'
services:
  youtube-downloader:
    image: alexbic/youtube-downloader-api:latest
    ports:
      - "5000:5000"
    volumes:
      - ./tasks:/app/tasks
      - ./cookies.txt:/app/cookies.txt  # Optional: YouTube auth
    environment:
      # Authentication
      PUBLIC_BASE_URL: "https://ytdl.example.com"
      API_KEY: "${API_KEY}"  # Generate: openssl rand -hex 32

      # Webhooks (optional)
      DEFAULT_WEBHOOK_URL: "https://your-server.com/webhooks/ytdl"
      WEBHOOK_HEADERS: '{"Authorization": "Bearer secret123"}'

      # Logging
      LOG_LEVEL: "INFO"
    restart: unless-stopped
```

---

## 📋 API Endpoints

### Protected (require auth if enabled)
- `POST /download_video` - Download video to server
- `POST /get_direct_url` - Get direct YouTube link
- `POST /get_video_info` - Get video metadata

### Public (no auth)
- `GET /health` - Health check
- `GET /task_status/<task_id>` - Check async task status
- `GET /download/<task_id>/<filename>` - Download file
- `GET /download/<task_id>/metadata.json` - Get task metadata

---

## 🔐 Authentication

### Internal Mode (No Auth)
- Don't set `API_KEY` or `PUBLIC_BASE_URL`
- All endpoints accessible without authentication
- Suitable for Docker internal networks

### Public Mode (Auth Required)
- Set both `PUBLIC_BASE_URL` and `API_KEY`
- Protected endpoints require: `Authorization: Bearer <API_KEY>`
- Suitable for public deployments

**Generate API key:**
```bash
openssl rand -hex 32
```

---

## 🔁 Webhook System

### How It Works

1. **Immediate retries** - 3 attempts with 5-second intervals when task completes
2. **Background resender** - scans all tasks every 15 minutes
3. **Persistent URL** - webhook URL saved in task metadata
4. **Retry until success** - continues until HTTP 200-299 or TTL expires

### Configuration

```yaml
environment:
  # Fallback webhook for tasks without explicit webhook_url
  DEFAULT_WEBHOOK_URL: "https://your-server.com/webhooks/ytdl"

  # Custom headers for authentication
  WEBHOOK_HEADERS: '{"Authorization": "Bearer secret123", "X-Source": "ytdl"}'

  # Retry configuration
  WEBHOOK_RETRY_ATTEMPTS: 3
  WEBHOOK_RETRY_INTERVAL_SECONDS: 5
  WEBHOOK_TIMEOUT_SECONDS: 8
```

### Webhook Payload

```json
{
  "task_id": "f834c34d-d4a9-4de4-a99d-a5e07988bccd",
  "status": "completed",
  "video_title": "Example Video",
  "download_url": "http://localhost:5000/download/f834c34d-.../video.mp4",
  "metadata_url": "http://localhost:5000/download/f834c34d-.../metadata.json",
  "client_meta": {
    "user_id": 123,
    "project": "demo"
  }
}
```

---

## 🧹 Automatic Cleanup

### Normal Tasks
- **TTL:** 24 hours (hardcoded in public version)
- **Trigger:** `created_at` timestamp in metadata.json
- **Fallback:** directory `mtime` if metadata missing

### Orphaned Tasks
- **TTL:** 1 hour (hardcoded)
- **Definition:** Tasks without `metadata.json` file
- **Reason:** Normal tasks always create metadata immediately

### Cleanup Logs

```
2025-11-18 04:03:31 [INFO] Cleanup: TTL=86400s (1440min)
2025-11-18 04:03:31 [DEBUG] Cleanup: orphaned task abc123 (no metadata.json), using mtime
2025-11-18 04:03:31 [DEBUG] Cleanup: removing orphaned task abc123 (age: 64564s, ttl: 3600s)
2025-11-18 04:03:31 [INFO] Resender: cleaned up 2 expired task(s) older than 86400s
```

---

## 🔒 Cookie Setup

YouTube may block downloads. Use cookies to bypass restrictions.

### Export Cookies

1. Install browser extension: [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. **Open private/incognito window** (important!)
3. Log in to YouTube
4. Export cookies from that private window
5. Save as `cookies.txt` next to `docker-compose.yml`

### Docker Compose

```yaml
volumes:
  - ./cookies.txt:/app/cookies.txt
```

**Why private window?**
YouTube rotates cookies in regular tabs for security. Private window cookies are more stable.

---

## 🛠️ Troubleshooting

### YouTube blocks downloads
- ✅ Use cookies from private/incognito window
- ✅ Add 5-10 second delay between requests
- ✅ Check if video is private/deleted/age-restricted

### Redis connection failed
- ✅ Public version has embedded Redis - this shouldn't happen
- ✅ Restart container: `docker restart yt-downloader`
- ✅ Check logs: `docker logs yt-downloader`

### Files not found after download
- ✅ Files auto-delete after 24 hours (hardcoded in public version)
- ✅ Download immediately after `status: "completed"`

### Webhook not received
- ✅ Ensure webhook URL is accessible from container
- ✅ Check logs: `LOG_LEVEL=DEBUG` shows webhook payload preview
- ✅ Background resender retries every 15 minutes

---

## 📊 Technical Stack

- **Python:** 3.11
- **Web Framework:** Flask 3.0.0
- **Download Engine:** yt-dlp (latest, auto-updated)
- **Video Processing:** FFmpeg
- **Web Server:** Gunicorn (2 workers, hardcoded)
- **Storage:** Redis 8.0.2 (embedded, 256MB)
- **Process Manager:** Supervisor

---

## 🏗️ CI/CD

### GitHub Actions
- ✅ Automated builds on every push to main
- ✅ Multi-arch builds: linux/amd64, linux/arm64
- ✅ Automated tagging: `latest`, `main`, `v1.0.0`, `sha-<commit>`

### Registries
- 🐳 **Docker Hub:** `alexbic/youtube-downloader-api`
- 📦 **GHCR:** `ghcr.io/alexbic/youtube-downloader-api`

---

## 📈 What's Next?

### Using Public Version
1. ✅ Deploy using Docker Compose examples above
2. ✅ Configure authentication if needed (`PUBLIC_BASE_URL` + `API_KEY`)
3. ✅ Set up cookies for YouTube restrictions
4. ✅ Configure webhooks for async workflows
5. ✅ Monitor logs for cleanup and webhook delivery

### Upgrading to Pro
If you need:
- Configurable TTL (hours to months)
- More than 2 workers
- PostgreSQL task history
- Processing results cache
- Advanced search and filtering

📧 Contact: support@alexbic.net
🌐 Info: https://github.com/alexbic/youtube-downloader-api-pro

---

## 📞 Support

- **GitHub Issues:** https://github.com/alexbic/youtube-downloader-api/issues
- **Documentation:** [README.md](README.md) | [README.ru.md](README.ru.md)
- **Docker Hub:** https://hub.docker.com/r/alexbic/youtube-downloader-api
- **License:** MIT (see [LICENSE](LICENSE))

---

## 🙏 Acknowledgments

Special thanks to:
- **yt-dlp project** - excellent YouTube download library
- **Flask community** - lightweight web framework
- **All users** who tested and provided feedback

---

**Thanks for using YouTube Downloader API!** 🎬✨

Have questions? Open an issue on GitHub or check the comprehensive documentation in README.md.
