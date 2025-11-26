# Changelog

All notable changes to YouTube Downloader API will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] - 2025-11-26

### Added
- **Automatic task recovery system** - comprehensive recovery mechanism with 3 components:
  - Startup recovery: resumes interrupted tasks on container restart
  - Runtime recovery: retries failed tasks with exponential backoff
  - Webhook resender: background service for failed webhook delivery
- **Recovery system documentation** - detailed guide in `docs/RECOVERY_SYSTEM.md`
- **Repository cleanup** - `testing/` directory removed from Git tracking

### Fixed
- **CRITICAL: Startup recovery race condition** - recovery now executes synchronously before Gunicorn starts accepting connections, preventing potential data corruption and duplicate tasks
- **YouTube HLS 403 errors** - added `skip_unavailable_fragments: True` to handle missing video fragments gracefully

### Changed
- **Unified logging style** - all logs now in English with emoji markers for key events
- **Optimized log output** - removed redundant debug messages, cleaner production logs
- **Documentation improvements** - cleaned up environment variables tables, marked hardcoded parameters

### Commits
- `39cf7ee` - fix: make startup recovery blocking to prevent race condition
- `7837a68` - chore: remove testing directory from Git tracking
- `9c072a4` - feat: add automatic task recovery system
- `c444537` - logs: optimize logging output for cleaner visibility
- `d527b61` - logs: unify logging style with English and emojis
- `679f18d` - fix: add skip_unavailable_fragments to handle YouTube HLS 403 errors
- `e377048` - docs: Clean up environment variables table
- `4bb8516` - docs: Remove GUNICORN_TIMEOUT from environment variables
- `8b3ac59` - docs: Remove hardcoded parameters from environment tables
- `c55ad80` - docs: Mark progress logging parameters as hardcoded

---

## [1.0.0] - 2025-11-21

### Added
- **Initial public release** - first stable version of YouTube Downloader API
- **Redis-first architecture** - fast caching with < 1ms response time for 99% requests
- **Stepwise state tracking** - incremental state verification with checkpoint logging
- **Unified response structure** - consistent input/output sections across all endpoints
- **Sync and async download modes** - flexible video downloading options
- **Webhook notifications** - POST callbacks with automatic retry mechanism (3 attempts, 5s interval)
- **Webhook resender** - background service retries failed webhooks every 15 minutes
- **Bearer token authentication** - optional API key protection for public deployments
- **Absolute URLs support** - internal and external URL generation
- **Built-in embedded Redis** - standalone container with 256MB Redis
- **Cookie support** - bypass YouTube restrictions using browser cookies
- **Auto cleanup** - automatic task deletion after 24h TTL
- **Docker multi-arch support** - amd64 and arm64 architectures
- **Client metadata** - arbitrary JSON passthrough (max 4096 bytes)
- **Video quality selection** - configurable quality presets (480p, 720p, 1080p, best)
- **Comprehensive error handling** - structured error responses with user actions
- **Health check endpoint** - service status and configuration monitoring

### Features
- `/download_video` - main endpoint for video downloads (sync/async)
- `/task_status/<task_id>` - check async task status
- `/health` - service health and configuration
- `/download/<task_id>/<filename>` - download completed files
- Metadata.json files with complete task information
- Progress tracking and logging (hardcoded: off in public version)
- HLS fragment skipping for YouTube streams

### Documentation
- Comprehensive README with API documentation
- Release notes with architecture details
- Environment variables reference
- Docker deployment guide
- Use cases and examples

### Hardcoded Limits (Public Version)
- 2 Gunicorn workers
- 24-hour task TTL
- 256MB Redis memory
- Memory-only storage (no PostgreSQL)
- Progress logging disabled
- yt-dlp warnings disabled

---

## Release Notes

- **v1.1.0**: [docs/RELEASE_NOTES_v1.1.0.md](./RELEASE_NOTES_v1.1.0.md) - Reliability & Recovery
- **v1.0.0**: [docs/RELEASE_NOTES.md](./RELEASE_NOTES.md) - Initial Public Release

---

## Upgrade Guide

### From 1.0.0 to 1.1.0

**No breaking changes** - fully backward compatible.

```bash
# Pull new version
docker pull alexbic/youtube-downloader-api:1.1.0
docker pull alexbic/youtube-downloader-api:latest

# Restart container
docker-compose down
docker-compose up -d
```

**What's different:**
- Recovery completes before API accepts requests (fixed race condition)
- Improved log output (English + emojis)
- Better handling of YouTube HLS errors

**Expected startup logs:**
```
[INFO] 🔄 Recovery: scanning for interrupted tasks...
[INFO] ✅ Recovery: COMPLETED. API endpoint accepting requests now.
[INFO] Starting gunicorn 21.2.0
[INFO] Listening at: http://0.0.0.0:5000
```

---

## Links

- **Repository**: https://github.com/alexbic/youtube-downloader-api
- **Docker Hub**: https://hub.docker.com/r/alexbic/youtube-downloader-api
- **Issues**: https://github.com/alexbic/youtube-downloader-api/issues
- **Pro Version**: https://github.com/alexbic/youtube-downloader-api-pro

---

**Format**: [Keep a Changelog](https://keepachangelog.com/)
**Versioning**: [Semantic Versioning](https://semver.org/)
