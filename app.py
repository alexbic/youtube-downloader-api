import os
import threading
import json
import logging
import redis
import uuid
import time
from functools import wraps
from datetime import datetime, timedelta
from typing import Any

import requests
import yt_dlp
from flask import Flask, Blueprint, request, jsonify, send_file

from api_commons import (
    ERROR_MISSING_AUTH_TOKEN,
    ERROR_INVALID_API_KEY,
    ERROR_MISSING_REQUIRED_FIELD,
    ERROR_INVALID_URL,
    ERROR_INVALID_WEBHOOK_URL,
    ERROR_INVALID_WEBHOOK_HEADERS,
    ERROR_INVALID_CLIENT_META,
    ERROR_TASK_NOT_FOUND,
    ERROR_FILE_NOT_FOUND,
    ERROR_INVALID_PATH,
    ERROR_UNKNOWN,
    create_simple_error,
    create_task_error,
    map_youtube_error_type_to_code,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (fixed for public version)
# ---------------------------------------------------------------------------
TASK_TTL_MINUTES = 1440                # 24 h — not configurable
MAX_CONCURRENT_TASKS = 2              # fixed limit
MAX_DOWNLOAD_VIDEO_SIZE_MB = int(os.getenv("MAX_DOWNLOAD_VIDEO_SIZE_MB", "2048"))
API_KEY = os.getenv("API_KEY", "")
TASKS_DIR = os.getenv("TASKS_DIR", "/app/tasks")  # must match orchestrator
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:5000")

SUPPORTED_PLATFORMS: dict[str, str] = {
    "youtube.com": "YouTube",
    "www.youtube.com": "YouTube",
    "m.youtube.com": "YouTube",
    "music.youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "www.youtu.be": "YouTube",
}

os.makedirs(TASKS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Redis client
# ---------------------------------------------------------------------------
redis_client: redis.Redis = redis.from_url(REDIS_URL, decode_responses=True)

# ---------------------------------------------------------------------------
# In-process state
# ---------------------------------------------------------------------------
active_task_count = 0
active_task_count_lock = threading.Lock()

WORKER_ID = f"worker-{os.getpid()}"

# ---------------------------------------------------------------------------
# Flask app & Blueprint
# ---------------------------------------------------------------------------
app = Flask(__name__)
api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if API_KEY:
            token = request.headers.get("Authorization", "")
            if not token:
                return jsonify(create_simple_error(ERROR_MISSING_AUTH_TOKEN)), 401
            if token.replace("Bearer ", "") != API_KEY:
                return jsonify(create_simple_error(ERROR_INVALID_API_KEY)), 403
        return f(*args, **kwargs)
    return decorated


def _platform_for_url(url: str) -> str | None:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        return SUPPORTED_PLATFORMS.get(host)
    except Exception:
        return None


def _task_dir(task_id: str) -> str:
    return os.path.join(TASKS_DIR, task_id)


def _meta_path(task_id: str) -> str:
    return os.path.join(_task_dir(task_id), "metadata.json")


def _save_task(task: dict) -> None:
    task_id = task["task_id"]
    os.makedirs(_task_dir(task_id), exist_ok=True)
    path = _meta_path(task_id)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    # Sync to Redis (non-critical)
    try:
        redis_client.setex(
            f"task:{task_id}",
            TASK_TTL_MINUTES * 60,
            json.dumps(task),
        )
    except Exception:
        pass


def _load_task(task_id: str) -> dict | None:
    path = _meta_path(task_id)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    # Fallback: Redis
    try:
        raw = redis_client.get(f"task:{task_id}")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _update_task(task_id: str, updates: dict) -> dict | None:
    task = _load_task(task_id)
    if task is None:
        return None
    task.update(updates)
    _save_task(task)
    return task


def _send_webhook(task: dict) -> None:
    webhook_url = task.get("webhook_url")
    if not webhook_url:
        return
    headers = {"Content-Type": "application/json"}
    if task.get("webhook_headers"):
        headers.update(task["webhook_headers"])
    payload = {
        "task_id": task["task_id"],
        "status": task["status"],
        "client_meta": task.get("client_meta"),
    }
    if task["status"] == "completed":
        payload["result"] = task.get("result")
    elif task["status"] == "failed":
        payload["error"] = task.get("error")

    def _try_send():
        for attempt in range(1, 4):
            try:
                resp = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
                if resp.status_code < 400:
                    log.info(f"[{task['task_id'][:8]}] Webhook delivered (attempt {attempt})")
                    return
                log.warning(f"[{task['task_id'][:8]}] Webhook HTTP {resp.status_code} (attempt {attempt})")
            except Exception as exc:
                log.warning(f"[{task['task_id'][:8]}] Webhook error (attempt {attempt}): {exc}")
            time.sleep(2 ** attempt)
        log.error(f"[{task['task_id'][:8]}] Webhook failed after 3 attempts")

    threading.Thread(target=_try_send, daemon=True).start()


# ---------------------------------------------------------------------------
# Redis wait on startup
# ---------------------------------------------------------------------------

def _wait_for_redis(timeout: int = 30) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            redis_client.ping()
            log.info("Redis: connected")
            return
        except Exception:
            time.sleep(1)
    log.warning("Redis: not reachable after startup wait — continuing anyway")


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

def _heartbeat_loop() -> None:
    while True:
        try:
            redis_client.setex(f"heartbeat:{WORKER_ID}", 120, int(time.time()))
        except Exception:
            pass
        time.sleep(30)


threading.Thread(target=_heartbeat_loop, daemon=True, name="heartbeat").start()


# ---------------------------------------------------------------------------
# Queue consumer
# ---------------------------------------------------------------------------
_queue_stop = threading.Event()


def _queue_loader_loop() -> None:
    log.info("Queue consumer started")
    while not _queue_stop.is_set():
        try:
            global active_task_count
            with active_task_count_lock:
                slots = MAX_CONCURRENT_TASKS - active_task_count
            if slots <= 0:
                time.sleep(0.5)
                continue

            item = redis_client.lpop("queue:queued")
            if not item:
                time.sleep(0.5)
                continue

            task_id = item.strip()
            task = _load_task(task_id)
            if task is None:
                log.warning(f"Queued task {task_id[:8]} not found, skipping")
                continue
            if task.get("status") != "queued":
                log.debug(f"Task {task_id[:8]} already {task.get('status')}, skipping")
                continue

            _update_task(task_id, {"status": "processing", "started_at": datetime.utcnow().isoformat()})
            with active_task_count_lock:
                active_task_count += 1
            threading.Thread(
                target=_background_download,
                args=(task_id,),
                daemon=True,
                name=f"dl-{task_id[:8]}",
            ).start()
        except Exception as exc:
            log.error(f"Queue loop error: {exc}", exc_info=True)
            time.sleep(1)


threading.Thread(target=_queue_loader_loop, daemon=True, name="queue-consumer").start()


# ---------------------------------------------------------------------------
# Download worker
# ---------------------------------------------------------------------------

def _build_ydl_opts(task_id: str, format_str: str | None, max_mb: float) -> dict:
    task_dir = _task_dir(task_id)
    os.makedirs(task_dir, exist_ok=True)
    opts: dict[str, Any] = {
        "outtmpl": os.path.join(task_dir, "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if format_str:
        opts["format"] = format_str
    else:
        opts["format"] = f"bestvideo[filesize<={max_mb}M]+bestaudio/best[filesize<={max_mb}M]/best"

    try:
        from yt_dlp_plugins.extractor.getpot_bgutil import GetPotBgUtilIE  # noqa: F401
        opts["extractor_args"] = {"youtube": {"pot_provider": "bgutil"}}
        log.debug(f"[{task_id[:8]}] bgutil enabled")
    except ImportError:
        pass

    return opts


def _background_download(task_id: str) -> None:
    global active_task_count
    try:
        task = _load_task(task_id)
        if task is None:
            log.error(f"[{task_id[:8]}] Task missing at download start")
            return

        url = task["url"]
        format_str = task.get("format")
        max_mb = task.get("max_size_mb", MAX_DOWNLOAD_VIDEO_SIZE_MB)
        opts = _build_ydl_opts(task_id, format_str, max_mb)

        log.info(f"[{task_id[:8]}] Downloading: {url}")

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if info is None:
            raise RuntimeError("yt-dlp returned no info")

        task_dir = _task_dir(task_id)
        downloaded = [f for f in os.listdir(task_dir) if f != "metadata.json"]
        if not downloaded:
            raise RuntimeError("No file downloaded")

        filename = downloaded[0]
        filepath = os.path.join(task_dir, filename)
        file_size = os.path.getsize(filepath)

        download_url = f"{SERVER_BASE_URL}/download/{task_id}/{filename}"
        result = {
            "filename": filename,
            "download_url": download_url,
            "file_size_bytes": file_size,
            "title": info.get("title"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "uploader": info.get("uploader"),
            "platform": "YouTube",
        }
        task = _update_task(task_id, {
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
            "result": result,
        })
        log.info(f"[{task_id[:8]}] Done: {filename} ({file_size} bytes)")
        _send_webhook(task)

    except yt_dlp.utils.DownloadError as exc:
        error_str = str(exc)
        error_code = map_youtube_error_type_to_code(error_str)
        log.error(f"[{task_id[:8]}] DownloadError: {error_str[:300]}")
        task = _update_task(task_id, {
            "status": "failed",
            "failed_at": datetime.utcnow().isoformat(),
            "error": create_task_error(error_code, error_str[:500]),
        })
        _send_webhook(task)
    except Exception as exc:
        log.error(f"[{task_id[:8]}] Error: {exc}", exc_info=True)
        task = _update_task(task_id, {
            "status": "failed",
            "failed_at": datetime.utcnow().isoformat(),
            "error": create_task_error(ERROR_UNKNOWN, str(exc)[:500]),
        })
        _send_webhook(task)
    finally:
        with active_task_count_lock:
            active_task_count = max(0, active_task_count - 1)


# ---------------------------------------------------------------------------
# Cleanup expired tasks
# ---------------------------------------------------------------------------

def _cleanup_loop() -> None:
    while True:
        time.sleep(3600)
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=TASK_TTL_MINUTES)
            for task_id in os.listdir(TASKS_DIR):
                task_dir = os.path.join(TASKS_DIR, task_id)
                if not os.path.isdir(task_dir):
                    continue
                path = os.path.join(task_dir, "metadata.json")
                if not os.path.exists(path):
                    continue
                try:
                    with open(path) as f:
                        task = json.load(f)
                    created = datetime.fromisoformat(task.get("created_at", ""))
                    if created < cutoff:
                        import shutil
                        shutil.rmtree(task_dir, ignore_errors=True)
                        try:
                            redis_client.delete(f"task:{task_id}")
                        except Exception:
                            pass
                        log.info(f"[cleanup] Removed expired task {task_id[:8]}")
                except Exception as exc:
                    log.warning(f"[cleanup] {task_id[:8]}: {exc}")
        except Exception as exc:
            log.error(f"[cleanup] Loop error: {exc}", exc_info=True)


threading.Thread(target=_cleanup_loop, daemon=True, name="cleanup").start()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _download_video_handler():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify(create_simple_error(ERROR_MISSING_REQUIRED_FIELD, field="url")), 400

    platform = _platform_for_url(url)
    if platform is None:
        return jsonify(create_simple_error(ERROR_INVALID_URL, detail="Only YouTube URLs are supported")), 400

    webhook_url = data.get("webhook_url", "").strip() or None
    if webhook_url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(webhook_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return jsonify(create_simple_error(ERROR_INVALID_WEBHOOK_URL)), 400
        except Exception:
            return jsonify(create_simple_error(ERROR_INVALID_WEBHOOK_URL)), 400

    webhook_headers = data.get("webhook_headers") or None
    if webhook_headers is not None and not isinstance(webhook_headers, dict):
        return jsonify(create_simple_error(ERROR_INVALID_WEBHOOK_HEADERS)), 400

    client_meta = data.get("client_meta") or None
    if client_meta is not None and not isinstance(client_meta, dict):
        return jsonify(create_simple_error(ERROR_INVALID_CLIENT_META)), 400

    task_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    task: dict[str, Any] = {
        "task_id": task_id,
        "status": "queued",
        "created_at": now,
        "url": url,
        "platform": platform,
        "format": data.get("format"),
        "max_size_mb": data.get("max_size_mb", MAX_DOWNLOAD_VIDEO_SIZE_MB),
        "webhook_url": webhook_url,
        "webhook_headers": webhook_headers,
        "client_meta": client_meta,
    }
    _save_task(task)
    redis_client.rpush("queue:queued", task_id)
    log.info(f"[{task_id[:8]}] Queued: {url}")

    return jsonify({
        "task_id": task_id,
        "status": "queued",
        "created_at": now,
        "platform": platform,
    }), 202


@app.route("/download_video", methods=["POST"])
@api_v1.route("/download_video", methods=["POST"])
@require_api_key
def download_video():
    return _download_video_handler()


# ---------------------------------------------------------------------------

def _task_status_handler(task_id: str):
    task = _load_task(task_id)
    if task is None:
        return jsonify(create_simple_error(ERROR_TASK_NOT_FOUND)), 404
    resp: dict[str, Any] = {
        "task_id": task_id,
        "status": task["status"],
        "created_at": task.get("created_at"),
        "platform": task.get("platform"),
        "url": task.get("url"),
    }
    if task["status"] == "completed":
        resp["result"] = task.get("result")
        resp["completed_at"] = task.get("completed_at")
    elif task["status"] == "failed":
        resp["error"] = task.get("error")
        resp["failed_at"] = task.get("failed_at")
    elif task["status"] == "processing":
        resp["started_at"] = task.get("started_at")
    return jsonify(resp), 200


@app.route("/task_status/<task_id>", methods=["GET"])
@api_v1.route("/task_status/<task_id>", methods=["GET"])
@require_api_key
def task_status(task_id: str):
    return _task_status_handler(task_id)


# ---------------------------------------------------------------------------

@app.route("/download/<path:inner_path>", methods=["GET"])
@api_v1.route("/download/<path:inner_path>", methods=["GET"])
@require_api_key
def serve_file(inner_path: str):
    parts = inner_path.split("/", 1)
    if len(parts) != 2:
        return jsonify(create_simple_error(ERROR_INVALID_PATH)), 400
    task_id, filename = parts
    if ".." in task_id or ".." in filename:
        return jsonify(create_simple_error(ERROR_INVALID_PATH)), 400
    filepath = os.path.join(TASKS_DIR, task_id, filename)
    if not os.path.isfile(filepath):
        return jsonify(create_simple_error(ERROR_FILE_NOT_FOUND)), 404
    return send_file(filepath, as_attachment=True)


# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
@api_v1.route("/health", methods=["GET"])
def health():
    try:
        redis_client.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    with active_task_count_lock:
        running = active_task_count

    queued = 0
    try:
        queued = redis_client.llen("queue:queued")
    except Exception:
        pass

    return jsonify({
        "status": "ok" if redis_ok else "degraded",
        "redis": "ok" if redis_ok else "unavailable",
        "active_tasks": running,
        "queued_tasks": queued,
        "max_concurrent_tasks": MAX_CONCURRENT_TASKS,
        "worker_id": WORKER_ID,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }), 200


# ---------------------------------------------------------------------------

@app.route("/api/version", methods=["GET"])
@api_v1.route("/version", methods=["GET"])
def version():
    return jsonify({
        "service": "youtube-downloader-api",
        "version": "2.0.0",
        "supported_platforms": list(set(SUPPORTED_PLATFORMS.values())),
    }), 200


# ---------------------------------------------------------------------------
# Register Blueprint
# ---------------------------------------------------------------------------
app.register_blueprint(api_v1)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def _startup() -> None:
    log.info("=" * 60)
    log.info("  YouTube Downloader API  (public build)")
    log.info("=" * 60)
    log.info(f"  Worker ID      : {WORKER_ID}")
    log.info(f"  Max concurrent : {MAX_CONCURRENT_TASKS}")
    log.info(f"  Task TTL       : {TASK_TTL_MINUTES} min (24h)")
    log.info(f"  Tasks dir      : {TASKS_DIR}")
    log.info(f"  Redis          : {REDIS_URL}")
    log.info(f"  Base URL       : {SERVER_BASE_URL}")
    log.info("=" * 60)
    _wait_for_redis()


_startup()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
