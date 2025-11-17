
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
PROGRESS_LOG_MODE = os.getenv('PROGRESS_LOG', os.getenv('YTDLP_PROGRESS_LOG', 'off')).strip().lower()
if PROGRESS_LOG_MODE not in ('off', 'compact', 'full'):
    PROGRESS_LOG_MODE = 'off'
PROGRESS_STEP = int(os.getenv('PROGRESS_STEP', 10))  # шаг, % для compact режима
LOG_YTDLP_OPTS = os.getenv('LOG_YTDLP_OPTS', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
LOG_YTDLP_WARNINGS = os.getenv('LOG_YTDLP_WARNINGS', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

# Cleanup TTL (hardcoded: 86400 seconds = 24 hours, not configurable in public version)
CLEANUP_TTL_SECONDS = 86400

# Webhook delivery config
WEBHOOK_RETRY_ATTEMPTS = int(os.getenv('WEBHOOK_RETRY_ATTEMPTS', 3))
WEBHOOK_RETRY_INTERVAL_SECONDS = float(os.getenv('WEBHOOK_RETRY_INTERVAL_SECONDS', 5))
WEBHOOK_TIMEOUT_SECONDS = float(os.getenv('WEBHOOK_TIMEOUT_SECONDS', 8))
# Периодические фоновые ретраи вебхуков (переживают рестарты, пока живёт задача)
WEBHOOK_BACKGROUND_INTERVAL_SECONDS = float(os.getenv('WEBHOOK_BACKGROUND_INTERVAL_SECONDS', 300))
DEFAULT_WEBHOOK_URL = os.getenv('DEFAULT_WEBHOOK_URL')
_WEBHOOK_HEADERS_ENV = os.getenv('WEBHOOK_HEADERS')

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
    logger.info("=" * 60)
    logger.info("YouTube Downloader API - PUBLIC VERSION")
    logger.info("=" * 60)
    logger.warning("⚠️  PUBLIC VERSION - LIMITED FEATURES")
    logger.warning("   • Workers: 2 (fixed)")
    logger.warning("   • Task TTL: 24 hours (fixed)")
    logger.warning("   • Redis: Built-in, 256MB limit")
    logger.warning("   • No processing results cache")
    logger.warning("")
    logger.warning("🚀 Want more? Upgrade to PRO VERSION:")
    logger.warning("   • Configurable TTL (up to months)")
    logger.warning("   • PostgreSQL metadata storage")
    logger.warning("   • /task/{id}/results endpoint")
    logger.warning("   • Advanced search & filtering")
    logger.warning("   • Priority support")
    logger.warning("")
    logger.warning("📧 Contact: support@alexbic.net")
    logger.warning("🌐 Info: https://github.com/alexbic/youtube-downloader-api-pro")
    logger.info("=" * 60)
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
    if 'TASKS_DIR' in globals():
        logger.info(f"Tasks dir: {TASKS_DIR} (files stored here)")
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
    logger.info(f"Logging: level={LOG_LEVEL}, progress_mode={PROGRESS_LOG_MODE}, step={PROGRESS_STEP}%")
    if 'CLEANUP_TTL_SECONDS' in globals():
        if CLEANUP_TTL_SECONDS == 0:
            logger.info("Cleanup: DISABLED (files persist indefinitely)")
        else:
            logger.info(f"Cleanup: TTL={CLEANUP_TTL_SECONDS}s ({CLEANUP_TTL_SECONDS//60}min)")
    logger.info(f"Webhook: attempts={WEBHOOK_RETRY_ATTEMPTS}, interval={WEBHOOK_RETRY_INTERVAL_SECONDS}s, timeout={WEBHOOK_TIMEOUT_SECONDS}s")
    if DEFAULT_WEBHOOK_URL:
        logger.info(f"Webhook: default_url set -> {DEFAULT_WEBHOOK_URL}")
    if WEBHOOK_HEADERS:
        try:
            masked = {k: ('***' if k.lower() in ('authorization', 'x-api-key', 'x-auth-token') else v) for k, v in WEBHOOK_HEADERS.items()}
            logger.info(f"Webhook: extra headers -> {masked}")
        except Exception:
            logger.info("Webhook: extra headers configured")
    # Отобразим предполагаемое число воркеров (если задали WORKERS)
    try:
        workers_env = os.getenv('WORKERS')
        if workers_env:
            logger.info(f"Workers (gunicorn): {workers_env}")
    except Exception:
        pass
    logger.info("=" * 60)

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

def _webhook_state_path(task_id: str) -> str:
    return os.path.join(get_task_dir(task_id), "webhook.json")

def save_webhook_state(task_id: str, state: dict):
    try:
        os.makedirs(get_task_dir(task_id), exist_ok=True)
        with open(_webhook_state_path(task_id), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_webhook_state(task_id: str) -> dict | None:
    try:
        with open(_webhook_state_path(task_id), 'r', encoding='utf-8') as f:
            return json.load(f)
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
def _try_send_webhook_once(url: str, payload: dict, task_id: str) -> bool:
    headers = {"Content-Type": "application/json"}
    try:
        for k, v in (WEBHOOK_HEADERS or {}).items():
            if k.lower() == 'content-type':
                continue
            headers[k] = v
    except Exception:
        pass
    try:
        resp = requests.post(url, headers=headers, data=json.dumps(payload, ensure_ascii=False), timeout=WEBHOOK_TIMEOUT_SECONDS)
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
                    
                    # URL вебхука: приоритет - состояние (на чём остановились), затем метаданные, затем дефолт
                    url = st.get('url') or (meta.get('webhook_url') if isinstance(meta, dict) else None) or DEFAULT_WEBHOOK_URL
                    if not url:
                        logger.debug(f"Resender: skipping task {task_id} (no webhook URL and no DEFAULT_WEBHOOK_URL)")
                        continue
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
                    for k in ('task_download_url', 'metadata_url', 'task_download_url_internal', 'metadata_url_internal', 'client_meta', 'operation', 'error_type', 'error_message', 'user_action', 'raw_error', 'failed_at'):
                        if k in meta:
                            payload[k] = meta[k]
                    ok = _try_send_webhook_once(url, payload, task_id)
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
def cleanup_old_files():
    if CLEANUP_TTL_SECONDS == 0:
        return  # cleanup disabled
    import time, shutil
    now = time.time()
    ttl = CLEANUP_TTL_SECONDS
    try:
        for task_id in os.listdir(TASKS_DIR):
            tdir = os.path.join(TASKS_DIR, task_id)
            if os.path.isdir(tdir) and now - os.path.getmtime(tdir) > ttl:
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
        # webhook для async режима
        webhook_url = data.get('webhook_url') or data.get('webhook') or data.get('callback_url') or DEFAULT_WEBHOOK_URL
        if webhook_url is not None:
            try:
                if not isinstance(webhook_url, str) or not webhook_url.lower().startswith(("http://", "https://")):
                    return jsonify({"error": "Invalid webhook_url (must start with http(s)://)"}), 400
                if len(webhook_url) > 2048:
                    return jsonify({"error": "Invalid webhook_url (too long)"}), 400
            except Exception:
                return jsonify({"error": "Invalid webhook_url"}), 400
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
            logger.info(f"[{task_id[:8]}] Task created (async): {video_url}")
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
                "webhook_url": webhook_url
            }
            save_task(task_id, task_data)
            link_base_external = (PUBLIC_BASE_URL if (PUBLIC_BASE_URL and API_KEY) else None)
            link_base_internal = (INTERNAL_BASE_URL or (request.host_url.rstrip('/') if request and hasattr(request, 'host_url') else None))
            thread = threading.Thread(target=_background_download, args=(task_id, video_url, quality, client_meta, "download_video_async", link_base_external or "", link_base_internal or "", cookies_from_browser, webhook_url))
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
                    "metadata_url_internal": build_internal_url(f"/download/{task_id}/metadata.json", link_base_internal),
                    "client_meta": client_meta,
                    "webhook_url": webhook_url
                }
            else:
                resp_async = {
                    "task_id": task_id,
                    "status": "processing",
                    "check_status_url_internal": build_internal_url(f"/task_status/{task_id}", link_base_internal),
                    "metadata_url_internal": build_internal_url(f"/download/{task_id}/metadata.json", link_base_internal),
                    "client_meta": client_meta,
                    "webhook_url": webhook_url
                }
            return jsonify(resp_async), 202

        # Sync mode: download immediately and return result
        task_id = str(uuid.uuid4())
        logger.info(f"[{task_id[:8]}] Task created (sync): {video_url}")
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
                # Метафайл как массив из одного объекта, по требуемому формату
                meta_item = {
                    "task_id": task_id,
                    "status": "completed",
                    "video_id": info.get('id'),
                    "title": info.get('title'),
                    "filename": filename,
                    "download_endpoint": download_endpoint,
                    "storage_rel_path": storage_rel_path,
                    "duration": info.get('duration'),
                    "resolution": info.get('resolution'),
                    "ext": ext,
                    "created_at": created_at_iso,
                    "completed_at": completed_at_iso
                }
                if webhook_url:
                    meta_item["webhook_url"] = webhook_url
                if PUBLIC_BASE_URL and API_KEY:
                    meta_item["task_download_url"] = task_download_url
                    meta_item["metadata_url"] = build_absolute_url(f"/download/{task_id}/metadata.json")
                    meta_item["task_download_url_internal"] = task_download_url_internal
                    meta_item["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json")
                else:
                    meta_item["task_download_url_internal"] = task_download_url_internal
                    meta_item["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json")
                if client_meta is not None:
                    meta_item["client_meta"] = client_meta
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
                    if mi.get('webhook_url') is not None:
                        resp['webhook_url'] = mi.get('webhook_url')
                    if endpoint:
                        if PUBLIC_BASE_URL and API_KEY:
                            resp["task_download_url"] = _join_url(PUBLIC_BASE_URL, endpoint)
                            resp["metadata_url"] = _join_url(PUBLIC_BASE_URL, f"/download/{task_id}/metadata.json")
                            resp["task_download_url_internal"] = build_internal_url(endpoint)
                            resp["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json")
                        else:
                            resp["task_download_url_internal"] = build_internal_url(endpoint)
                            resp["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json")
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
                    if meta.get('client_meta') is not None:
                        resp['client_meta'] = meta['client_meta']
                    if meta.get('webhook_url') is not None:
                        resp['webhook_url'] = meta.get('webhook_url')
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
    # Добавляем client_meta строго последним, если присутствует
    if task.get('client_meta') is not None:
        resp['client_meta'] = task['client_meta']
    if task.get('webhook_url') is not None:
        resp['webhook_url'] = task['webhook_url']
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
    webhook_url: str | None = None
):
    def _post_webhook(payload: dict):
        if not webhook_url:
            logger.debug(f"[{task_id[:8]}] Webhook skipped: no webhook_url provided")
            return
        logger.info(f"[{task_id[:8]}] Sending webhook")
        logger.debug(f"[{task_id[:8]}] webhook_url={webhook_url}")
        headers = {"Content-Type": "application/json"}
        # Добавляем пользовательские заголовки, не позволяя переопределять Content-Type
        try:
            for k, v in (WEBHOOK_HEADERS or {}).items():
                if k.lower() == 'content-type':
                    continue
                headers[k] = v
        except Exception:
            pass
        body = json.dumps(payload, ensure_ascii=False)
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
                resp = requests.post(webhook_url, headers=headers, data=body, timeout=WEBHOOK_TIMEOUT_SECONDS)
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
            meta_item = {
                "task_id": task_id,
                "status": "completed",
                "video_id": info.get('id'),
                "title": info.get('title'),
                "filename": filename,
                "download_endpoint": download_endpoint,
                "storage_rel_path": storage_rel_path,
                "duration": info.get('duration'),
                "resolution": info.get('resolution'),
                "ext": ext,
                "created_at": created_at_iso,
                "completed_at": completed_at_iso
            }
            if base_url_external:
                meta_item["task_download_url"] = full_task_download_url
                meta_item["metadata_url"] = build_absolute_url(f"/download/{task_id}/metadata.json", base_url_external)
                meta_item["task_download_url_internal"] = full_task_download_url_internal
                meta_item["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json", base_url_internal or None)
            else:
                meta_item["task_download_url_internal"] = full_task_download_url_internal
                meta_item["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json", base_url_internal or None)
            if client_meta is not None:
                meta_item["client_meta"] = client_meta
            if webhook_url:
                meta_item["webhook_url"] = webhook_url
            save_task_metadata(task_id, [meta_item])

            # webhook payload (client_meta последним)
            payload = {
                "task_id": task_id,
                "status": "completed",
                "video_id": info.get('id'),
                "title": info.get('title'),
                "filename": filename,
                "download_endpoint": download_endpoint,
                "storage_rel_path": storage_rel_path,
                "duration": info.get('duration'),
                "resolution": info.get('resolution'),
                "ext": ext,
                "created_at": created_at_iso,
                "completed_at": completed_at_iso
            }
            if base_url_external:
                payload["task_download_url"] = full_task_download_url
                payload["metadata_url"] = build_absolute_url(f"/download/{task_id}/metadata.json", base_url_external)
                payload["task_download_url_internal"] = full_task_download_url_internal
                payload["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json", base_url_internal or None)
            else:
                payload["task_download_url_internal"] = full_task_download_url_internal
                payload["metadata_url_internal"] = build_internal_url(f"/download/{task_id}/metadata.json", base_url_internal or None)
            if client_meta is not None:
                payload["client_meta"] = client_meta
            _post_webhook(payload)
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
        if client_meta is not None:
            payload['client_meta'] = client_meta
        _post_webhook(payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
