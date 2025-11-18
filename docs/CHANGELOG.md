# Changelog

All notable changes to YouTube Downloader API (Public Version) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2025-11-18

### 🎉 First Official Release - Public Version

**YouTube Downloader API (Public Version)** - Production-ready Docker container with embedded Redis and hardcoded limits.

This is the **free, open-source version** with fixed configuration optimized for standalone deployment.

---

### ✨ Features

#### Core Functionality
- 🎬 **Direct URL retrieval** - get YouTube video links without downloading to server
- ⬇️ **Server-side downloads** - download videos with quality selection (sync/async modes)
- 📊 **Video information API** - extract complete metadata (title, description, duration, views, etc.)
- 🔄 **Sync and async modes** - immediate or background processing
- 🔗 **Webhook support** - POST notifications on task completion with automatic retries
- 📝 **Client metadata** - pass arbitrary JSON through entire workflow

#### Public Version Specifics (Hardcoded)
- 📦 **Embedded Redis** - 256MB memory limit, localhost:6379 (not configurable)
- 👥 **2 Workers** - Gunicorn workers (not configurable)
- ⏰ **24h TTL** - automatic file cleanup after 24 hours (not configurable)
- 🔁 **Webhook Resender** - background service retries failed webhooks every 15 minutes (not configurable)
- 🧹 **Smart Cleanup** - orphaned tasks (without metadata.json) deleted after 1 hour

#### Infrastructure
- 🐳 **Docker multi-arch** - linux/amd64, linux/arm64
- 🔑 **Optional authentication** - Bearer token support for public deployments
- 🌐 **URL flexibility** - internal and external URL generation
- 🔒 **Cookie support** - bypass YouTube restrictions with browser cookies
- 📋 **Comprehensive logging** - DEBUG, INFO, WARNING, ERROR levels

---

### 🔧 Hardcoded Limitations (Public Version)

The following parameters are **HARDCODED** and **CANNOT be changed** in the public version:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `WORKERS` | `2` | Number of Gunicorn workers |
| `CLEANUP_TTL_SECONDS` | `86400` | Task file TTL (24 hours) |
| `REDIS_HOST` | `localhost` | Embedded Redis host |
| `REDIS_PORT` | `6379` | Embedded Redis port |
| `REDIS_DB` | `0` | Redis database number |
| `WEBHOOK_BACKGROUND_INTERVAL_SECONDS` | `900` | Webhook resender scan interval (15 minutes) |

🚀 **Want configurable limits?** Upgrade to [YouTube Downloader API Pro](https://github.com/alexbic/youtube-downloader-api-pro)

---

### 🐛 Critical Bug Fixes

#### TTL Cleanup Reliability ([#48bacfc](https://github.com/alexbic/youtube-downloader-api/commit/48bacfc))
**Problem:** Cleanup used directory `mtime` which gets reset when Docker volume is mounted after container restart.

**Solution:**
- ✅ Now reads `created_at` timestamp from `metadata.json`
- ✅ Falls back to `mtime` only if metadata.json doesn't exist
- ✅ Prevents premature deletion of old tasks after container restart

**Impact:** Tasks are now deleted at correct intervals (24 hours from creation, not from last container restart).

#### Orphaned Tasks Cleanup ([#9c8a7fa](https://github.com/alexbic/youtube-downloader-api/commit/9c8a7fa))
**Problem:** Tasks without `metadata.json` (stuck/damaged tasks) were never deleted properly.

**Solution:**
- ✅ Orphaned tasks (without metadata.json) are now deleted after **1 hour** (vs 24 hours for normal tasks)
- ✅ Added detailed logging: `"removing orphaned task"` vs `"removing expired task"`
- ✅ Prevents accumulation of broken/incomplete tasks

**Impact:** Automatic cleanup of stuck downloads that failed to create metadata.

---

### 📚 Documentation

#### Comprehensive Documentation (EN + RU)
- ✅ **README.md** - Complete English documentation with all features
- ✅ **README.ru.md** - Full Russian translation (synchronized)
- ✅ **RELEASE_NOTES_v1.0.0.md** - Detailed release notes
- ✅ **CHANGELOG.md** - Version history (this file)

#### Docker Compose
- ✅ Fully commented `docker-compose.yml` with inline documentation
- ✅ Clear section markers (authentication, webhooks, public version limits)
- ✅ Examples for common deployment scenarios

#### Integration Examples
- ✅ Python async workflow example
- ✅ JavaScript/Node.js example
- ✅ n8n workflow configuration
- ✅ Troubleshooting guide for common issues

---

### 🔐 Security

#### Authentication
- ✅ Optional Bearer token authentication (`API_KEY` + `PUBLIC_BASE_URL`)
- ✅ Internal mode (no auth) for Docker networks
- ✅ Public mode (auth required) for external deployments

#### Input Validation
- ✅ Client metadata limits (16KB size, 5 levels depth, 200 keys max)
- ✅ String length limits (1000 chars)
- ✅ List length limits (200 items)
- ✅ Webhook URL validation

#### Logging Security
- ✅ Sensitive headers (Authorization, X-API-Key) masked in logs
- ✅ Webhook payload preview in DEBUG mode (first 500 chars)

---

### 🏗️ Infrastructure

#### CI/CD Pipeline
- ✅ **GitHub Actions** - automated builds on every push
- ✅ **Multi-arch builds** - linux/amd64, linux/arm64
- ✅ **Docker Hub** - `alexbic/youtube-downloader-api`
- ✅ **GitHub Container Registry** - `ghcr.io/alexbic/youtube-downloader-api`

#### Docker Images
- ✅ Tag `latest` - latest stable version
- ✅ Tag `main` - latest from main branch
- ✅ Tag `v1.0.0` - specific version
- ✅ Tag `sha-<commit>` - specific commit

---

### 📊 Technical Details

#### Stack
- Python 3.11
- Flask 3.0.0
- yt-dlp (latest, auto-updated)
- FFmpeg
- Gunicorn (2 workers, hardcoded)
- Redis 8.0.2 (embedded, 256MB limit)
- Supervisor (process manager)

#### Performance
- **2 workers** - handles concurrent requests
- **Embedded Redis** - no external dependencies
- **Background webhook resender** - automatic retry every 15 minutes
- **Automatic cleanup** - prevents disk space exhaustion

---

## Upgrade to Pro Version

For advanced features and configurable limits, check out **YouTube Downloader API Pro**:

### Pro Version Features
- 🗄️ **PostgreSQL metadata storage** - persistent task history
- ⚙️ **Configurable TTL** - from hours to months
- 🔍 **Advanced search & filtering** - query tasks by status, date, client_meta
- 📊 **Processing results cache** - store yt-dlp output for analytics
- 🔧 **Configurable workers** - scale from 1 to 10+ workers
- 🔄 **External Redis** - use your existing Redis cluster
- 📈 **Task statistics** - track processing time, success rate
- 👨‍💼 **Priority support** - email and GitHub support

### Contact
- 📧 Email: support@alexbic.net
- 🌐 Website: https://github.com/alexbic/youtube-downloader-api-pro

---

## Links

- **GitHub Repository:** https://github.com/alexbic/youtube-downloader-api
- **Docker Hub:** https://hub.docker.com/r/alexbic/youtube-downloader-api
- **GitHub Container Registry:** https://github.com/alexbic/youtube-downloader-api/pkgs/container/youtube-downloader-api
- **Issues:** https://github.com/alexbic/youtube-downloader-api/issues
- **License:** MIT

---

**Thanks for using YouTube Downloader API!** 🎬✨
