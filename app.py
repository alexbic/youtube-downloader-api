from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import json
from datetime import datetime
import tempfile
import shutil

app = Flask(__name__)

# Конфигурация
DOWNLOAD_DIR = "/app/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Очистка старых файлов (старше 1 часа)
def cleanup_old_files():
    """Удаляет файлы старше 1 часа"""
    import time
    current_time = time.time()
    for root, dirs, files in os.walk(DOWNLOAD_DIR):
        for d in dirs:
            dir_path = os.path.join(root, d)
            try:
                # Проверяем время модификации директории
                if current_time - os.path.getmtime(dir_path) > 3600:  # 1 час
                    shutil.rmtree(dir_path)
            except Exception:
                pass

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/get_direct_url', methods=['POST'])
def get_direct_url():
    """Получить прямую ссылку на скачивание без загрузки файла"""
    try:
        data = request.json
        video_url = data.get('url')
        quality = data.get('quality', 'best[height<=720]')

        if not video_url:
            return jsonify({"success": False, "error": "URL is required"}), 400

        ydl_opts = {
            'format': quality,
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

            # Получаем HTTP headers необходимые для скачивания
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

@app.route('/download_video', methods=['POST'])
def download_video():
    """Скачать видео на сервер и вернуть ссылку на файл"""
    try:
        data = request.json
        video_url = data.get('url')
        quality = data.get('quality', 'best[height<=720]')

        if not video_url:
            return jsonify({"success": False, "error": "URL is required"}), 400

        # Создаем уникальную папку для загрузки
        temp_dir = tempfile.mkdtemp(dir=DOWNLOAD_DIR)

        ydl_opts = {
            'format': quality,
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)

            # Находим скачанный файл
            downloaded_files = os.listdir(temp_dir)
            if downloaded_files:
                filename = downloaded_files[0]
                file_path = os.path.join(temp_dir, filename)
                file_size = os.path.getsize(file_path)

                return jsonify({
                    "success": True,
                    "video_id": info.get('id'),
                    "title": info.get('title'),
                    "filename": filename,
                    "file_path": file_path,
                    "file_size": file_size,
                    "download_url": f"/download_file/{os.path.basename(temp_dir)}/{filename}",
                    "duration": info.get('duration'),
                    "processed_at": datetime.now().isoformat()
                })
            else:
                return jsonify({"success": False, "error": "No file downloaded"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/download_file/<folder>/<filename>', methods=['GET'])
def download_file(folder, filename):
    """Скачать файл с сервера"""
    try:
        file_path = os.path.join(DOWNLOAD_DIR, folder, filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download_direct', methods=['POST'])
def download_direct():
    """Скачать видео и вернуть URL для скачивания (решает проблему 403)"""
    try:
        data = request.json
        video_url = data.get('url')
        quality = data.get('quality', 'best[height<=720]')

        if not video_url:
            return jsonify({"success": False, "error": "URL is required"}), 400

        # Очищаем старые файлы перед загрузкой
        cleanup_old_files()

        # Создаем уникальную папку для загрузки в DOWNLOAD_DIR
        temp_dir = tempfile.mkdtemp(dir=DOWNLOAD_DIR)

        ydl_opts = {
            'format': quality,
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)

            # Находим скачанный файл
            downloaded_files = os.listdir(temp_dir)
            if downloaded_files:
                filename = downloaded_files[0]
                file_path = os.path.join(temp_dir, filename)
                file_size = os.path.getsize(file_path)

                return jsonify({
                    "success": True,
                    "video_id": info.get('id'),
                    "title": info.get('title'),
                    "filename": filename,
                    "file_path": file_path,
                    "file_size": file_size,
                    "download_url": f"/download_file/{os.path.basename(temp_dir)}/{filename}",
                    "duration": info.get('duration'),
                    "resolution": info.get('resolution'),
                    "ext": info.get('ext'),
                    "note": "Use download_url to get the file. File will auto-delete after 1 hour.",
                    "processed_at": datetime.now().isoformat()
                })
            else:
                return jsonify({"success": False, "error": "No file downloaded"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/get_video_info', methods=['POST'])
def get_video_info():
    """Получить информацию о видео без загрузки"""
    try:
        data = request.json
        video_url = data.get('url')

        if not video_url:
            return jsonify({"success": False, "error": "URL is required"}), 400

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

            return jsonify({
                "success": True,
                "video_id": info.get('id'),
                "title": info.get('title'),
                "description": info.get('description', '')[:500],  # Первые 500 символов
                "duration": info.get('duration'),
                "view_count": info.get('view_count'),
                "like_count": info.get('like_count'),
                "uploader": info.get('uploader'),
                "upload_date": info.get('upload_date'),
                "thumbnail": info.get('thumbnail'),
                "tags": info.get('tags', [])[:10],  # Первые 10 тегов
                "available_formats": len(info.get('formats', [])),
                "processed_at": datetime.now().isoformat()
            })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
