
import os
import json
import logging
from flask import Flask, request, jsonify, send_file
import yt_dlp
from datetime import datetime
import uuid
import threading
from functools import wraps
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yt-dlp-api")

API_KEY = os.getenv('API_KEY')
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL') or os.getenv('EXTERNAL_BASE_URL')
# Опциональный базовый URL для внутреннего контура (Docker network)
INTERNAL_BASE_URL = os.getenv('INTERNAL_BASE_URL')
# Авторизация требуется только если указан внешний URL и задан ключ
AUTH_REQUIRED = bool(PUBLIC_BASE_URL) and bool(API_KEY)

def log_startup_info():
    public_url = PUBLIC_BASE_URL
    logger.info("=" * 60)
    logger.info("YouTube Downloader API starting...")
    logger.info(f"Auth: {'REQUIRED' if AUTH_REQUIRED else 'DISABLED'} (depends on PUBLIC_BASE_URL & API_KEY)")
    if public_url and API_KEY:
        logger.info("Mode: PUBLIC API with external URLs")
        logger.info(f"Base URL: {public_url}")
    else:
        logger.info("Mode: INTERNAL (Docker network)")
        if public_url and not API_KEY:
            logger.warning("WARNING: PUBLIC_BASE_URL is set but API_KEY is not! PUBLIC access is DISABLED. Using internal URLs.")
    if INTERNAL_BASE_URL:
        logger.info(f"Internal base URL: {INTERNAL_BASE_URL}")
    # Некоторые константы могут быть ещё не определены при импорте — проверяем наличие
    if 'DOWNLOAD_DIR' in globals():
        logger.info(f"Downloads dir: {DOWNLOAD_DIR}")
    if 'TASKS_DIR' in globals():
        logger.info(f"Tasks dir: {TASKS_DIR}")
    if 'COOKIES_PATH' in globals():
        logger.info(f"Cookies file: {COOKIES_PATH} {'(exists)' if os.path.exists(COOKIES_PATH) else '(not found)'}")
    if 'MAX_CLIENT_META_BYTES' in globals():
        logger.info(f"client_meta limits: bytes={MAX_CLIENT_META_BYTES}, depth={MAX_CLIENT_META_DEPTH}, keys={MAX_CLIENT_META_KEYS}, str_len={MAX_CLIENT_META_STRING_LENGTH}, list_len={MAX_CLIENT_META_LIST_LENGTH}")
    if 'STORAGE_MODE' in globals():
        if STORAGE_MODE == 'redis' and 'REDIS_HOST' in globals():
            logger.info(f"Storage: redis ({REDIS_HOST}:{REDIS_PORT}/db{REDIS_DB})")
        else:
            logger.info("Storage: memory (single-process)")
    logger.info(f"yt-dlp version: {get_yt_dlp_version()}")
    logger.info("=" * 60)

def get_yt_dlp_version():
    try:
        return yt_dlp.version.__version__
    except Exception:
        return 'unknown'

app = Flask(__name__)

# ============================================
# AUTH CONFIG
# ============================================

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not AUTH_REQUIRED:
            return f(*args, **kwargs)
        # Primary: Authorization: Bearer <token>
        auth_header = request.headers.get('Authorization', '')
        token = None
        if auth_header.lower().startswith('bearer '):
            token = auth_header.split(' ', 1)[1].strip()
        # Backward-compat: X-API-Key
        if not token:
            token = request.headers.get('X-API-Key')
        if not token:
            return jsonify({"error": "Missing Authorization Bearer token or X-API-Key"}), 401
        if token != API_KEY:
            return jsonify({"error": "Invalid API key"}), 403
        return f(*args, **kwargs)
    return decorated

# ============================================
# URL HELPERS
# ============================================
def _join_url(base: str, path: str) -> str:
    if not base:
        return path
    return f"{base.rstrip('/')}/{path.lstrip('/')}"

def get_link_base() -> str | None:
    try:
        if PUBLIC_BASE_URL and API_KEY:
            return PUBLIC_BASE_URL
        if request and hasattr(request, 'host_url') and request.host_url:
            return request.host_url
    except Exception:
        return None
    return None

def build_absolute_url(path: str, base: str | None = None) -> str:
    try:
        base_url = base or get_link_base()
        if base_url:
            return _join_url(base_url, path)
    except Exception:
        pass
    return path

def build_internal_url(path: str, base: str | None = None) -> str:
    try:
        base_url = base or INTERNAL_BASE_URL
        if not base_url and request and hasattr(request, 'host_url') and request.host_url:
            base_url = request.host_url
        if base_url:
            return _join_url(base_url, path)
    except Exception:
        pass
    return path

# ============================================
# DIRECTORIES & TASKS
# ============================================
DOWNLOAD_DIR = "/app/downloads"
TASKS_DIR = "/app/tasks"
COOKIES_PATH = "/app/cookies.txt"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(TASKS_DIR, exist_ok=True)

def get_task_dir(task_id: str) -> str:
    return os.path.join(TASKS_DIR, task_id)

def get_task_output_dir(task_id: str) -> str:
    return os.path.join(get_task_dir(task_id), "output")

def create_task_dirs(task_id: str):
    os.makedirs(get_task_output_dir(task_id), exist_ok=True)

def build_download_path(task_id: str, filename: str) -> str:
    return f"/download/{task_id}/output/{filename}"

def save_task_metadata(task_id: str, metadata: dict):
    meta_path = os.path.join(get_task_dir(task_id), "metadata.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

# ============================================
# TASK STORAGE (Redis or Memory)
# ============================================
STORAGE_MODE = "memory"
tasks_store: Dict[str, Dict[str, Any]] = {}
redis_client = None
REDIS_HOST = os.getenv('REDIS_HOST', 'redis')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))

try:
    import redis  # type: ignore
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2
    )
    redis_client.ping()
    STORAGE_MODE = "redis"
except Exception:
    redis_client = None
    STORAGE_MODE = "memory"

def save_task(task_id: str, data: dict):
    if STORAGE_MODE == "redis" and redis_client is not None:
        try:
            redis_client.setex(f"task:{task_id}", 86400, json.dumps(data, ensure_ascii=False))
            return
        except Exception:
            pass
    tasks_store[task_id] = data

def get_task(task_id: str):
    if STORAGE_MODE == "redis" and redis_client is not None:
        try:
            data = redis_client.get(f"task:{task_id}")
            return json.loads(data) if data else None
        except Exception:
            return tasks_store.get(task_id)
    return tasks_store.get(task_id)

def update_task(task_id: str, updates: dict):
    t = get_task(task_id)
    if t:
        t.update(updates)
        save_task(task_id, t)

# ============================================
# client_meta VALIDATION (simplified)
# ============================================
MAX_CLIENT_META_BYTES = int(os.getenv('MAX_CLIENT_META_BYTES', 16 * 1024))
MAX_CLIENT_META_DEPTH = int(os.getenv('MAX_CLIENT_META_DEPTH', 5))
MAX_CLIENT_META_KEYS = int(os.getenv('MAX_CLIENT_META_KEYS', 200))
MAX_CLIENT_META_STRING_LENGTH = int(os.getenv('MAX_CLIENT_META_STRING_LENGTH', 1000))
MAX_CLIENT_META_LIST_LENGTH = int(os.getenv('MAX_CLIENT_META_LIST_LENGTH', 200))
ALLOWED_JSON_PRIMITIVES = (str, int, float, bool, type(None))

def _validate_meta_structure(node, depth=0, counters=None):
    if counters is None:
        counters = {'keys': 0}
    if depth > MAX_CLIENT_META_DEPTH:
        return False, f"client_meta depth exceeds {MAX_CLIENT_META_DEPTH}"
    if isinstance(node, dict):
        counters['keys'] += len(node)
        if counters['keys'] > MAX_CLIENT_META_KEYS:
            return False, f"client_meta total keys exceed {MAX_CLIENT_META_KEYS}"
        for k, v in node.items():
            if not isinstance(k, str):
                return False, "client_meta keys must be strings"
            if len(k) > MAX_CLIENT_META_STRING_LENGTH:
                return False, f"client_meta key too long (> {MAX_CLIENT_META_STRING_LENGTH})"
            ok, err = _validate_meta_structure(v, depth + 1, counters)
            if not ok:
                return ok, err
        return True, None
    if isinstance(node, list):
        if len(node) > MAX_CLIENT_META_LIST_LENGTH:
            return False, f"client_meta list too long (> {MAX_CLIENT_META_LIST_LENGTH})"
        for item in node:
            ok, err = _validate_meta_structure(item, depth + 1, counters)
            if not ok:
                return ok, err
        return True, None
    if isinstance(node, ALLOWED_JSON_PRIMITIVES):
        if isinstance(node, str) and len(node) > MAX_CLIENT_META_STRING_LENGTH:
            return False, f"client_meta string too long (> {MAX_CLIENT_META_STRING_LENGTH})"
        return True, None
    return False, "client_meta contains unsupported value type"

def validate_client_meta(client_meta):
    if client_meta is None:
        return True, None
    if not isinstance(client_meta, dict):
        return False, "client_meta must be a JSON object"
    ok, err = _validate_meta_structure(client_meta)
    if not ok:
        return False, err
    meta_bytes = json.dumps(client_meta, ensure_ascii=False).encode('utf-8')
    if len(meta_bytes) > MAX_CLIENT_META_BYTES:
        return False, f"client_meta exceeds {MAX_CLIENT_META_BYTES} bytes"
    return True, None

def classify_youtube_error(error_message: str) -> dict:
    """Классифицирует ошибку YouTube для автоматической обработки"""
    error_lower = error_message.lower()
    
    if 'private video' in error_lower:
        return {
            "error_type": "private_video",
            "error_message": "Video is private",
            "user_action": "Mark as unavailable - private video"
        }
    elif 'video unavailable' in error_lower or 'this video is unavailable' in error_lower:
        return {
            "error_type": "unavailable",
            "error_message": "Video is unavailable",
            "user_action": "Mark as unavailable - deleted or removed"
        }
    elif 'video has been removed' in error_lower or 'deleted' in error_lower:
        return {
            "error_type": "deleted",
            "error_message": "Video has been removed",
            "user_action": "Mark as unavailable - deleted by uploader"
        }
    elif 'not available in your country' in error_lower or 'region' in error_lower:
        return {
            "error_type": "region_blocked",
            "error_message": "Video is not available in your region",
            "user_action": "Mark as region-restricted"
        }
    elif 'sign in to confirm' in error_lower and 'age' in error_lower:
        return {
            "error_type": "age_restricted",
            "error_message": "Video is age-restricted",
            "user_action": "Requires authentication - age verification"
        }
    elif 'copyright' in error_lower or 'copyright claim' in error_lower:
        return {
            "error_type": "copyright_claim",
            "error_message": "Video removed due to copyright claim",
            "user_action": "Mark as unavailable - copyright"
        }
    elif 'video not found' in error_lower or 'video id' in error_lower and 'invalid' in error_lower:
        return {
            "error_type": "not_found",
            "error_message": "Video not found",
            "user_action": "Mark as unavailable - invalid ID"
        }
    elif 'sign in' in error_lower or 'bot' in error_lower:
        return {
            "error_type": "authentication_required",
            "error_message": "YouTube requires authentication (cookies needed)",
            "user_action": "Check cookies file or retry later"
        }
    else:
        return {
            "error_type": "unknown",
            "error_message": error_message[:500],
            "user_action": "Review error manually"
        }

# Вызов логирования после определения всех лимитов и функций (однократно при импорте)
log_startup_info()

# ============================================
# CLEANUP
# ============================================
def cleanup_old_files():
    import time, shutil
    now = time.time()
    try:
        for filename in os.listdir(DOWNLOAD_DIR):
            fp = os.path.join(DOWNLOAD_DIR, filename)
            if os.path.isfile(fp) and now - os.path.getmtime(fp) > 3600:
                os.remove(fp)
        for task_id in os.listdir(TASKS_DIR):
            tdir = os.path.join(TASKS_DIR, task_id)
            if os.path.isdir(tdir) and now - os.path.getmtime(tdir) > 3600:
                shutil.rmtree(tdir, ignore_errors=True)
    except Exception:
        pass

# ============================================
# HEALTH
# ============================================
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "auth": "enabled" if AUTH_REQUIRED else "disabled",
        "storage": STORAGE_MODE
    })

# ============================================
# GET DIRECT URL
# ============================================
@app.route('/get_direct_url', methods=['POST'])
@require_api_key
def get_direct_url():
    try:
        data = request.json or {}
        video_url = data.get('url')
        quality = data.get('quality', 'best[height<=720]')
        if not video_url:
            return jsonify({"error": "URL is required"}), 400
        ydl_opts = {'format': quality,'quiet': True,'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            http_headers = info.get('http_headers', {})
            return jsonify({
                "video_id": info.get('id'),
                "title": info.get('title'),
                "direct_url": info.get('url'),
                "duration": info.get('duration'),
                "filesize": info.get('filesize'),
                "filesize_approx": info.get('filesize_approx'),
                "ext": info.get('ext'),
                "resolution": info.get('resolution'),
                "fps": info.get('fps'),
                "thumbnail": info.get('thumbnail'),
                "uploader": info.get('uploader'),
                "upload_date": info.get('upload_date'),
                "http_headers": http_headers,
                "expiry_warning": "URL expires in a few hours. Use immediately or call /download_video to save permanently.",
                "processed_at": datetime.now().isoformat()
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================
# SYNC DOWNLOAD (download_video)
# ============================================
@app.route('/download_video', methods=['POST'])
@require_api_key
def download_video():
    try:
        data = request.json or {}
        video_url = data.get('url')
        quality = data.get('quality', 'best[height<=720]')
        cookies_from_browser = data.get('cookiesFromBrowser')
        client_meta = data.get('client_meta') or data.get('meta')
        if isinstance(client_meta, str):
            try:
                if len(client_meta.encode('utf-8')) > MAX_CLIENT_META_BYTES:
                    return jsonify({"error": f"Invalid client_meta: exceeds {MAX_CLIENT_META_BYTES} bytes"}), 400
                parsed = json.loads(client_meta)
                client_meta = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError as e:
                return jsonify({"error": f"Invalid client_meta JSON: {e}"}), 400
        ok, err = validate_client_meta(client_meta)
        if not ok:
            return jsonify({"error": f"Invalid client_meta: {err}"}), 400
        if not video_url:
            return jsonify({"error": "URL is required"}), 400

        # Async mode: start background task and return immediately
        if bool(data.get('async', False)):
            cleanup_old_files()
            task_id = str(uuid.uuid4())
            create_task_dirs(task_id)
            task_data = {
                "task_id": task_id,
                "status": "queued",
                "created_at": datetime.now().isoformat(),
                "video_url": video_url,
                "quality": quality,
                "cookies_from_browser": cookies_from_browser,
                "client_meta": client_meta
            }
            save_task(task_id, task_data)
            link_base_external = (PUBLIC_BASE_URL if (PUBLIC_BASE_URL and API_KEY) else None)
            link_base_internal = (INTERNAL_BASE_URL or (request.host_url.rstrip('/') if request and hasattr(request, 'host_url') else None))
            thread = threading.Thread(target=_background_download, args=(task_id, video_url, quality, client_meta, "download_video_async", link_base_external or "", link_base_internal or "", cookies_from_browser))
            thread.daemon = True
            thread.start()
            # В async-режиме всегда возвращаем только task_id и статус, ошибки — только через /task_status
            task_download_path = f"/download/{task_id}/output/pending"
            return jsonify({
                "task_id": task_id,
                "status": "processing",
                "check_status_url": build_absolute_url(f"/task_status/{task_id}", link_base_external),
                "check_status_url_internal": build_internal_url(f"/task_status/{task_id}", link_base_internal),
                "metadata_url": build_absolute_url(f"/download/{task_id}/metadata.json", link_base_external),
                "metadata_url_internal": build_internal_url(f"/download/{task_id}/metadata.json", link_base_internal),
                "client_meta": client_meta
            }), 202

        # Sync mode: download immediately and return result
        task_id = str(uuid.uuid4())
        create_task_dirs(task_id)
        safe_filename = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        outtmpl = os.path.join(get_task_output_dir(task_id), f'{safe_filename}.%(ext)s')
        ydl_opts = {'format': quality,'outtmpl': outtmpl,'quiet': True,'no_warnings': True}
        if cookies_from_browser:
            ydl_opts['cookiesfrombrowser'] = (cookies_from_browser,)
        elif os.path.exists(COOKIES_PATH):
            ydl_opts['cookiefile'] = COOKIES_PATH
        
        logger.info(f"[sync] yt-dlp opts for {video_url}: {ydl_opts}")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                ext = info.get('ext', 'mp4')
                filename = f"{safe_filename}.{ext}"
                file_path = os.path.join(get_task_output_dir(task_id), filename)
            if os.path.exists(file_path):
                os.chmod(file_path, 0o644)
                file_size = os.path.getsize(file_path)
                task_download_path = build_download_path(task_id, filename)
                task_download_url = build_absolute_url(task_download_path)
                task_download_url_internal = build_internal_url(task_download_path)
                metadata = {
                    "task_id": task_id,
                    "status": "completed",
                    "mode": "sync",
                    "operation": "download_video",
                    "video_id": info.get('id'),
                    "title": info.get('title'),
                    "filename": filename,
                    "file_size": file_size,
                    "duration": info.get('duration'),
                    "resolution": info.get('resolution'),
                    "ext": ext,
                    "completed_at": datetime.now().isoformat()
                }
                if client_meta is not None:
                    metadata['client_meta'] = client_meta
                save_task_metadata(task_id, metadata)
                return jsonify({
                    "task_id": task_id,
                    "status": "completed",
                    "video_id": info.get('id'),
                    "title": info.get('title'),
                    "filename": filename,
                    "file_size": file_size,
                    "task_download_path": task_download_path,
                    "task_download_url": task_download_url,
                    "task_download_url_internal": task_download_url_internal,
                    "metadata_url": build_absolute_url(f"/download/{task_id}/metadata.json"),
                    "metadata_url_internal": build_internal_url(f"/download/{task_id}/metadata.json"),
                    "duration": info.get('duration'),
                    "resolution": info.get('resolution'),
                    "ext": ext,
                    "client_meta": client_meta,
                    "processed_at": metadata['completed_at']
                })
            return jsonify({"error": "No file downloaded"}), 500
        except Exception as e:
            error_info = classify_youtube_error(str(e))
            metadata = {
                "task_id": task_id,
                "status": "error",
                "mode": "sync",
                "operation": "download_video",
                "error_type": error_info["error_type"],
                "error_message": error_info["error_message"],
                "user_action": error_info["user_action"],
                "raw_error": str(e)[:1000],
                "failed_at": datetime.now().isoformat()
            }
            if client_meta is not None:
                metadata['client_meta'] = client_meta
            save_task_metadata(task_id, metadata)
            return jsonify({
                "task_id": task_id,
                "status": "error",
                "error_type": error_info["error_type"],
                "error_message": error_info["error_message"],
                "user_action": error_info["user_action"],
                "metadata_url": f"/download/{task_id}/metadata.json",
                "client_meta": client_meta
            }), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================
# LEGACY DOWNLOAD FILE (root)
# ============================================
@app.route('/download_file/<filename>', methods=['GET'])
def download_file(filename):
    try:
        fp = os.path.join(DOWNLOAD_DIR, filename)
        if os.path.exists(fp):
            return send_file(fp, as_attachment=True)
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================
# TASK FILE DOWNLOAD
# ============================================
@app.route('/download/<path:inner_path>', methods=['GET'])
def download_task_file(inner_path):
    try:
        full_path = os.path.join(TASKS_DIR, inner_path)
        if not os.path.abspath(full_path).startswith(os.path.abspath(TASKS_DIR)):
            return jsonify({"error": "Invalid path"}), 403
        if os.path.exists(full_path) and os.path.isfile(full_path):
            return send_file(full_path, as_attachment=True, conditional=True)
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# download_direct endpoint removed as legacy

# ============================================
# VIDEO INFO
# ============================================
@app.route('/get_video_info', methods=['POST'])
@require_api_key
def get_video_info():
    try:
        data = request.json or {}
        video_url = data.get('url')
        if not video_url:
            return jsonify({"error": "URL is required"}), 400
        ydl_opts = {'quiet': True,'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return jsonify({
                "video_id": info.get('id'),
                "title": info.get('title'),
                "description": info.get('description', '')[:500],
                "duration": info.get('duration'),
                "view_count": info.get('view_count'),
                "like_count": info.get('like_count'),
                "uploader": info.get('uploader'),
                "upload_date": info.get('upload_date'),
                "thumbnail": info.get('thumbnail'),
                "tags": info.get('tags', [])[:10],
                "available_formats": len(info.get('formats', [])),
                "processed_at": datetime.now().isoformat()
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================
# TASK STATUS
# ============================================
@app.route('/task_status/<task_id>', methods=['GET'])
def task_status(task_id):
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    resp = {"task_id": task_id, "status": task.get('status'), "created_at": task.get('created_at')}
    if task.get('client_meta') is not None:
        resp['client_meta'] = task['client_meta']
    if task.get('status') == 'completed':
        resp.update({
            "video_id": task.get('video_id'),
            "title": task.get('title'),
            "filename": task.get('filename'),
            "task_download_path": task.get('task_download_path'),
            "task_download_url": build_absolute_url(task.get('task_download_path')) if task.get('task_download_path') else None,
            "task_download_url_internal": build_internal_url(task.get('task_download_path')) if task.get('task_download_path') else None,
            "metadata_url": build_absolute_url(f"/download/{task_id}/metadata.json"),
            "metadata_url_internal": build_internal_url(f"/download/{task_id}/metadata.json"),
            "duration": task.get('duration'),
            "resolution": task.get('resolution'),
            "ext": task.get('ext'),
            "completed_at": task.get('completed_at')
        })
    elif task.get('status') == 'error':
        resp['error_type'] = task.get('error_type', 'unknown')
        resp['error_message'] = task.get('error_message', task.get('error', 'Unknown error'))
        resp['user_action'] = task.get('user_action', 'Review error manually')
        if task.get('raw_error'):
            resp['raw_error'] = task.get('raw_error')
    return jsonify(resp)

def _background_download(
    task_id: str,
    video_url: str,
    quality: str,
    client_meta: dict,
    operation: str = "download_video_async",
    base_url_external: str = "",
    base_url_internal: str = "",
    cookies_from_browser: str = None
):
    try:
        update_task(task_id, {"status": "downloading"})
        safe_filename = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        outtmpl = os.path.join(get_task_output_dir(task_id), f"{safe_filename}.%(ext)s")
        ydl_opts = {
            'format': quality,
            'outtmpl': outtmpl,
            'quiet': True,
            'no_warnings': True
        }
        if cookies_from_browser:
            ydl_opts['cookiesfrombrowser'] = (cookies_from_browser,)
        elif os.path.exists(COOKIES_PATH):
            ydl_opts['cookiefile'] = COOKIES_PATH

        logger.info(f"[async] yt-dlp opts for {video_url}: {ydl_opts}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            ext = info.get('ext', 'mp4')

        filename = f"{safe_filename}.{ext}"
        file_path = os.path.join(get_task_output_dir(task_id), filename)
        if os.path.exists(file_path):
            os.chmod(file_path, 0o644)
            file_size = os.path.getsize(file_path)
            task_download_path = build_download_path(task_id, filename)
            full_task_download_url = build_absolute_url(task_download_path, base_url_external or None)
            full_task_download_url_internal = build_internal_url(task_download_path, base_url_internal or None)

            update_task(task_id, {
                "status": "completed",
                "video_id": info.get('id'),
                "title": info.get('title'),
                "filename": filename,
                "duration": info.get('duration'),
                "resolution": info.get('resolution'),
                "ext": ext,
                "task_download_path": task_download_path,
                "task_download_url": full_task_download_url,
                "task_download_url_internal": full_task_download_url_internal,
                "completed_at": datetime.now().isoformat()
            })

            metadata = {
                "task_id": task_id,
                "status": "completed",
                "operation": operation,
                "video_id": info.get('id'),
                "file_size": file_size,
                "task_download_url": full_task_download_url,
                "task_download_url_internal": full_task_download_url_internal,
                "metadata_url": build_absolute_url(f"/download/{task_id}/metadata.json", base_url_external or None),
                "duration": info.get('duration'),
                "resolution": info.get('resolution'),
                "ext": ext,
                "completed_at": datetime.now().isoformat()
            }
            if client_meta is not None:
                metadata['client_meta'] = client_meta
            save_task_metadata(task_id, metadata)
        else:
            error_info = classify_youtube_error("File not downloaded")
            update_task(task_id, {
                "status": "error",
                "error_type": error_info["error_type"],
                "error_message": error_info["error_message"],
                "user_action": error_info["user_action"]
            })
            metadata = {
                "task_id": task_id,
                "status": "error",
                "operation": operation,
                "error_type": error_info["error_type"],
                "error_message": error_info["error_message"],
                "user_action": error_info["user_action"],
                "failed_at": datetime.now().isoformat()
            }
            if client_meta is not None:
                metadata['client_meta'] = client_meta
            save_task_metadata(task_id, metadata)
    except Exception as e:
        error_info = classify_youtube_error(str(e))
        update_task(task_id, {
            "status": "error",
            "error_type": error_info["error_type"],
            "error_message": error_info["error_message"],
            "user_action": error_info["user_action"],
            "raw_error": str(e)[:1000]
        })
        metadata = {
            "task_id": task_id,
            "status": "error",
            "operation": operation,
            "error_type": error_info["error_type"],
            "error_message": error_info["error_message"],
            "user_action": error_info["user_action"],
            "raw_error": str(e)[:1000],
            "failed_at": datetime.now().isoformat()
        }
        if client_meta is not None:
            metadata['client_meta'] = client_meta
        save_task_metadata(task_id, metadata)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
