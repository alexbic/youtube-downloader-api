from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import json
from datetime import datetime
import uuid
import threading
from functools import wraps

app = Flask(__name__)

# ============================================
# AUTH CONFIG
# ============================================
API_KEY = os.getenv('YTDL_API_KEY')
API_KEY_ENABLED = bool(API_KEY)

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_KEY_ENABLED:
            return f(*args, **kwargs)
        provided = request.headers.get('X-API-Key')
        if not provided:
            return jsonify({"success": False, "error": "Missing X-API-Key"}), 401
        if provided != API_KEY:
            return jsonify({"success": False, "error": "Invalid API key"}), 403
        return f(*args, **kwargs)
    return decorated

# ============================================
# DIRECTORIES & TASKS
# ============================================
DOWNLOAD_DIR = "/app/downloads"
TASKS_DIR = "/app/tasks"
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

# In-memory tasks
tasks_store = {}
def save_task(task_id: str, data: dict):
    tasks_store[task_id] = data
def get_task(task_id: str):
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
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat(), "auth": "enabled" if API_KEY_ENABLED else "disabled"})

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
            return jsonify({"success": False, "error": "URL is required"}), 400
        ydl_opts = {'format': quality,'quiet': True,'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            http_headers = info.get('http_headers', {})
            return jsonify({
                "success": True,
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
        return jsonify({"success": False, "error": str(e)}), 500

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
        client_meta = data.get('client_meta') or data.get('meta')
        if isinstance(client_meta, str):
            try:
                if len(client_meta.encode('utf-8')) > MAX_CLIENT_META_BYTES:
                    return jsonify({"success": False, "error": f"Invalid client_meta: exceeds {MAX_CLIENT_META_BYTES} bytes"}), 400
                parsed = json.loads(client_meta)
                client_meta = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError as e:
                return jsonify({"success": False, "error": f"Invalid client_meta JSON: {e}"}), 400
        ok, err = validate_client_meta(client_meta)
        if not ok:
            return jsonify({"success": False, "error": f"Invalid client_meta: {err}"}), 400
        if not video_url:
            return jsonify({"success": False, "error": "URL is required"}), 400

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
                "client_meta": client_meta
            }
            save_task(task_id, task_data)
            base_url = request.host_url.rstrip('/')
            thread = threading.Thread(target=_background_download, args=(task_id, video_url, quality, client_meta, "download_video_async", base_url))
            thread.daemon = True
            thread.start()
            return jsonify({
                "success": True,
                "task_id": task_id,
                "status": "processing",
                "check_status_url": f"/task_status/{task_id}",
                "metadata_url": f"/download/{task_id}/metadata.json",
                "client_meta": client_meta
            }), 202

        # Sync mode: download immediately and return result
        task_id = str(uuid.uuid4())
        create_task_dirs(task_id)
        safe_filename = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        outtmpl = os.path.join(get_task_output_dir(task_id), f'{safe_filename}.%(ext)s')
        ydl_opts = {'format': quality,'outtmpl': outtmpl,'quiet': True,'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            ext = info.get('ext', 'mp4')
            filename = f"{safe_filename}.{ext}"
            file_path = os.path.join(get_task_output_dir(task_id), filename)
            if os.path.exists(file_path):
                os.chmod(file_path, 0o644)
                file_size = os.path.getsize(file_path)
                download_path = f"/download_file/{filename}"  # legacy path
                base_url = request.host_url.rstrip('/')
                full_download_url = f"{base_url}{download_path}"
                task_download_path = build_download_path(task_id, filename)
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
                    "success": True,
                    "task_id": task_id,
                    "status": "completed",
                    "video_id": info.get('id'),
                    "title": info.get('title'),
                    "filename": filename,
                    "file_path": file_path,
                    "file_size": file_size,
                    "download_url": full_download_url,
                    "download_path": download_path,
                    "task_download_path": task_download_path,
                    "metadata_url": f"/download/{task_id}/metadata.json",
                    "duration": info.get('duration'),
                    "resolution": info.get('resolution'),
                    "ext": ext,
                    "client_meta": client_meta,
                    "processed_at": metadata['completed_at']
                })
            return jsonify({"success": False, "error": "No file downloaded"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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

# ============================================
# SYNC DOWNLOAD (download_direct)
# ============================================
@app.route('/download_direct', methods=['POST'])
@require_api_key
def download_direct():
    try:
        data = request.json or {}
        video_url = data.get('url')
        quality = data.get('quality', 'best[height<=720]')
        client_meta = data.get('client_meta') or data.get('meta')
        if isinstance(client_meta, str):
            try:
                if len(client_meta.encode('utf-8')) > MAX_CLIENT_META_BYTES:
                    return jsonify({"success": False, "error": f"Invalid client_meta: exceeds {MAX_CLIENT_META_BYTES} bytes"}), 400
                parsed = json.loads(client_meta)
                client_meta = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError as e:
                return jsonify({"success": False, "error": f"Invalid client_meta JSON: {e}"}), 400
        ok, err = validate_client_meta(client_meta)
        if not ok:
            return jsonify({"success": False, "error": f"Invalid client_meta: {err}"}), 400
        if not video_url:
            return jsonify({"success": False, "error": "URL is required"}), 400
        cleanup_old_files()
        task_id = str(uuid.uuid4())
        create_task_dirs(task_id)
        safe_filename = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        outtmpl = os.path.join(get_task_output_dir(task_id), f'{safe_filename}.%(ext)s')
        ydl_opts = {'format': quality,'outtmpl': outtmpl,'quiet': True,'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            ext = info.get('ext', 'mp4')
            filename = f"{safe_filename}.{ext}"
            file_path = os.path.join(get_task_output_dir(task_id), filename)
            if os.path.exists(file_path):
                os.chmod(file_path, 0o644)
                file_size = os.path.getsize(file_path)
                download_path = f"/download_file/{filename}"  # legacy
                base_url = request.host_url.rstrip('/')
                full_download_url = f"{base_url}{download_path}"
                task_download_path = build_download_path(task_id, filename)
                metadata = {
                    "task_id": task_id,
                    "status": "completed",
                    "mode": "sync",
                    "operation": "download_direct",
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
                    "success": True,
                    "task_id": task_id,
                    "status": "completed",
                    "video_id": info.get('id'),
                    "title": info.get('title'),
                    "filename": filename,
                    "file_path": file_path,
                    "file_size": file_size,
                    "download_url": full_download_url,
                    "download_path": download_path,
                    "task_download_path": task_download_path,
                    "metadata_url": f"/download/{task_id}/metadata.json",
                    "duration": info.get('duration'),
                    "resolution": info.get('resolution'),
                    "ext": ext,
                    "client_meta": client_meta,
                    "processed_at": metadata['completed_at']
                })
            return jsonify({"success": False, "error": "No file downloaded"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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
            return jsonify({"success": False, "error": "URL is required"}), 400
        ydl_opts = {'quiet': True,'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return jsonify({
                "success": True,
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
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================
# TASK STATUS
# ============================================
@app.route('/task_status/<task_id>', methods=['GET'])
def task_status(task_id):
    task = get_task(task_id)
    if not task:
        return jsonify({"success": False, "error": "Task not found"}), 404
    resp = {"success": True, "task_id": task_id, "status": task.get('status'), "created_at": task.get('created_at')}
    if task.get('client_meta') is not None:
        resp['client_meta'] = task['client_meta']
    if task.get('status') == 'completed':
        resp.update({
            "video_id": task.get('video_id'),
            "title": task.get('title'),
            "filename": task.get('filename'),
            "download_url": task.get('download_url'),
            "download_path": task.get('download_path'),
            "task_download_path": task.get('task_download_path'),
            "metadata_url": f"/download/{task_id}/metadata.json",
            "duration": task.get('duration'),
            "resolution": task.get('resolution'),
            "ext": task.get('ext'),
            "completed_at": task.get('completed_at')
        })
    elif task.get('status') == 'error':
        resp['error'] = task.get('error')
    return jsonify(resp)

def _background_download(task_id: str, video_url: str, quality: str, client_meta: dict, operation: str = "download_video_async", base_url: str = ""):
    try:
        update_task(task_id, {"status": "downloading"})
        safe_filename = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        outtmpl = os.path.join(get_task_output_dir(task_id), f'{safe_filename}.%(ext)s')
        ydl_opts = {'format': quality,'outtmpl': outtmpl,'quiet': True,'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            ext = info.get('ext', 'mp4')
            filename = f"{safe_filename}.{ext}"
            file_path = os.path.join(get_task_output_dir(task_id), filename)
            if os.path.exists(file_path):
                os.chmod(file_path, 0o644)
                file_size = os.path.getsize(file_path)
                download_path = f"/download_file/{filename}"
                full_download_url = f"{base_url}{download_path}" if base_url else download_path
                task_download_path = build_download_path(task_id, filename)
                update_task(task_id, {
                    "status": "completed",
                    "video_id": info.get('id'),
                    "title": info.get('title'),
                    "filename": filename,
                    "duration": info.get('duration'),
                    "resolution": info.get('resolution'),
                    "ext": ext,
                    "download_url": full_download_url,
                    "download_path": download_path,
                    "task_download_path": task_download_path,
                    "completed_at": datetime.now().isoformat()
                })
                metadata = {
                    "task_id": task_id,
                    "status": "completed",
                    "operation": operation,
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
            else:
                update_task(task_id, {"status": "error", "error": "File not downloaded"})
    except Exception as e:
        update_task(task_id, {"status": "error", "error": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
