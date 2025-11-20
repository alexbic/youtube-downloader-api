
import os
import threading
import json
import logging
from flask import Flask, request, jsonify, send_file
import requests
import yt_dlp
from datetime import datetime, timedelta
import uuid
import threading
from functools import wraps
from typing import Dict, Any
import time

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
try:
    _log_level = getattr(logging, LOG_LEVEL, logging.INFO)
except Exception:
    _log_level = logging.INFO
logging.basicConfig(
    level=_log_level,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("yt-dlp-api")

# Управление логированием прогресса скачивания
# Logging configuration (HARDCODED for public version)
PROGRESS_LOG_MODE = 'off'  # os.getenv('PROGRESS_LOG', os.getenv('YTDLP_PROGRESS_LOG', 'off')).strip().lower()
PROGRESS_STEP = 10  # int(os.getenv('PROGRESS_STEP', 10))  # шаг, % для compact режима
LOG_YTDLP_OPTS = False  # os.getenv('LOG_YTDLP_OPTS', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
LOG_YTDLP_WARNINGS = False  # os.getenv('LOG_YTDLP_WARNINGS', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

# Cleanup TTL (hardcoded: 86400 seconds = 24 hours, not configurable in public version)
CLEANUP_TTL_SECONDS = 86400

# Webhook delivery config (HARDCODED for public version)
WEBHOOK_RETRY_ATTEMPTS = 3  # int(os.getenv('WEBHOOK_RETRY_ATTEMPTS', 3))
WEBHOOK_RETRY_INTERVAL_SECONDS = 5.0  # float(os.getenv('WEBHOOK_RETRY_INTERVAL_SECONDS', 5))
WEBHOOK_TIMEOUT_SECONDS = 8.0  # float(os.getenv('WEBHOOK_TIMEOUT_SECONDS', 8))
# Периодические фоновые ретраи вебхуков (переживают рестарты, пока живёт задача)
# Публичная версия: фиксированный интервал, переменные окружения игнорируются
WEBHOOK_BACKGROUND_INTERVAL_SECONDS = 900.0
DEFAULT_WEBHOOK_URL = None  # os.getenv('DEFAULT_WEBHOOK_URL')
_WEBHOOK_HEADERS_ENV = None  # os.getenv('WEBHOOK_HEADERS')

def _parse_webhook_headers(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return {str(k): str(v) for k, v in obj.items()}
    except Exception:
        pass
    headers: dict[str, str] = {}
    # Допускаем форматы: "Key: Value" или "Key=Value", разделители: \n, ;, ,
    parts = []
    for sep in ['\n', ';', ',']:
        if sep in raw:
            parts = [p for p in raw.split(sep) if p.strip()]
            break
    if not parts:
        parts = [raw]
    for p in parts:
        if ':' in p:
            k, v = p.split(':', 1)
        elif '=' in p:
            k, v = p.split('=', 1)
        else:
            # одиночное значение игнорируем
            continue
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            headers[k] = v
    return headers

WEBHOOK_HEADERS = _parse_webhook_headers(_WEBHOOK_HEADERS_ENV)

API_KEY = os.getenv('API_KEY')
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL') or os.getenv('EXTERNAL_BASE_URL')
# Опциональный базовый URL для внутреннего контура (Docker network)
INTERNAL_BASE_URL = os.getenv('INTERNAL_BASE_URL')
# Авторизация требуется только если указан внешний URL и задан ключ
AUTH_REQUIRED = bool(PUBLIC_BASE_URL) and bool(API_KEY)

def log_startup_info():
    public_url = PUBLIC_BASE_URL
    # Сохраняем текущий форматтер
    root_logger = logging.getLogger()
    handlers = root_logger.handlers if root_logger.handlers else [logging.StreamHandler()]
    old_formatters = [h.formatter for h in handlers]
    # Устанавливаем временный форматтер без времени для всего стартового блока
    for h in handlers:
        h.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
    try:
        logger.info("=" * 60)
        logger.info("YouTube Downloader API - PUBLIC VERSION")
        logger.info("=" * 60)
        logger.info("⚠️  PUBLIC VERSION - HARDCODED PARAMETERS")
        logger.info("")
        logger.info("📋 Configuration:")
        storage = 'redis' if 'STORAGE_MODE' in globals() and STORAGE_MODE == 'redis' else 'memory'
        logger.info(f"   Workers: 2 | Redis: {REDIS_HOST}:{REDIS_PORT} (256MB) | Storage: {storage}")
        logger.info(f"   TTL: {CLEANUP_TTL_SECONDS}s (24h) | Meta: {MAX_CLIENT_META_BYTES}B, depth={MAX_CLIENT_META_DEPTH}")
        logger.info(f"   Webhook: attempts={WEBHOOK_RETRY_ATTEMPTS}, interval={WEBHOOK_RETRY_INTERVAL_SECONDS}s, timeout={WEBHOOK_TIMEOUT_SECONDS}s")
        logger.info(f"   Resender: {int(WEBHOOK_BACKGROUND_INTERVAL_SECONDS)}s | Progress: {PROGRESS_LOG_MODE}")
        logger.info("")
        logger.info("🚀 Upgrade to Pro: support@alexbic.net")
        logger.info("   ✓ Configurable parameters ✓ PostgreSQL ✓ /results endpoint")
        logger.info("=" * 60)
        logger.info(f"Log level: {LOG_LEVEL} | yt-dlp: {get_yt_dlp_version()}")
        # Log API access mode
        if public_url and API_KEY:
            logger.info(f"Mode: PUBLIC API | Base URL: {public_url}")
            logger.info("Authentication: ENABLED")
        else:
            logger.info("Mode: INTERNAL (Docker network)")
            if public_url and not API_KEY:
                logger.warning("⚠️  PUBLIC_BASE_URL ignored (API_KEY not set)")
            logger.info("Authentication: DISABLED")
        if 'TASKS_DIR' in globals():
            logger.info(f"Tasks dir: {TASKS_DIR}")
        if 'COOKIES_PATH' in globals() and os.path.exists(COOKIES_PATH):
            logger.info(f"Cookies: available")
        logger.info("=" * 60)
    finally:
        # Возвращаем старый форматтер
        for h, old_fmt in zip(handlers, old_formatters):
            h.setFormatter(old_fmt)

def _log_startup_once():
    """Логируем старт приложения один раз на контейнер (атомарный маркер в /tmp)."""
    marker = "/tmp/yt_dlp_api_start_logged"
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(fd)
        log_startup_info()
    except FileExistsError:
        # Уже логировали в этом контейнере — пропускаем
        pass
    except Exception:
        # На всякий случай логируем, если не удалось создать маркер
        log_startup_info()

def get_yt_dlp_version():
    try:
        return yt_dlp.version.__version__
    except Exception:
        return 'unknown'

app = Flask(__name__)
# Отключаем сортировку ключей в JSON, чтобы сохранить порядок вставки
try:
    app.config['JSON_SORT_KEYS'] = False
    if hasattr(app, 'json') and hasattr(app.json, 'sort_keys'):
        app.json.sort_keys = False  # Flask 2.3+/3.0 JSON provider
except Exception:
    pass

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
def is_youtube_url(url: str) -> bool:
    """
    Validates that the URL is a YouTube URL.
    Accepts:
    - youtube.com (www.youtube.com, m.youtube.com, music.youtube.com)
    - youtu.be short URLs

    Security: Prevents downloading from arbitrary URLs.
    """
    if not url or not isinstance(url, str):
        return False

    url_lower = url.lower().strip()

    # Must start with http:// or https://
    if not url_lower.startswith(('http://', 'https://')):
        return False

    # Extract domain from URL
    try:
        # Remove protocol
        without_protocol = url_lower.split('://', 1)[1] if '://' in url_lower else url_lower
        # Get domain (before first / or ?)
        domain = without_protocol.split('/')[0].split('?')[0]

        # Valid YouTube domains
        valid_domains = (
            'youtube.com',
            'www.youtube.com',
            'm.youtube.com',
            'music.youtube.com',
            'youtu.be',
            'www.youtu.be'
        )

        return domain in valid_domains
    except Exception:
        return False

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
# LOGGING HELPERS FOR YT-DLP
# ============================================

class _QuietYTDLPLogger:
    def debug(self, msg):
        # yt-dlp спамит debug; подавляем полностью
        pass
    def warning(self, msg):
        if LOG_YTDLP_WARNINGS:
            logger.warning(f"yt-dlp: {msg}")
    def error(self, msg):
        logger.error(f"yt-dlp: {msg}")

_last_progress_bucket: dict[str, int] = {}

def _make_progress_hook(task_id: str, step: int = 10):
    def hook(d):
        try:
            if d.get('status') != 'downloading':
                return
            percent = None
            if d.get('_percent_str'):
                # format like ' 81.2%'
                s = d['_percent_str'].strip().rstrip('%')
                percent = float(s)
            else:
                downloaded = d.get('downloaded_bytes') or 0
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                if total:
                    percent = (downloaded / total) * 100.0
            if percent is None:
                return
            bucket = int(percent // max(1, step))
            last = _last_progress_bucket.get(task_id, -1)
            if bucket > last:
                _last_progress_bucket[task_id] = bucket
                logger.info(f"[{task_id[:8]}] progress: {min(100, int(percent))}%")
        except Exception:
            pass
    return hook

def _prepare_ydl_opts(task_id: str | None, video_url: str, quality: str, outtmpl: str, cookies_from_browser: str | None):
    ydl_opts = {
        'format': quality,
        'outtmpl': outtmpl,
        'no_warnings': True,
        # Больше устойчивости к временным сбоям сети/CDN
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 20,
        # Снижаем параллелизм фрагментов для стабильности (особенно в ограниченных средах)
        'concurrent_fragment_downloads': 1,
        # Честный User-Agent помогает против редких 5xx/anti-bot эвристик
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9'
        },
    }
    # Управление уровнем детализации
    if PROGRESS_LOG_MODE == 'full':
        ydl_opts['quiet'] = False
        ydl_opts['noprogress'] = False
    else:
        ydl_opts['quiet'] = True
        ydl_opts['noprogress'] = True
        ydl_opts['logger'] = _QuietYTDLPLogger()
        if PROGRESS_LOG_MODE == 'compact' and task_id:
            ydl_opts['progress_hooks'] = [
                _make_progress_hook(task_id, max(1, PROGRESS_STEP))
            ]

    if cookies_from_browser:
        ydl_opts['cookiesfrombrowser'] = (cookies_from_browser,)
    elif os.path.exists(COOKIES_PATH):
        touch_cookies()  # Обновляем временные метки перед использованием
        ydl_opts['cookiefile'] = COOKIES_PATH

    if LOG_YTDLP_OPTS:
        logger.info(f"yt-dlp opts for {video_url}: {ydl_opts}")
    return ydl_opts

# ============================================
# DIRECTORIES & TASKS
# ============================================
TASKS_DIR = "/app/tasks"
COOKIES_PATH = "/app/cookies.txt"
os.makedirs(TASKS_DIR, exist_ok=True)

def touch_cookies():
    """Обновляет временные метки cookies файла, чтобы он казался свежим для YouTube."""
    if os.path.exists(COOKIES_PATH):
        try:
            os.utime(COOKIES_PATH, None)
        except Exception:
            pass

def get_task_dir(task_id: str) -> str:
    return os.path.join(TASKS_DIR, task_id)

def get_task_output_dir(task_id: str) -> str:
    return get_task_dir(task_id)

def create_task_dirs(task_id: str):
    os.makedirs(get_task_output_dir(task_id), exist_ok=True)

def build_download_endpoint(task_id: str, filename: str) -> str:
    return f"/download/{task_id}/{filename}"

def build_storage_rel_path(task_id: str, filename: str) -> str:
    return f"{task_id}/{filename}"

def save_task_metadata(task_id: str, metadata: Any):
    meta_path = os.path.join(get_task_dir(task_id), "metadata.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def build_structured_metadata(
    task_id: str,
    status: str,
    created_at: str,
    completed_at: str | None,
    expires_at: str | None,
    video_url: str | None,
    video_id: str | None,
    title: str | None,
    duration: int | None,
    resolution: str | None,
    ext: str | None,
    filename: str | None,
    download_endpoint: str | None,
    storage_rel_path: str | None,
    task_download_url: str | None,
    task_download_url_internal: str | None,
    metadata_url: str | None,
    metadata_url_internal: str | None,
    webhook_url: str | None,
    webhook_headers: dict | None,
    client_meta: Any | None,
    ttl_seconds: int | None = None,
    ttl_human: str | None = None
) -> dict:
    """
    Builds metadata object with unified structure matching video-processor-api.

    Итоговая структура:
    {
      "task_id": "...",
      "status": "completed",
      "created_at": "...",
      "completed_at": "..." (optional),
      "expires_at": "..." (optional),
      
      "input": {
        "video_url": "http://...",
        "operations": ["download_video"],
        "operations_count": 1
      },
      
      "output": {
        "output_files": [
          {
            "filename": "video.mp4",
            "download_path": "/download/task-id/video.mp4",
            "download_url": "http://external/download/task-id/video.mp4"  // если PUBLIC_BASE_URL и API_KEY
          }
        ],
        "total_files": 1,
        "metadata_url": "https://external/download/task-id/metadata.json",  // если PUBLIC_BASE_URL и API_KEY
        "metadata_url_internal": "http://localhost:5000/download/task-id/metadata.json"  // всегда
      },
      
      "webhook": {...},
      "client_meta": {...}
    }
    """
    result = {}

    # 1. TASK INFO
    result["task_id"] = task_id
    result["status"] = status
    result["created_at"] = created_at
    if completed_at is not None:
        result["completed_at"] = completed_at
    if expires_at is not None:
        result["expires_at"] = expires_at

    # 2. INPUT (video URL и операции)
    input_data = {
        "video_url": video_url if video_url else None,
        "operations": ["download_video"],
        "operations_count": 1
    }
    # Дополнительная информация о видео (не обязательна)
    if video_id:
        input_data["video_id"] = video_id
    if title:
        input_data["title"] = title
    if duration is not None:
        input_data["duration"] = duration
    if resolution:
        input_data["resolution"] = resolution
    if ext:
        input_data["ext"] = ext
    result["input"] = input_data

    # 3. OUTPUT (файлы и URL)
    output_data = {}

    # output_files array
    output_files = []
    if filename and download_endpoint:
        file_entry = {
            "filename": filename,
            "download_path": download_endpoint
        }
        # Добавляем download_url только если есть публичный URL
        if task_download_url:
            file_entry["download_url"] = task_download_url
        # download_url_internal всегда присутствует
        if task_download_url_internal:
            file_entry["download_url_internal"] = task_download_url_internal
        output_files.append(file_entry)

    output_data["output_files"] = output_files
    output_data["total_files"] = len(output_files)

    # Metadata URLs
    if metadata_url:
        output_data["metadata_url"] = metadata_url
    if metadata_url_internal:
        output_data["metadata_url_internal"] = metadata_url_internal

    # TTL (time-to-live)
    if ttl_seconds is not None:
        output_data["ttl_seconds"] = ttl_seconds
    if ttl_human is not None:
        output_data["ttl_human"] = ttl_human

    result["output"] = output_data

    # 4. WEBHOOK
    if webhook_url:
        result["webhook"] = {
            "url": webhook_url,
            "headers": webhook_headers,
            "status": "pending",
            "attempts": 0,
            "last_attempt": None,
            "last_status": None,
            "last_error": None,
            "next_retry": None,
            "task_id": task_id
        }
    else:
        result["webhook"] = None

    # 5. CLIENT META (always last)
    if client_meta is not None:
        result["client_meta"] = client_meta

    return result


def save_webhook_state(task_id: str, state: dict):
    """Сохраняет состояние webhook в metadata.json в поле 'webhook'"""
    try:
        meta_path = os.path.join(get_task_dir(task_id), "metadata.json")
        # Читаем текущую metadata
        metadata = None
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            except Exception:
                pass

        # Если metadata это массив (как обычно), обновляем первый элемент
        if isinstance(metadata, list) and len(metadata) > 0:
            metadata[0]["webhook"] = state
        elif isinstance(metadata, dict):
            metadata["webhook"] = state
        else:
            # Если metadata еще не создана, создаем минимальную структуру
            metadata = [{"webhook": state}]

        # Сохраняем обновленную metadata
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug(f"[{task_id[:8]}] Failed to save webhook state: {e}")
        pass

def load_webhook_state(task_id: str) -> dict | None:
    """Загружает состояние webhook из metadata.json поля 'webhook'"""
    try:
        meta_path = os.path.join(get_task_dir(task_id), "metadata.json")
        if not os.path.exists(meta_path):
            return None

        with open(meta_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        # Извлекаем webhook из metadata
        if isinstance(metadata, list) and len(metadata) > 0:
            return metadata[0].get("webhook")
        elif isinstance(metadata, dict):
            return metadata.get("webhook")
        return None
    except Exception:
        return None

def _load_metadata_for_payload(task_id: str) -> dict | None:
    try:
        meta_path = os.path.join(get_task_dir(task_id), "metadata.json")
        if not os.path.exists(meta_path):
            return None
        with open(meta_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None

# ============================================
# TASK STORAGE (Redis or Memory)
# ============================================
# Public version: Built-in Redis (localhost), not configurable
STORAGE_MODE = "memory"
tasks_store: Dict[str, Dict[str, Any]] = {}
redis_client = None
REDIS_HOST = 'localhost'  # Built-in Redis
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_INIT_RETRIES = 20  # More retries for built-in Redis startup
REDIS_INIT_DELAY_SECONDS = 0.5

def _ensure_redis() -> bool:
    """Пытается (пере)инициализировать Redis-клиент. Возвращает True при успехе."""
    global redis_client, STORAGE_MODE
    if redis_client is not None and STORAGE_MODE == "redis":
        return True
    try:
        import redis  # type: ignore
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2
        )
        client.ping()
        redis_client = client
        if STORAGE_MODE != "redis":
            logger.info("Redis connected: switching storage to redis")
        STORAGE_MODE = "redis"
        return True
    except Exception as e:
        if STORAGE_MODE != "memory":
            logger.warning(f"Redis unavailable, falling back to memory: {e}")
        STORAGE_MODE = "memory"
        redis_client = None
        return False

# Инициализация при старте с несколькими попытками, чтобы дождаться Redis
for _i in range(max(0, REDIS_INIT_RETRIES)):
    if _ensure_redis():
        break
    try:
        time.sleep(max(0.0, REDIS_INIT_DELAY_SECONDS))
    except Exception:
        pass

def save_task(task_id: str, data: dict):
    # ленивое переподключение к Redis
    _ensure_redis()
    if STORAGE_MODE == "redis" and redis_client is not None:
        try:
            redis_client.setex(f"task:{task_id}", 86400, json.dumps(data, ensure_ascii=False))
            return
        except Exception:
            # если write в Redis не удался — сохраняем в память как резерв
            logger.warning("Redis write failed; saving task in memory store")
    tasks_store[task_id] = data

def get_task(task_id: str):
    # ленивое переподключение к Redis
    _ensure_redis()
    if STORAGE_MODE == "redis" and redis_client is not None:
        try:
            data = redis_client.get(f"task:{task_id}")
            if data:
                return json.loads(data)
        except Exception:
            # fall back to memory below
            logger.warning("Redis read failed; falling back to memory store")
    return tasks_store.get(task_id)

def update_task(task_id: str, updates: dict):
    t = get_task(task_id)
    if t:
        t.update(updates)
        save_task(task_id, t)

# ============================================
# client_meta VALIDATION (HARDCODED for public version)
# ============================================
MAX_CLIENT_META_BYTES = 16 * 1024  # int(os.getenv('MAX_CLIENT_META_BYTES', 16 * 1024))
MAX_CLIENT_META_DEPTH = 5  # int(os.getenv('MAX_CLIENT_META_DEPTH', 5))
MAX_CLIENT_META_KEYS = 200  # int(os.getenv('MAX_CLIENT_META_KEYS', 200))
MAX_CLIENT_META_STRING_LENGTH = 1000  # int(os.getenv('MAX_CLIENT_META_STRING_LENGTH', 1000))
MAX_CLIENT_META_LIST_LENGTH = 200  # int(os.getenv('MAX_CLIENT_META_LIST_LENGTH', 200))
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
    
    if 'http error 5' in error_lower or 'internal server error' in error_lower:
        return {
            "error_type": "network_or_server_error",
            "error_message": "Upstream 5xx error from video server",
            "user_action": "Retry later; usually transient server issue"
        }
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

# Вызов логирования после определения всех лимитов и функций — выводим один раз на контейнер
_log_startup_once()

# ============================================
# BACKGROUND WEBHOOK RESENDER
# ============================================
def _try_send_webhook_once(url: str, payload: dict, task_id: str, webhook_headers: dict | None = None) -> bool:
    headers = {"Content-Type": "application/json"}
    # Добавляем глобальные заголовки из конфига
    try:
        for k, v in (WEBHOOK_HEADERS or {}).items():
            if k.lower() == 'content-type':
                continue
            headers[k] = v
    except Exception:
        pass
    # Добавляем кастомные заголовки для этого webhook (приоритет выше глобальных)
    try:
        for k, v in (webhook_headers or {}).items():
            if k.lower() == 'content-type':
                continue
            headers[k] = v
    except Exception:
        pass
    try:
        # Отправляем корректный JSON-тело через параметр json=
        if logger.isEnabledFor(logging.DEBUG):
            try:
                preview = json.dumps(payload, ensure_ascii=False)[:300]
                logger.debug(f"[{task_id[:8]}] Webhook payload preview: {preview}")
            except Exception:
                pass
        resp = requests.post(url, headers=headers, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS)
        if 200 <= resp.status_code < 300:
            logger.info(f"[{task_id[:8]}] Webhook re-delivered successfully (HTTP {resp.status_code})")
            return True
        preview = (resp.text or "")[:500]
        if preview:
            logger.warning(f"[{task_id[:8]}] Webhook re-delivery failed HTTP {resp.status_code}; body: {preview}")
        else:
            logger.warning(f"[{task_id[:8]}] Webhook re-delivery failed HTTP {resp.status_code} (empty body)")
        return False
    except Exception as e:
        logger.warning(f"[{task_id[:8]}] Webhook re-delivery exception: {e}")
        return False

def _webhook_resender_loop():
    logger.info(f"Webhook resender: started; interval={WEBHOOK_BACKGROUND_INTERVAL_SECONDS}s")
    if DEFAULT_WEBHOOK_URL:
        logger.info(f"Webhook resender: DEFAULT_WEBHOOK_URL is set, will attempt delivery for tasks without webhook URL")
    else:
        logger.info("Webhook resender: DEFAULT_WEBHOOK_URL not set, skipping tasks without webhook URL")
    first_scan = True
    while True:
        try:
            # Перед сканированием — чистим просроченные задачи по TTL (публичная версия: 24 часа)
            try:
                removed = cleanup_old_files()
                if removed > 0:
                    logger.info(f"Resender: cleaned up {removed} expired task(s) older than {CLEANUP_TTL_SECONDS}s")
            except Exception:
                pass
            now = datetime.now()
            task_dirs = []
            try:
                task_dirs = [d for d in os.listdir(TASKS_DIR) if os.path.isdir(os.path.join(TASKS_DIR, d))]
            except Exception as e:
                logger.error(f"Resender: failed to list tasks directory: {e}")
                time.sleep(max(1.0, WEBHOOK_BACKGROUND_INTERVAL_SECONDS))
                continue
            
            if first_scan and task_dirs:
                logger.info(f"Resender: scanning {len(task_dirs)} existing task(s)")
                first_scan = False
            
            for task_id in task_dirs:
                tdir = os.path.join(TASKS_DIR, task_id)
                try:
                    # Пропускаем активные задачи (воркер обрабатывает сейчас)
                    try:
                        t = get_task(task_id)
                    except Exception:
                        t = None
                    if t and str(t.get('status')).lower() in ("queued", "downloading", "processing"):
                        logger.debug(f"Resender: skipping task {task_id} (task in progress: {t.get('status')})")
                        continue

                    # Читаем метаданные, ресендер работает только с терминальными статусами
                    meta = _load_metadata_for_payload(task_id)
                    if not meta:
                        logger.debug(f"Resender: skipping task {task_id} (no metadata)")
                        continue
                    if isinstance(meta, dict):
                        mstatus = str(meta.get('status', '')).lower()
                        if mstatus and mstatus not in ("completed", "error", "failed"):
                            logger.debug(f"Resender: skipping task {task_id} (non-terminal metadata status: {mstatus})")
                            continue

                    # Состояние вебхука
                    st = load_webhook_state(task_id) or {}
                    if st.get('status') == 'delivered':
                        logger.debug(f"Resender: skipping task {task_id} (already delivered)")
                        continue
                    
                    # URL вебхука: приоритет - состояние (на чём остановились), затем из webhook объекта, затем дефолт
                    webhook_obj = meta.get('webhook') if isinstance(meta, dict) else None
                    url = st.get('url')
                    if not url and isinstance(webhook_obj, dict):
                        url = webhook_obj.get('url')
                    if not url:
                        url = meta.get('webhook_url') if isinstance(meta, dict) else None  # Fallback для старых задач
                    if not url:
                        url = DEFAULT_WEBHOOK_URL
                    if not url:
                        logger.debug(f"Resender: skipping task {task_id} (no webhook URL and no DEFAULT_WEBHOOK_URL)")
                        continue

                    # Загружаем кастомные заголовки webhook из metadata
                    webhook_headers = None
                    if isinstance(webhook_obj, dict):
                        webhook_headers = webhook_obj.get('headers')

                    # Если используем дефолтный URL, сохраняем его в состояние для последующих попыток
                    if not st.get('url') and url == DEFAULT_WEBHOOK_URL:
                        st['url'] = DEFAULT_WEBHOOK_URL
                        # Не шумим созданием состояния раньше времени, сохраняем тихо
                        save_webhook_state(task_id, st)
                    
                    next_retry = st.get('next_retry')
                    if next_retry:
                        try:
                            next_retry_dt = datetime.fromisoformat(next_retry)
                            if now < next_retry_dt:
                                logger.debug(f"Resender: skipping task {task_id} (next retry at {next_retry})")
                                continue
                        except Exception:
                            pass
                    
                    logger.info(f"[{task_id[:8]}] Resender: attempting webhook delivery (attempt #{int(st.get('attempts') or 0) + 1})")
                    
                    payload = {
                        'task_id': meta.get('task_id', task_id),
                        'status': meta.get('status', 'completed'),
                        'video_id': meta.get('video_id'),
                        'title': meta.get('title'),
                        'filename': meta.get('filename'),
                        'download_endpoint': meta.get('download_endpoint'),
                        'storage_rel_path': meta.get('storage_rel_path'),
                        'duration': meta.get('duration'),
                        'resolution': meta.get('resolution'),
                        'ext': meta.get('ext'),
                        'created_at': meta.get('created_at'),
                        'completed_at': meta.get('completed_at'),
                    }
                    for k in ('task_download_url', 'metadata_url', 'task_download_url_internal', 'metadata_url_internal', 'operation', 'error_type', 'error_message', 'user_action', 'raw_error', 'failed_at'):
                        if k in meta:
                            payload[k] = meta[k]
                    # Добавляем webhook объект если есть
                    if url or webhook_headers:
                        webhook_obj = {}
                        if url:
                            webhook_obj["url"] = url
                        if webhook_headers:
                            webhook_obj["headers"] = webhook_headers
                        payload["webhook"] = webhook_obj
                    # client_meta добавляем последним
                    if 'client_meta' in meta:
                        payload['client_meta'] = meta['client_meta']
                    ok = _try_send_webhook_once(url, payload, task_id, webhook_headers)
                    if ok:
                        st.update({
                            'status': 'delivered',
                            'last_attempt': datetime.now().isoformat(),
                            'attempts': int(st.get('attempts') or 0) + 1,
                            'last_status': 200,
                            'last_error': None,
                            'next_retry': None,
                        })
                    else:
                        st.update({
                            'status': 'pending',
                            'last_attempt': datetime.now().isoformat(),
                            'attempts': int(st.get('attempts') or 0) + 1,
                            'next_retry': (datetime.now() + timedelta(seconds=WEBHOOK_BACKGROUND_INTERVAL_SECONDS)).isoformat(),
                        })
                    save_webhook_state(task_id, st)
                except Exception as e:
                    logger.error(f"[{task_id[:8]}] Resender: exception processing task: {e}")
        except Exception as e:
            logger.error(f"Resender: main loop exception: {e}")
        time.sleep(max(1.0, WEBHOOK_BACKGROUND_INTERVAL_SECONDS))


# Запускаем resender только в первом gunicorn worker
marker_file = '/tmp/ytdlp_resender_started'
try:
    if not os.path.exists(marker_file):
        with open(marker_file, 'w') as f:
            f.write(str(os.getpid()))
        _resender_thread = threading.Thread(target=_webhook_resender_loop, name='webhook-resender', daemon=True)
        _resender_thread.start()
        logger.debug(f"Resender thread started in process {os.getpid()}")
except Exception as e:
    logger.warning(f"Failed to start resender thread: {e}")

# ============================================
# CLEANUP
# ============================================
def cleanup_old_files() -> int:
    """
    Удаляет задачи старше TTL секунд.

    Использует created_at из metadata.json для проверки возраста задачи,
    чтобы избежать проблем с обновлением mtime директории при рестарте контейнера.

    Orphaned tasks (без metadata.json) удаляются агрессивнее - через 1 час,
    так как нормальные задачи всегда имеют metadata.json с момента создания.
    """
    if CLEANUP_TTL_SECONDS == 0:
        return 0  # cleanup disabled
    import time, shutil
    from datetime import datetime, timezone

    now = time.time()
    ttl = CLEANUP_TTL_SECONDS
    removed = 0

    try:
        for task_id in os.listdir(TASKS_DIR):
            tdir = os.path.join(TASKS_DIR, task_id)
            try:
                if not os.path.isdir(tdir):
                    continue

                # Читаем created_at из metadata.json
                metadata_path = os.path.join(tdir, 'metadata.json')
                task_created_at = None
                is_orphaned = False

                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                            # metadata может быть списком (legacy) или объектом
                            if isinstance(metadata, list) and len(metadata) > 0:
                                created_str = metadata[0].get('created_at')
                            elif isinstance(metadata, dict):
                                created_str = metadata.get('created_at')
                            else:
                                created_str = None

                            if created_str:
                                # Парсим ISO timestamp: "2025-11-17T05:17:07.362338"
                                created_dt = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                                task_created_at = created_dt.timestamp()
                    except Exception as e:
                        logger.debug(f"Cleanup: failed to parse metadata for {task_id}: {e}")
                else:
                    # Задача без metadata.json считается orphaned (зависшая/поврежденная)
                    is_orphaned = True

                # Если не удалось прочитать metadata, используем mtime как fallback
                if task_created_at is None:
                    task_created_at = os.path.getmtime(tdir)
                    if is_orphaned:
                        logger.debug(f"Cleanup: orphaned task {task_id} (no metadata.json), using mtime")

                # Проверяем возраст задачи
                age_seconds = now - task_created_at

                # Orphaned tasks (без metadata.json) удаляем агрессивнее - через 1 час
                # Нормальные задачи имеют metadata.json с момента создания
                effective_ttl = 3600 if is_orphaned else ttl  # 1 hour for orphaned, normal TTL for others

                if age_seconds > effective_ttl:
                    reason = "orphaned" if is_orphaned else "expired"
                    logger.debug(f"Cleanup: removing {reason} task {task_id} (age: {age_seconds:.0f}s, ttl: {effective_ttl}s)")
                    shutil.rmtree(tdir, ignore_errors=True)
                    removed += 1

            except Exception as e:
                # Игнорируем проблемы с отдельными директориями, продолжаем
                logger.debug(f"Cleanup: error processing {task_id}: {e}")
                pass
    except Exception as e:
        logger.debug(f"Cleanup: error listing tasks directory: {e}")
        pass

    return removed

# ============================================
# HEALTH
# ============================================
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "youtube-downloader-api",
        "version": "public",
        "timestamp": datetime.now().isoformat(),
        "auth": "enabled" if AUTH_REQUIRED else "disabled",
        "storage": STORAGE_MODE,
        
        # Hardcoded configuration (Public Version)
        # Upgrade to Pro for configurable parameters via environment variables
        "config": {
            "workers": 2,  # Hardcoded in Dockerfile
            "redis": {
                "host": REDIS_HOST,
                "port": REDIS_PORT,
                "db": REDIS_DB,
                "maxmemory": "256MB",
                "embedded": True
            },
            "limits": {
                "task_ttl_seconds": CLEANUP_TTL_SECONDS,
                "max_client_meta_bytes": MAX_CLIENT_META_BYTES,
                "max_client_meta_depth": MAX_CLIENT_META_DEPTH,
                "max_client_meta_keys": MAX_CLIENT_META_KEYS,
                "max_client_meta_string_length": MAX_CLIENT_META_STRING_LENGTH,
                "max_client_meta_list_length": MAX_CLIENT_META_LIST_LENGTH
            },
            "logging": {
                "progress_mode": PROGRESS_LOG_MODE,
                "progress_step": PROGRESS_STEP,
                "ytdlp_opts": LOG_YTDLP_OPTS,
                "ytdlp_warnings": LOG_YTDLP_WARNINGS
            },
            "webhook": {
                "retry_attempts": WEBHOOK_RETRY_ATTEMPTS,
                "retry_interval_seconds": WEBHOOK_RETRY_INTERVAL_SECONDS,
                "timeout_seconds": WEBHOOK_TIMEOUT_SECONDS,
                "background_interval_seconds": WEBHOOK_BACKGROUND_INTERVAL_SECONDS,
                "default_url": DEFAULT_WEBHOOK_URL,
                "global_headers": WEBHOOK_HEADERS
            }
        },
        
        "pro_features": {
            "available": False,
            "upgrade_info": "Contact for Pro version with configurable parameters",
            "features": [
                "Configurable workers (1-10+)",
                "External Redis support",
                "Variable task TTL (hours to months)",
                "PostgreSQL metadata storage",
                "/task/{id}/results endpoint",
                "Advanced search & filtering",
                "Custom webhook parameters",
                "Adjustable logging modes",
                "Priority support"
            ]
        }
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
        touch_cookies()  # Обновляем временные метки cookies
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
        # Webhook - только новый формат (объект с url и headers)
        webhook = data.get('webhook')
        webhook_url = None
        webhook_headers = None

        if webhook is not None:
            # Принимаем только объект формата: {"url": "...", "headers": {...}}
            if not isinstance(webhook, dict):
                return jsonify({"error": "Invalid webhook (must be an object with 'url' and optional 'headers')"}), 400

            webhook_url = webhook.get('url')
            webhook_headers = webhook.get('headers')

            # Валидация webhook.url
            if webhook_url is not None:
                if not isinstance(webhook_url, str) or not webhook_url.lower().startswith(("http://", "https://")):
                    return jsonify({"error": "Invalid webhook.url (must start with http(s)://)"}), 400
                if len(webhook_url) > 2048:
                    return jsonify({"error": "Invalid webhook.url (too long)"}), 400

            # Валидация webhook.headers
            if webhook_headers is not None:
                if not isinstance(webhook_headers, dict):
                    return jsonify({"error": "Invalid webhook.headers (must be an object)"}), 400
                for key, value in webhook_headers.items():
                    if not isinstance(key, str) or not isinstance(value, str):
                        return jsonify({"error": "Invalid webhook.headers (keys and values must be strings)"}), 400
                    if len(key) > 256 or len(value) > 2048:
                        return jsonify({"error": "Invalid webhook.headers (header name or value too long)"}), 400

        # Fallback на DEFAULT_WEBHOOK_URL если webhook не указан
        if webhook_url is None and DEFAULT_WEBHOOK_URL:
            webhook_url = DEFAULT_WEBHOOK_URL
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

        # Security: Validate that URL is from YouTube only
        if not is_youtube_url(video_url):
            return jsonify({"error": "Invalid URL: Only YouTube URLs are allowed (youtube.com, youtu.be)"}), 400

        # Async mode: start background task and return immediately
        if bool(data.get('async', False)):
            cleanup_old_files()
            task_id = str(uuid.uuid4())
            logger.info(f"Task created (async): {task_id} | {video_url}")
            logger.debug(f"[{task_id[:8]}] quality={quality}, webhook={'yes' if webhook_url else 'no'}")
            create_task_dirs(task_id)
            task_data = {
                "task_id": task_id,
                "status": "queued",
                "created_at": datetime.now().isoformat(),
                "video_url": video_url,
                "quality": quality,
                "cookies_from_browser": cookies_from_browser,
                "client_meta": client_meta,
                "webhook_url": webhook_url,
                "webhook_headers": webhook_headers
            }
            save_task(task_id, task_data)
            link_base_external = (PUBLIC_BASE_URL if (PUBLIC_BASE_URL and API_KEY) else None)
            link_base_internal = (INTERNAL_BASE_URL or (request.host_url.rstrip('/') if request and hasattr(request, 'host_url') else None))
            thread = threading.Thread(target=_background_download, args=(task_id, video_url, quality, client_meta, "download_video_async", link_base_external or "", link_base_internal or "", cookies_from_browser, webhook_url, webhook_headers))
            thread.daemon = True
            thread.start()
            # Только internal, если нет внешнего контура; иначе обе
            if PUBLIC_BASE_URL and API_KEY:
                resp_async = {
                    "task_id": task_id,
                    "status": "processing",
                    "check_status_url": build_absolute_url(f"/task_status/{task_id}", link_base_external),
                    "metadata_url": build_absolute_url(f"/download/{task_id}/metadata.json", link_base_external),
                    "check_status_url_internal": build_internal_url(f"/task_status/{task_id}", link_base_internal),
                    "metadata_url_internal": build_internal_url(f"/download/{task_id}/metadata.json", link_base_internal)
                }
                # Добавляем webhook объект, если был предоставлен
                if webhook:
                    resp_async["webhook"] = webhook
                # client_meta всегда в конце
                if client_meta is not None:
                    resp_async["client_meta"] = client_meta
            else:
                resp_async = {
                    "task_id": task_id,
                    "status": "processing",
                    "check_status_url_internal": build_internal_url(f"/task_status/{task_id}", link_base_internal),
                    "metadata_url_internal": build_internal_url(f"/download/{task_id}/metadata.json", link_base_internal)
                }
                # Добавляем webhook объект, если был предоставлен
                if webhook:
                    resp_async["webhook"] = webhook
                # client_meta всегда в конце
                if client_meta is not None:
                    resp_async["client_meta"] = client_meta
            return jsonify(resp_async), 202

        # Sync mode: download immediately and return result
        task_id = str(uuid.uuid4())
        logger.info(f"Task created (sync): {task_id} | {video_url}")
        logger.debug(f"[{task_id[:8]}] quality={quality}")
        created_at_iso = datetime.now().isoformat()
        create_task_dirs(task_id)
        safe_filename = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        outtmpl = os.path.join(get_task_output_dir(task_id), f'{safe_filename}.%(ext)s')
        ydl_opts = _prepare_ydl_opts(task_id, video_url, quality, outtmpl, cookies_from_browser)
        if LOG_YTDLP_OPTS:
            logger.debug(f"[{task_id[:8]}] yt-dlp opts: {ydl_opts}")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                ext = info.get('ext', 'mp4')
                filename = f"{safe_filename}.{ext}"
                file_path = os.path.join(get_task_output_dir(task_id), filename)
            if os.path.exists(file_path):
                os.chmod(file_path, 0o644)
                file_size = os.path.getsize(file_path)
                logger.info(f"[{task_id[:8]}] Completed (sync): {info.get('title', 'unknown')[:50]} [{file_size//1024//1024}MB]")
                logger.debug(f"[{task_id[:8]}] video_id={info.get('id')}, ext={ext}, resolution={info.get('resolution')}")
                download_endpoint = build_download_endpoint(task_id, filename)
                task_download_url = build_absolute_url(download_endpoint)
                task_download_url_internal = build_internal_url(download_endpoint)
                completed_at_iso = datetime.now().isoformat()
                storage_rel_path = build_storage_rel_path(task_id, filename)
                # Вычисляем время истечения TTL
                created_dt = datetime.fromisoformat(created_at_iso)
                if CLEANUP_TTL_SECONDS > 0:
                    expires_dt = created_dt + timedelta(seconds=CLEANUP_TTL_SECONDS)
                    expires_at_iso = expires_dt.isoformat()
                else:
                    expires_at_iso = None  # Файлы хранятся бессрочно

                # Метафайл как массив из одного объекта, по требуемому формату
                ttl_seconds = CLEANUP_TTL_SECONDS if CLEANUP_TTL_SECONDS > 0 else None
                ttl_human = f"{CLEANUP_TTL_SECONDS // 3600}h" if CLEANUP_TTL_SECONDS >= 3600 else f"{CLEANUP_TTL_SECONDS // 60}m" if CLEANUP_TTL_SECONDS >= 60 else f"{CLEANUP_TTL_SECONDS}s"
                meta_item = build_structured_metadata(
                    task_id=task_id,
                    status="completed",
                    created_at=created_at_iso,
                    completed_at=completed_at_iso,
                    expires_at=expires_at_iso,
                    video_url=video_url,
                    video_id=info.get('id'),
                    title=info.get('title'),
                    duration=info.get('duration'),
                    resolution=info.get('resolution'),
                    ext=ext,
                    filename=filename,
                    download_endpoint=download_endpoint,
                    storage_rel_path=storage_rel_path,
                    task_download_url=task_download_url if (PUBLIC_BASE_URL and API_KEY) else None,
                    task_download_url_internal=task_download_url_internal,
                    metadata_url=build_absolute_url(f"/download/{task_id}/metadata.json") if (PUBLIC_BASE_URL and API_KEY) else None,
                    metadata_url_internal=build_internal_url(f"/download/{task_id}/metadata.json"),
                    webhook_url=webhook_url,
                    webhook_headers=webhook_headers,
                    client_meta=client_meta,
                    ttl_seconds=ttl_seconds,
                    ttl_human=ttl_human
                )
                save_task_metadata(task_id, [meta_item])
                resp_sync = {
                    "task_id": task_id,
                    "status": "completed",
                    "video_id": info.get('id'),
                    "title": info.get('title'),
                    "filename": filename,
                    "file_size": file_size,
                    "download_endpoint": download_endpoint,
                    "storage_rel_path": storage_rel_path,
                    "duration": info.get('duration'),
                    "resolution": info.get('resolution'),
                    "ext": ext,
                    "created_at": created_at_iso,
                    "processed_at": completed_at_iso
                }
                if PUBLIC_BASE_URL and API_KEY:
                    resp_sync["task_download_url"] = task_download_url
                    resp_sync["metadata_url"] = build_absolute_url(f"/download/{task_id}/metadata.json")
                    resp_sync["task_download_url_internal"] = task_download_url_internal
                    resp_sync["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json")
                else:
                    resp_sync["task_download_url_internal"] = task_download_url_internal
                    resp_sync["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json")
                resp_sync["client_meta"] = client_meta
                return jsonify(resp_sync)
            return jsonify({"error": "No file downloaded"}), 500
        except Exception as e:
            error_info = classify_youtube_error(str(e))
            logger.error(f"[{task_id[:8]}] SYNC FAILED: type={error_info['error_type']}, msg={error_info['error_message']}")
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
            if webhook_url:
                metadata['webhook_url'] = webhook_url
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
        touch_cookies()  # Обновляем временные метки cookies
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
        # Fallback 1: если есть metadata.json — читаем из него
        meta_path = os.path.join(get_task_dir(task_id), "metadata.json")
        try:
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                # async успешный кейс у нас — массив из одного объекта
                if isinstance(meta, list) and meta:
                    mi = meta[0]
                    endpoint = mi.get('download_endpoint')
                    resp = {
                        "task_id": task_id,
                        "status": mi.get('status', 'completed'),
                        "video_id": mi.get('video_id'),
                        "title": mi.get('title'),
                        "filename": mi.get('filename'),
                        "download_endpoint": endpoint,
                        "storage_rel_path": mi.get('storage_rel_path'),
                        "duration": mi.get('duration'),
                        "resolution": mi.get('resolution'),
                        "ext": mi.get('ext'),
                        "created_at": mi.get('created_at'),
                        "completed_at": mi.get('completed_at')
                    }
                    if endpoint:
                        if PUBLIC_BASE_URL and API_KEY:
                            resp["task_download_url"] = _join_url(PUBLIC_BASE_URL, endpoint)
                            resp["metadata_url"] = _join_url(PUBLIC_BASE_URL, f"/download/{task_id}/metadata.json")
                            resp["task_download_url_internal"] = build_internal_url(endpoint)
                            resp["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json")
                        else:
                            resp["task_download_url_internal"] = build_internal_url(endpoint)
                            resp["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json")
                    # Добавляем webhook из metadata.json, если есть
                    if mi.get('webhook') is not None:
                        resp['webhook'] = mi.get('webhook')
                    # client_meta всегда в конце
                    if mi.get('client_meta') is not None:
                        resp['client_meta'] = mi['client_meta']
                    # Включаем состояние вебхука, если есть
                    try:
                        st = load_webhook_state(task_id)
                        if st:
                            resp['webhook_status'] = st.get('status')
                            resp['webhook_attempts'] = int(st.get('attempts') or 0)
                            resp['webhook_next_retry'] = st.get('next_retry')
                    except Exception:
                        pass
                    return jsonify(resp)
                # error/other — объект
                if isinstance(meta, dict):
                    resp = {
                        "task_id": task_id,
                        "status": meta.get('status', 'error'),
                        "error_type": meta.get('error_type', 'unknown'),
                        "error_message": meta.get('error_message', meta.get('error', 'Unknown error')),
                        "user_action": meta.get('user_action', 'Review error manually'),
                        "failed_at": meta.get('failed_at')
                    }
                    if meta.get('raw_error'):
                        resp['raw_error'] = meta['raw_error']
                    # Добавляем webhook из metadata.json, если есть
                    if meta.get('webhook') is not None:
                        resp['webhook'] = meta.get('webhook')
                    # client_meta всегда в конце
                    if meta.get('client_meta') is not None:
                        resp['client_meta'] = meta['client_meta']
                    # Включаем состояние вебхука, если есть
                    try:
                        st = load_webhook_state(task_id)
                        if st:
                            resp['webhook_status'] = st.get('status')
                            resp['webhook_attempts'] = int(st.get('attempts') or 0)
                            resp['webhook_next_retry'] = st.get('next_retry')
                    except Exception:
                        pass
                    return jsonify(resp)
        except Exception:
            # игнорируем и продолжаем к следующему fallback
            pass
        # Fallback 2: Если папка задачи существует — считаем, что она в процессе
        tdir = get_task_dir(task_id)
        if os.path.isdir(tdir):
            try:
                created_at = datetime.fromtimestamp(os.path.getctime(tdir)).isoformat()
            except Exception:
                created_at = None
            return jsonify({
                "task_id": task_id,
                "status": "processing",
                "created_at": created_at
            })
        return jsonify({"error": "Task not found"}), 404
    resp = {"task_id": task_id, "status": task.get('status'), "created_at": task.get('created_at')}
    if task.get('status') == 'completed':
        endpoint = build_download_endpoint(task_id, task.get('filename')) if task.get('filename') else None
        resp_update = {
            "video_id": task.get('video_id'),
            "title": task.get('title'),
            "filename": task.get('filename'),
            "download_endpoint": endpoint,
            "storage_rel_path": build_storage_rel_path(task_id, task.get('filename')) if task.get('filename') else None,
            "duration": task.get('duration'),
            "resolution": task.get('resolution'),
            "ext": task.get('ext'),
            "completed_at": task.get('completed_at')
        }
        if endpoint:
            if PUBLIC_BASE_URL and API_KEY:
                resp_update["task_download_url"] = _join_url(PUBLIC_BASE_URL, endpoint)
                resp_update["metadata_url"] = _join_url(PUBLIC_BASE_URL, f"/download/{task_id}/metadata.json")
                resp_update["task_download_url_internal"] = build_internal_url(endpoint)
                resp_update["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json")
            else:
                resp_update["task_download_url_internal"] = build_internal_url(endpoint)
                resp_update["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json")
        resp.update(resp_update)
    if task.get('status') == 'error':
        resp['error_type'] = task.get('error_type', 'unknown')
        resp['error_message'] = task.get('error_message', task.get('error', 'Unknown error'))
        resp['user_action'] = task.get('user_action', 'Review error manually')
        if task.get('raw_error'):
            resp['raw_error'] = task.get('raw_error')
    # Восстанавливаем webhook объект из task data (webhook_url + webhook_headers)
    if task.get('webhook_url') is not None:
        webhook_obj = {"url": task['webhook_url']}
        if task.get('webhook_headers'):
            webhook_obj["headers"] = task['webhook_headers']
        resp['webhook'] = webhook_obj
    # client_meta всегда строго последним
    if task.get('client_meta') is not None:
        resp['client_meta'] = task['client_meta']
    # Включаем состояние вебхука, если есть
    try:
        st = load_webhook_state(task_id)
        if st:
            resp['webhook_status'] = st.get('status')
            resp['webhook_attempts'] = int(st.get('attempts') or 0)
            resp['webhook_next_retry'] = st.get('next_retry')
    except Exception:
        pass
    return jsonify(resp)

def _background_download(
    task_id: str,
    video_url: str,
    quality: str,
    client_meta: dict,
    operation: str = "download_video_async",
    base_url_external: str = "",
    base_url_internal: str = "",
    cookies_from_browser: str = None,
    webhook_url: str | None = None,
    webhook_headers: dict | None = None
):
    def _post_webhook(payload: dict):
        if not webhook_url:
            logger.debug(f"[{task_id[:8]}] Webhook skipped: no webhook_url provided")
            return
        logger.info(f"[{task_id[:8]}] Sending webhook")
        logger.debug(f"[{task_id[:8]}] webhook_url={webhook_url}")
        headers = {"Content-Type": "application/json"}
        # Добавляем глобальные пользовательские заголовки из конфига
        try:
            for k, v in (WEBHOOK_HEADERS or {}).items():
                if k.lower() == 'content-type':
                    continue
                headers[k] = v
        except Exception:
            pass
        # Добавляем заголовки для конкретного webhook (приоритет выше глобальных)
        try:
            for k, v in (webhook_headers or {}).items():
                if k.lower() == 'content-type':
                    continue  # Не позволяем переопределять Content-Type
                headers[k] = v
        except Exception:
            pass
        # Лёгкая диагностика тела запроса под DEBUG
        if logger.isEnabledFor(logging.DEBUG):
            try:
                body_preview = json.dumps(payload, ensure_ascii=False)
                logger.debug(f"[{task_id[:8]}] webhook payload size={len(body_preview)}")
                logger.debug(f"[{task_id[:8]}] webhook payload preview={body_preview[:400]}")
            except Exception:
                pass
        # Инициализируем/обновляем файл состояния вебхука
        st = load_webhook_state(task_id) or {}
        st.update({
            "task_id": task_id,
            "url": webhook_url,
            "status": st.get("status") or "pending",
            "attempts": int(st.get("attempts") or 0),
        })
        save_webhook_state(task_id, st)
        attempts = max(1, WEBHOOK_RETRY_ATTEMPTS)
        for i in range(1, attempts + 1):
            try:
                if i > 1:
                    logger.debug(f"[{task_id[:8]}] Webhook retry {i}/{attempts}")
                # Используем json= для корректного формирования тела и заголовков
                resp = requests.post(webhook_url, headers=headers, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS)
                if 200 <= resp.status_code < 300:
                    logger.info(f"[{task_id[:8]}] Webhook delivered")
                    logger.debug(f"[{task_id[:8]}] HTTP {resp.status_code}")
                    st.update({
                        "status": "delivered",
                        "attempts": int(st.get("attempts") or 0) + 1,
                        "last_attempt": datetime.now().isoformat(),
                        "last_status": int(resp.status_code),
                        "last_error": None,
                        "next_retry": None
                    })
                    save_webhook_state(task_id, st)
                    return
                # Логируем тело ответа (усечённое) для упрощения диагностики в n8n
                resp_preview = (resp.text or "")[:500]
                if resp_preview:
                    logger.warning(f"[{task_id[:8]}] Webhook failed with HTTP {resp.status_code}; body: {resp_preview}")
                else:
                    logger.warning(f"[{task_id[:8]}] Webhook failed with HTTP {resp.status_code} (empty body)")
                # Неположительные коды считаем ошибкой доставки
            except Exception as e:
                logger.warning(f"[{task_id[:8]}] Webhook attempt {i} failed: {e}")
                # сетевые/таймаут ошибки — пробуем снова
                pass
            # Обновляем счётчик попыток и планируем следующий фоновый ретрай
            st.update({
                "status": "pending",
                "attempts": int(st.get("attempts") or 0) + 1,
                "last_attempt": datetime.now().isoformat(),
                "last_status": None,
                "last_error": None,
                "next_retry": (datetime.now() + timedelta(seconds=WEBHOOK_BACKGROUND_INTERVAL_SECONDS)).isoformat()
            })
            save_webhook_state(task_id, st)
            if i < attempts:
                time.sleep(max(0.0, WEBHOOK_RETRY_INTERVAL_SECONDS))
        # Все попытки исчерпаны — продолжаем без падения
        logger.error(f"[{task_id[:8]}] Webhook delivery failed after {attempts} attempts; will retry in background")

    try:
        logger.info(f"[{task_id[:8]}] Download started")
        logger.debug(f"[{task_id[:8]}] url={video_url}, quality={quality}")
        update_task(task_id, {"status": "downloading"})
        safe_filename = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        outtmpl = os.path.join(get_task_output_dir(task_id), f"{safe_filename}.%(ext)s")
        ydl_opts = _prepare_ydl_opts(task_id, video_url, quality, outtmpl, cookies_from_browser)
        if LOG_YTDLP_OPTS:
            logger.debug(f"[{task_id[:8]}] yt-dlp opts: {ydl_opts}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            ext = info.get('ext', 'mp4')

        filename = f"{safe_filename}.{ext}"
        file_path = os.path.join(get_task_output_dir(task_id), filename)
        if os.path.exists(file_path):
            os.chmod(file_path, 0o644)
            file_size = os.path.getsize(file_path)
            logger.info(f"[{task_id[:8]}] Download completed: {info.get('title', 'unknown')[:50]} [{file_size//1024//1024}MB]")
            logger.debug(f"[{task_id[:8]}] video_id={info.get('id')}, ext={ext}, resolution={info.get('resolution')}")
            download_endpoint = build_download_endpoint(task_id, filename)
            full_task_download_url = build_absolute_url(download_endpoint, base_url_external or None)
            full_task_download_url_internal = build_internal_url(download_endpoint, base_url_internal or None)
            completed_at_iso = datetime.now().isoformat()
            # created_at из сохранённой задачи, если есть
            created_at_iso = None
            try:
                t = get_task(task_id)
                if t and t.get('created_at'):
                    created_at_iso = t.get('created_at')
            except Exception:
                created_at_iso = None
            storage_rel_path = build_storage_rel_path(task_id, filename)

            # Вычисляем время истечения TTL
            if created_at_iso:
                created_dt = datetime.fromisoformat(created_at_iso)
                if CLEANUP_TTL_SECONDS > 0:
                    expires_dt = created_dt + timedelta(seconds=CLEANUP_TTL_SECONDS)
                    expires_at_iso = expires_dt.isoformat()
                else:
                    expires_at_iso = None  # Файлы хранятся бессрочно
            else:
                expires_at_iso = None

            updates = {
                "status": "completed",
                "video_id": info.get('id'),
                "title": info.get('title'),
                "filename": filename,
                "duration": info.get('duration'),
                "resolution": info.get('resolution'),
                "ext": ext,
                "completed_at": completed_at_iso
            }
            if base_url_external:
                updates["task_download_url"] = full_task_download_url
                updates["task_download_url_internal"] = full_task_download_url_internal
            else:
                updates["task_download_url_internal"] = full_task_download_url_internal
            update_task(task_id, updates)
            # Метафайл как массив из одного объекта, по требуемому формату
            ttl_seconds = CLEANUP_TTL_SECONDS if CLEANUP_TTL_SECONDS > 0 else None
            ttl_human = f"{CLEANUP_TTL_SECONDS // 3600}h" if CLEANUP_TTL_SECONDS >= 3600 else f"{CLEANUP_TTL_SECONDS // 60}m" if CLEANUP_TTL_SECONDS >= 60 else f"{CLEANUP_TTL_SECONDS}s"
            meta_item = build_structured_metadata(
                task_id=task_id,
                status="completed",
                created_at=created_at_iso,
                completed_at=completed_at_iso,
                expires_at=expires_at_iso,
                video_url=video_url,
                video_id=info.get('id'),
                title=info.get('title'),
                duration=info.get('duration'),
                resolution=info.get('resolution'),
                ext=ext,
                filename=filename,
                download_endpoint=download_endpoint,
                storage_rel_path=storage_rel_path,
                task_download_url=full_task_download_url if base_url_external else None,
                task_download_url_internal=full_task_download_url_internal,
                metadata_url=build_absolute_url(f"/download/{task_id}/metadata.json", base_url_external) if base_url_external else None,
                metadata_url_internal=build_internal_url(f"/download/{task_id}/metadata.json", base_url_internal or None),
                webhook_url=webhook_url,
                webhook_headers=webhook_headers,
                client_meta=client_meta,
                ttl_seconds=ttl_seconds,
                ttl_human=ttl_human
            )
            save_task_metadata(task_id, [meta_item])

            # webhook payload теперь строго build_structured_metadata (единый формат)
            webhook_payload = build_structured_metadata(
                task_id=task_id,
                status="completed",
                created_at=created_at_iso,
                completed_at=completed_at_iso,
                expires_at=expires_at_iso,
                video_url=video_url,
                video_id=info.get('id'),
                title=info.get('title'),
                duration=info.get('duration'),
                resolution=info.get('resolution'),
                ext=ext,
                filename=filename,
                download_endpoint=download_endpoint,
                storage_rel_path=storage_rel_path,
                task_download_url=full_task_download_url if base_url_external else None,
                task_download_url_internal=full_task_download_url_internal,
                metadata_url=build_absolute_url(f"/download/{task_id}/metadata.json", base_url_external) if base_url_external else None,
                metadata_url_internal=build_internal_url(f"/download/{task_id}/metadata.json", base_url_internal or None),
                webhook_url=webhook_url,
                webhook_headers=webhook_headers,
                client_meta=client_meta,
                ttl_seconds=ttl_seconds,
                ttl_human=ttl_human
            )
            _post_webhook(webhook_payload)
        else:
            logger.error(f"[{task_id[:8]}] DOWNLOAD FAILED: File not downloaded")
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
            if webhook_url:
                metadata['webhook_url'] = webhook_url
            save_task_metadata(task_id, metadata)
            # webhook об ошибке
            payload = {
                "task_id": task_id,
                "status": "error",
                "operation": operation,
                "error_type": error_info["error_type"],
                "error_message": error_info["error_message"],
                "user_action": error_info["user_action"],
                "failed_at": datetime.now().isoformat()
            }
            # Добавляем webhook объект если есть
            if webhook_url or webhook_headers:
                webhook_obj = {}
                if webhook_url:
                    webhook_obj["url"] = webhook_url
                if webhook_headers:
                    webhook_obj["headers"] = webhook_headers
                payload["webhook"] = webhook_obj
            if client_meta is not None:
                payload['client_meta'] = client_meta
            _post_webhook(payload)
    except Exception as e:
        error_info = classify_youtube_error(str(e))
        logger.error(f"[{task_id[:8]}] DOWNLOAD EXCEPTION: type={error_info['error_type']}, msg={error_info['error_message'][:100]}")
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
        if webhook_url:
            metadata['webhook_url'] = webhook_url
        save_task_metadata(task_id, metadata)
        # webhook об ошибке
        payload = {
            "task_id": task_id,
            "status": "error",
            "operation": operation,
            "error_type": error_info["error_type"],
            "error_message": error_info["error_message"],
            "user_action": error_info["user_action"],
            "raw_error": str(e)[:1000],
            "failed_at": datetime.now().isoformat()
        }
        # Добавляем webhook объект если есть
        if webhook_url or webhook_headers:
            webhook_obj = {}
            if webhook_url:
                webhook_obj["url"] = webhook_url
            if webhook_headers:
                webhook_obj["headers"] = webhook_headers
            payload["webhook"] = webhook_obj
        if client_meta is not None:
            payload['client_meta'] = client_meta
        _post_webhook(payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
