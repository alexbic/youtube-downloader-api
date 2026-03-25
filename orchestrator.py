#!/usr/bin/env python3
"""
Task Orchestrator - Independent process that manages:
1. Redis initialization from disk metadata (Recovery)
2. Task queue management and worker distribution

Startup sequence:
1. Redis server starts
2. Orchestrator starts
   a) Wait for Redis ready
   b) Recovery: scan /app/tasks, load metadata.json → populate Redis
   c) Check MAX_CONCURRENT_TASKS configuration
   d) Start managing worker queue (FIFO distribution)
3. Gunicorn (HTTP workers) start after orchestrator is ready
"""

import os
import sys
import time
import json
import logging
import threading
import redis
import requests
from datetime import datetime, timedelta
from task_sync import save_and_sync_metadata

# Force unbuffered stdout/stderr for immediate log visibility
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)


class FlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
flush_handler = FlushHandler(sys.stdout)
flush_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    handlers=[flush_handler]
)
logger = logging.getLogger(__name__)

# Redis configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))

# Task configuration — fixed limits for public version
TASKS_DIR = os.getenv('TASKS_DIR', '/app/tasks')
MAX_CONCURRENT_TASKS = 2          # Fixed: public version limit
MAX_CONCURRENT_TASKS_LIMIT = 2    # Hard ceiling
TASK_TTL_MINUTES = 1440           # Fixed: 24 hours

# Recovery & retry config
MAX_TASK_RETRIES = int(os.getenv('MAX_TASK_RETRIES', '3'))
RETRY_DELAY_SECONDS = int(os.getenv('RETRY_DELAY_SECONDS', '60'))
TASK_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv('TASK_HEARTBEAT_INTERVAL_SECONDS', '30'))
TASK_HEARTBEAT_TIMEOUT_SECONDS = int(os.getenv('TASK_HEARTBEAT_TIMEOUT_SECONDS', '90'))
WEBHOOK_MAX_RETRY_ATTEMPTS = int(os.getenv('WEBHOOK_MAX_RETRY_ATTEMPTS', '5'))
WEBHOOK_RETRY_DELAY_SECONDS = int(os.getenv('WEBHOOK_RETRY_DELAY_SECONDS', '60'))
WEBHOOK_BACKGROUND_INTERVAL_SECONDS = int(os.getenv('WEBHOOK_BACKGROUND_INTERVAL_SECONDS', '900'))
CLEANUP_INTERVAL_SECONDS = int(os.getenv('CLEANUP_INTERVAL_SECONDS', '3600'))
MAX_QUEUED_TASKS = 50
MAX_CLIENT_META_BYTES = int(os.getenv('MAX_CLIENT_META_BYTES', str(16 * 1024)))
MAX_CLIENT_META_DEPTH = int(os.getenv('MAX_CLIENT_META_DEPTH', '5'))
MAX_CLIENT_META_KEYS = int(os.getenv('MAX_CLIENT_META_KEYS', '200'))

# API configuration
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL') or os.getenv('EXTERNAL_BASE_URL')
INTERNAL_BASE_URL = os.getenv('INTERNAL_BASE_URL')
DEFAULT_WEBHOOK_URL = os.getenv('DEFAULT_WEBHOOK_URL')
API_KEY = os.getenv('API_KEY')
API_KEY_ENABLED = bool(API_KEY)

# Download limits
MAX_DOWNLOAD_VIDEO_SIZE_MB = int(os.getenv('MAX_DOWNLOAD_VIDEO_SIZE_MB', '2048'))

# Redis keys
REDIS_ACTIVE_TASKS_KEY = "tasks:active"
REDIS_QUEUED_TASKS_KEY = "queue:queued"
REDIS_TASK_PREFIX = "task:"
REDIS_RECOVERY_FLAG = "system:recovery_in_progress"


def cleanup_task_from_redis(redis_client, task_id: str):
    """Remove task from all Redis keys."""
    try:
        if not redis_client:
            return
        redis_client.delete(f"{REDIS_TASK_PREFIX}{task_id}")
        redis_client.hdel(REDIS_ACTIVE_TASKS_KEY, task_id)
        redis_client.lrem(REDIS_QUEUED_TASKS_KEY, 0, task_id)
    except Exception:
        pass


def load_task_metadata(task_id):
    """Load metadata from disk."""
    try:
        metadata_path = os.path.join(TASKS_DIR, task_id, "metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return None


def save_task_metadata(redis_conn, task_id, metadata):
    """Save metadata to disk and sync to Redis."""
    return save_and_sync_metadata(redis_conn, task_id, metadata, TASKS_DIR)


class TaskOrchestrator:
    """Orchestrator: central manager for all background tasks."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.running = True
        self.recovery_done = False
        self.lock = threading.Lock()

        try:
            self.redis.set(REDIS_RECOVERY_FLAG, "1")
        except Exception as e:
            logger.warning(f"Could not set recovery flag: {e}")

        self.system_ready_file = "/tmp/system-ready"

    def wait_for_redis(self, max_retries=30):
        for attempt in range(max_retries):
            try:
                self.redis.ping()
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Redis attempt {attempt + 1}/{max_retries} failed: {e}")
                    time.sleep(1)
                else:
                    logger.error(f"Failed to connect to Redis after {max_retries} attempts")
                    return False
        return False

    def _is_error_recoverable(self, error_msg: str) -> bool:
        error_lower = str(error_msg).lower()
        recoverable_keywords = [
            'connection', 'timeout', 'network', 'socket',
            'no space', 'disk full', 'enospc',
            'memory', 'out of memory', 'oom', 'cannot allocate'
        ]
        for keyword in recoverable_keywords:
            if keyword in error_lower:
                return True
        non_recoverable_keywords = [
            'missing', 'not found', 'no such file',
            'invalid', 'bad format', 'corrupt', 'unsupported',
            'permission denied', 'access denied', 'forbidden',
            'unauthorized', '401', '403',
            'file too large', 'too large', 'exceeds', 'exceed', 'size limit', 'maximum allowed'
        ]
        for keyword in non_recoverable_keywords:
            if keyword in error_lower:
                return False
        return True

    def recovery_initialize_redis_from_disk(self):
        """Recovery: Scan /app/tasks and populate Redis from metadata.json files."""
        if not os.path.exists(TASKS_DIR):
            return (0, 0)

        try:
            task_ids = [d for d in os.listdir(TASKS_DIR) if os.path.isdir(os.path.join(TASKS_DIR, d))]
        except Exception as e:
            logger.error(f"Recovery: failed to scan tasks directory: {e}")
            return (0, 0)

        initialized = 0
        failed = 0
        enqueued = 0

        for task_id in task_ids:
            metadata_path = os.path.join(TASKS_DIR, task_id, "metadata.json")

            if not os.path.exists(metadata_path):
                failed += 1
                continue

            try:
                with open(metadata_path, 'r') as f:
                    metadata_raw = json.load(f)
                if isinstance(metadata_raw, list) and len(metadata_raw) > 0:
                    metadata = metadata_raw[0]
                elif isinstance(metadata_raw, dict):
                    metadata = metadata_raw
                else:
                    failed += 1
                    continue
            except Exception as e:
                logger.debug(f"Recovery: [{task_id[:8]}] failed to read metadata: {e}")
                failed += 1
                continue

            task_status = metadata.get('status', 'unknown')

            try:
                ttl_seconds = TASK_TTL_MINUTES * 60
                self.redis.setex(
                    f"{REDIS_TASK_PREFIX}{task_id}",
                    ttl_seconds,
                    json.dumps(metadata)
                )
                initialized += 1

                is_recoverable_error = False
                if task_status in ['failed', 'error']:
                    retry_count = metadata.get('retry_count', 0)
                    if retry_count < MAX_TASK_RETRIES:
                        error_info = metadata.get('error', {})
                        if isinstance(error_info, dict):
                            if error_info.get('recoverable') != False:
                                error_message = error_info.get('message', '')
                                if self._is_error_recoverable(error_message):
                                    is_recoverable_error = True
                        else:
                            if self._is_error_recoverable(str(error_info)):
                                is_recoverable_error = True

                incomplete_statuses = ['queued', 'downloading', 'processing']
                if task_status in incomplete_statuses or is_recoverable_error:
                    if is_recoverable_error:
                        metadata['status'] = 'queued'
                        metadata['retry_count'] = metadata.get('retry_count', 0) + 1
                        try:
                            with open(metadata_path, 'w') as f:
                                json.dump(metadata, f, indent=2)
                            self.redis.setex(
                                f"{REDIS_TASK_PREFIX}{task_id}",
                                ttl_seconds,
                                json.dumps(metadata)
                            )
                        except Exception:
                            pass

                    try:
                        task_dir = os.path.join(TASKS_DIR, task_id)
                        try:
                            cleaned_items = []
                            for item in os.listdir(task_dir):
                                item_path = os.path.join(task_dir, item)
                                if item != "metadata.json":
                                    if os.path.isfile(item_path):
                                        os.remove(item_path)
                                        cleaned_items.append(f"file:{item}")
                                    elif os.path.isdir(item_path):
                                        import shutil
                                        shutil.rmtree(item_path)
                                        cleaned_items.append(f"dir:{item}")
                            if cleaned_items:
                                logger.info(f"Recovery: [{task_id[:8]}] cleaned: {', '.join(cleaned_items)}")
                        except Exception as e:
                            logger.warning(f"Recovery: [{task_id[:8]}] cleanup failed: {e}")

                        self.redis.rpush(REDIS_QUEUED_TASKS_KEY, task_id)
                        enqueued += 1
                        logger.info(f"Recovery: [{task_id[:8]}] re-enqueued (was {task_status})")
                    except Exception as e:
                        logger.error(f"Recovery: [{task_id[:8]}] failed to enqueue: {e}")

            except Exception as e:
                logger.error(f"Recovery: [{task_id[:8]}] failed to write to Redis: {e}")
                failed += 1

        try:
            self.redis.delete(REDIS_RECOVERY_FLAG)
        except Exception as e:
            logger.error(f"Recovery: failed to clear flag: {e}")

        if enqueued > 0:
            logger.info(f"Recovery: loaded {initialized} tasks ({enqueued} re-enqueued)")

        return (initialized, enqueued)

    def get_active_count(self) -> int:
        try:
            return self.redis.hlen(REDIS_ACTIVE_TASKS_KEY)
        except Exception:
            return 0

    def get_queued_count(self) -> int:
        try:
            return self.redis.llen(REDIS_QUEUED_TASKS_KEY)
        except Exception:
            return 0

    def check_and_start_workers(self):
        try:
            self._check_crashed_tasks()
            active = self.get_active_count()
            queued = self.get_queued_count()
            if queued > 0 and active > 0:
                logger.debug(f"📊 Queue: {active}/{MAX_CONCURRENT_TASKS} active | {queued} pending")
        except Exception as e:
            logger.error(f"Orchestration error: {e}")

    def _check_crashed_tasks(self):
        try:
            active_tasks = self.redis.hgetall(REDIS_ACTIVE_TASKS_KEY)
            if not active_tasks:
                return

            now = datetime.now()
            timeout = timedelta(seconds=TASK_HEARTBEAT_TIMEOUT_SECONDS)

            for task_id, task_info_raw in active_tasks.items():
                if isinstance(task_id, bytes):
                    task_id = task_id.decode('utf-8')
                if isinstance(task_info_raw, bytes):
                    task_info_raw = task_info_raw.decode('utf-8')

                try:
                    task_info = json.loads(task_info_raw)
                except Exception:
                    continue

                heartbeat_str = task_info.get('heartbeat')
                if not heartbeat_str:
                    continue

                try:
                    heartbeat = datetime.fromisoformat(heartbeat_str)
                except Exception:
                    continue

                if now - heartbeat > timeout:
                    retry_count = task_info.get('retry_count', 0)
                    logger.warning(f"[{task_id[:8]}] 💀 Task crashed (no heartbeat for {TASK_HEARTBEAT_TIMEOUT_SECONDS}s)")

                    self.redis.hdel(REDIS_ACTIVE_TASKS_KEY, task_id)

                    metadata = load_task_metadata(task_id)
                    if metadata:
                        new_retry_count = retry_count + 1
                        metadata['retry_count'] = new_retry_count

                        if new_retry_count >= MAX_TASK_RETRIES:
                            metadata['status'] = 'failed'
                            metadata['error'] = {
                                'type': 'WORKER_CRASHED',
                                'message': f'Worker crashed {new_retry_count} times',
                                'recoverable': False
                            }
                            logger.error(f"[{task_id[:8]}] ⛔ Max retries after crash ({new_retry_count}/{MAX_TASK_RETRIES})")
                        else:
                            metadata['status'] = 'queued'
                            self.redis.rpush(REDIS_QUEUED_TASKS_KEY, task_id)
                            logger.info(f"[{task_id[:8]}] 🔄 Re-enqueued for retry ({new_retry_count}/{MAX_TASK_RETRIES})")

                        save_task_metadata(self.redis, task_id, metadata)

        except Exception as e:
            err_str = str(e).lower()
            if 'timeout' not in err_str and 'timed out' not in err_str:
                logger.error(f"Crashed tasks check error: {e}")

    def webhook_resender_loop(self):
        """Background loop: retry failed webhook notifications."""
        while self.running:
            try:
                time.sleep(60)

                if not os.path.exists(TASKS_DIR):
                    continue

                scanned = 0
                retried = 0

                for task_id in os.listdir(TASKS_DIR):
                    task_path = os.path.join(TASKS_DIR, task_id)
                    if not os.path.isdir(task_path):
                        continue

                    scanned += 1
                    metadata_path = os.path.join(task_path, "metadata.json")
                    if not os.path.exists(metadata_path):
                        continue

                    try:
                        with open(metadata_path, 'r') as f:
                            metadata_raw = json.load(f)
                        if isinstance(metadata_raw, list) and len(metadata_raw) > 0:
                            metadata = metadata_raw[0]
                        elif isinstance(metadata_raw, dict):
                            metadata = metadata_raw
                        else:
                            continue
                    except Exception:
                        continue

                    status = metadata.get('status')
                    terminal_statuses = {'completed', 'failed', 'error', 'cancelled'}
                    if status not in terminal_statuses:
                        continue

                    webhook_state = metadata.get('webhook')
                    if not webhook_state:
                        continue

                    webhook_status = webhook_state.get('status', 'unknown')
                    if webhook_status == 'delivered':
                        continue

                    attempt = int(webhook_state.get('attempts', 0) or 0)
                    if attempt <= 0:
                        continue

                    next_retry = webhook_state.get('next_retry')
                    if next_retry:
                        try:
                            next_retry_dt = datetime.fromisoformat(next_retry)
                            if datetime.now() < next_retry_dt:
                                continue
                        except Exception:
                            pass

                    webhook_url = webhook_state.get('url')
                    if not webhook_url:
                        continue

                    logger.info(f"[{task_id[:8]}] Background webhook retry (attempt {attempt + 1}) → {webhook_url}")

                    try:
                        headers = {"Content-Type": "application/json"}
                        webhook_headers = webhook_state.get('headers', {})
                        if webhook_headers:
                            for k, v in webhook_headers.items():
                                if k.lower() != 'content-type':
                                    headers[k] = v

                        response = requests.post(webhook_url, json=metadata, headers=headers, timeout=30)

                        webhook_state['attempts'] = attempt + 1
                        webhook_state['last_attempt'] = datetime.now().isoformat()

                        if 200 <= response.status_code < 300:
                            webhook_state['status'] = 'delivered'
                            webhook_state['last_status'] = response.status_code
                            webhook_state['next_retry'] = None
                            logger.info(f"[{task_id[:8]}] ✓ Background webhook delivered ({response.status_code})")
                        else:
                            webhook_state['status'] = 'failed'
                            webhook_state['last_status'] = response.status_code
                            retry_delay = min(300, 60 * (2 ** attempt))
                            webhook_state['next_retry'] = (datetime.now() + timedelta(seconds=retry_delay)).isoformat()
                            logger.warning(f"[{task_id[:8]}] ✗ Background webhook failed ({response.status_code}), next retry in {retry_delay}s")

                        metadata['webhook'] = webhook_state
                        save_and_sync_metadata(self.redis, task_id, metadata, TASKS_DIR)
                        retried += 1

                    except Exception as webhook_error:
                        webhook_state['attempts'] = attempt + 1
                        webhook_state['last_attempt'] = datetime.now().isoformat()
                        webhook_state['status'] = 'failed'
                        webhook_state['last_error'] = str(webhook_error)
                        retry_delay = min(300, 60 * (2 ** attempt))
                        webhook_state['next_retry'] = (datetime.now() + timedelta(seconds=retry_delay)).isoformat()
                        logger.error(f"[{task_id[:8]}] ✗ Background webhook error: {webhook_error}")
                        metadata['webhook'] = webhook_state
                        save_and_sync_metadata(self.redis, task_id, metadata, TASKS_DIR)
                        retried += 1

                if retried > 0:
                    logger.debug(f"Webhook resender: scanned {scanned}, {retried} retried")

            except Exception as e:
                logger.error(f"Webhook resender error: {e}")

    def recovery_check_failed_tasks(self):
        """Background loop: check failed tasks and mark recoverable ones for retry."""
        while self.running:
            try:
                time.sleep(120)

                if not os.path.exists(TASKS_DIR):
                    continue

                checked = 0
                recovered = 0
                skipped = 0

                for task_id in os.listdir(TASKS_DIR):
                    task_path = os.path.join(TASKS_DIR, task_id)
                    if not os.path.isdir(task_path):
                        continue

                    checked += 1
                    metadata_path = os.path.join(task_path, "metadata.json")
                    if not os.path.exists(metadata_path):
                        continue

                    try:
                        with open(metadata_path, 'r') as f:
                            metadata_raw = json.load(f)
                        if isinstance(metadata_raw, list) and len(metadata_raw) > 0:
                            metadata = metadata_raw[0]
                        elif isinstance(metadata_raw, dict):
                            metadata = metadata_raw
                        else:
                            continue
                    except Exception:
                        continue

                    status = metadata.get('status')
                    if status not in ['failed', 'error']:
                        continue

                    retry_count = metadata.get('retry_count', 0)
                    max_retries = 3

                    if retry_count >= max_retries:
                        skipped += 1
                        continue

                    error_info = metadata.get('error', {})
                    if isinstance(error_info, dict):
                        if error_info.get('recoverable') is False:
                            skipped += 1
                            continue
                        if error_info.get('type') in ('file_too_large', 'size_limit_exceeded'):
                            skipped += 1
                            continue
                        error_message = error_info.get('message', '')
                    else:
                        error_message = str(error_info)

                    if not self._is_error_recoverable(error_message):
                        skipped += 1
                        continue

                    metadata['status'] = 'queued'
                    metadata['retry_count'] = retry_count + 1

                    try:
                        task_dir = os.path.join(TASKS_DIR, task_id)
                        for item in os.listdir(task_dir):
                            if item != "metadata.json":
                                item_path = os.path.join(task_dir, item)
                                if os.path.isfile(item_path):
                                    os.remove(item_path)
                                elif os.path.isdir(item_path):
                                    import shutil
                                    shutil.rmtree(item_path)

                        with open(metadata_path, 'w') as f:
                            json.dump(metadata, f, indent=2)

                        self.redis.setex(
                            f"{REDIS_TASK_PREFIX}{task_id}",
                            TASK_TTL_MINUTES * 60,
                            json.dumps(metadata)
                        )
                        self.redis.rpush(REDIS_QUEUED_TASKS_KEY, task_id)
                        logger.info(f"[{task_id[:8]}] 🔄 Re-enqueued for recovery (attempt {retry_count + 1}/{max_retries})")
                        recovered += 1
                    except Exception as e:
                        logger.error(f"[{task_id[:8]}] Failed to recover task: {e}")

                if checked > 0:
                    logger.debug(f"Recovery checker: checked {checked}, recovered {recovered}, skipped {skipped}")

            except Exception as e:
                logger.error(f"Recovery checker error: {e}")

    def _do_cleanup(self):
        """Single cleanup pass: remove expired and orphaned tasks."""
        if not os.path.exists(TASKS_DIR):
            return 0, 0, 0

        now = time.time()
        ttl_seconds = TASK_TTL_MINUTES * 60
        cleaned = 0
        orphaned = 0
        total_size_freed = 0

        try:
            for task_id in os.listdir(TASKS_DIR):
                task_path = os.path.join(TASKS_DIR, task_id)
                if not os.path.isdir(task_path):
                    continue

                try:
                    dir_size = sum(
                        os.path.getsize(os.path.join(dirpath, filename))
                        for dirpath, dirnames, filenames in os.walk(task_path)
                        for filename in filenames
                    )
                except Exception:
                    dir_size = 0

                metadata_path = os.path.join(task_path, 'metadata.json')

                if not os.path.exists(metadata_path):
                    try:
                        import shutil
                        shutil.rmtree(task_path, ignore_errors=True)
                        cleanup_task_from_redis(self.redis, task_id)
                        orphaned += 1
                        total_size_freed += dir_size
                        logger.info(f"[{task_id[:8]}] 🗑️ Removed orphaned | {dir_size/1024/1024:.1f} MB")
                    except Exception as e:
                        logger.error(f"[{task_id[:8]}] Failed to delete orphaned: {e}")
                    continue

                try:
                    task_mtime = os.path.getmtime(task_path)
                    age_seconds = now - task_mtime

                    if age_seconds > ttl_seconds:
                        import shutil
                        shutil.rmtree(task_path)
                        cleanup_task_from_redis(self.redis, task_id)
                        cleaned += 1
                        total_size_freed += dir_size
                        logger.info(f"[{task_id[:8]}] 🗑️ Removed expired | {dir_size/1024/1024:.1f} MB | age: {age_seconds/3600:.1f}h")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

        return cleaned, orphaned, total_size_freed

    def cleanup_loop(self):
        """Background loop: periodically run cleanup."""
        while self.running:
            try:
                time.sleep(CLEANUP_INTERVAL_SECONDS)
                cleaned, orphaned, total_size_freed = self._do_cleanup()
                if cleaned > 0 or orphaned > 0:
                    total_size_mb = total_size_freed / 1024 / 1024
                    logger.info(f"🧹 Cleanup: {cleaned} expired, {orphaned} orphaned | {total_size_mb:.1f} MB freed")
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")

    def run(self):
        """Main orchestrator loop."""
        if not self.wait_for_redis():
            logger.error("Failed to connect to Redis - exiting")
            sys.exit(1)

        try:
            self.redis.delete(REDIS_ACTIVE_TASKS_KEY)
            logger.debug("  🧹 Cleared active tasks markers (startup reset)")
        except Exception as e:
            logger.warning(f"  ⚠️  Failed to clear active tasks: {e}")

        cleaned, orphaned, total_size = self._do_cleanup()
        if cleaned > 0 or orphaned > 0:
            total_size_mb = total_size / 1024 / 1024
            logger.info(f"  🧹 Startup cleanup: {cleaned} expired, {orphaned} orphaned | {total_size_mb:.1f} MB freed")

        recovery_count, enqueued_count = self.recovery_initialize_redis_from_disk()
        self.recovery_done = True

        try:
            logger.info(" ")
            logger.info("=" * 70)
            logger.info("📥 YouTube Downloader API - Orchestrator".center(70))
            logger.info("=" * 70)
            logger.info(" ")
            logger.info("⚙️  System Configuration:")
            logger.info(f"   🔌 Redis:         {REDIS_HOST}:{REDIS_PORT} (db {REDIS_DB})")
            logger.info(f"   📦 Tasks:         max_concurrent={MAX_CONCURRENT_TASKS}, max_queued={MAX_QUEUED_TASKS}, ttl={TASK_TTL_MINUTES}m (24h)")
            logger.info(f"   🔄 Recovery:      max_retries={MAX_TASK_RETRIES}, delay={RETRY_DELAY_SECONDS}s")
            logger.info(f"   📨 Webhook:       max_retries={WEBHOOK_MAX_RETRY_ATTEMPTS}, retry_delay={WEBHOOK_RETRY_DELAY_SECONDS}s")
            logger.info(f"   🧹 Cleanup:       every {CLEANUP_INTERVAL_SECONDS}s")
            logger.info(f"   📥 Video Limits:  max_size={MAX_DOWNLOAD_VIDEO_SIZE_MB}MB")
            logger.info(f"   📝 Metadata:      max_bytes={MAX_CLIENT_META_BYTES}B, max_depth={MAX_CLIENT_META_DEPTH}, max_keys={MAX_CLIENT_META_KEYS}")
            logger.info("   🎬 Platforms:     YouTube only")
            logger.info(" ")
            logger.info("📡 Background Services:")
            logger.info("   📨 Webhook Worker:  Active")
            logger.info("   🔄 Task Recovery:   Active")
            logger.info("   🧹 Cleanup Service: Active")
            logger.info(" ")
            logger.info("🔐 Authorization:")
            if API_KEY_ENABLED:
                logger.info("   🔑 Auth Mode: Authorization Bearer (Enabled)")
            else:
                logger.info("=" * 80)
                logger.info("    WARNING: API_KEY environment variable is not set!")
                logger.info("    All API endpoints will be DISABLED (except /health)")
                logger.info("    Set API_KEY to enable API functionality")
                logger.info("=" * 80)
            logger.info(" ")
            logger.info("📡 API Endpoints:")
            logger.info("     POST /download_video     → download YouTube video")
            logger.info("     GET  /task_status/<id>   → check task status")
            logger.info("     GET  /download/<id>/<f>  → download result file")
            logger.info("     GET  /health             → service health check")
            logger.info("     GET  /api/version        → API documentation")
            logger.info("  📍 Versioned: same endpoints under /api/v1/")
            logger.info(" ")
            logger.info(f"   API_KEY={'***set***' if API_KEY else 'not set'}")
            logger.info(f"   PUBLIC_BASE_URL={PUBLIC_BASE_URL or 'not set'}")
            logger.info(f"   INTERNAL_BASE_URL={INTERNAL_BASE_URL or 'not set'}")
            logger.info(f"   MAX_DOWNLOAD_VIDEO_SIZE_MB={MAX_DOWNLOAD_VIDEO_SIZE_MB}")
            logger.info(f"   MEMORY_LIMIT={os.getenv('MEMORY_LIMIT', 'not set')}")
            logger.info(" ")
            logger.info("=" * 70)
            logger.info(" ")
            logger.info("📊 Startup results: cleaned=%d, loaded=%d, enqueued=%d", cleaned + orphaned, recovery_count, enqueued_count)
            if API_KEY_ENABLED:
                logger.info("✅ System ready - waiting for tasks...")
        finally:
            timestamp_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
            root_logger = logging.getLogger()
            for h in root_logger.handlers:
                h.setFormatter(timestamp_formatter)

        webhook_thread = threading.Thread(target=self.webhook_resender_loop, name='webhook-resender', daemon=True)
        webhook_thread.start()

        recovery_thread = threading.Thread(target=self.recovery_check_failed_tasks, name='recovery-checker', daemon=True)
        recovery_thread.start()

        cleanup_thread = threading.Thread(target=self.cleanup_loop, name='task-cleanup', daemon=True)
        cleanup_thread.start()

        try:
            with open(self.system_ready_file, 'w') as f:
                f.write('ready\n')
        except Exception as e:
            logger.warning(f"Failed to write system ready flag: {e}")

        while self.running:
            try:
                self.check_and_start_workers()
                time.sleep(5)
            except KeyboardInterrupt:
                logger.info("Orchestrator shutting down...")
                self.running = False
            except Exception as e:
                logger.error(f"Orchestration loop error: {e}")
                time.sleep(5)


def main():
    try:
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            socket_connect_timeout=5,
            socket_timeout=5,
            decode_responses=True
        )
        orchestrator = TaskOrchestrator(redis_client)
        orchestrator.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
