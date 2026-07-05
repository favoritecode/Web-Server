import json
import os
import yt_dlp
import requests
import time
import uuid
import re
from flask import request, jsonify, send_from_directory, Response, session

BASE_DIR = os.path.dirname(__file__)
PROJECT_DIR = os.path.dirname(BASE_DIR)
DATA_FILE = os.path.join(BASE_DIR, "videos.json")
LOCAL_DATA_FILE = os.path.join(BASE_DIR, "videos.local.json")
COOKIES_FILE = os.path.join(PROJECT_DIR, "cookies.txt")
LOCAL_COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")

UPSTREAM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
}


def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def atomic_write_json(path, data):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def load_videos():
    videos = read_json_file(DATA_FILE)
    local_videos = read_json_file(LOCAL_DATA_FILE)
    videos.update(local_videos)
    return videos


def save_videos(videos):
    atomic_write_json(DATA_FILE, videos)
    atomic_write_json(LOCAL_DATA_FILE, videos)

def current_owner_key():
    user = session.get("user") or {}
    raw = (user.get("email") or user.get("sub") or user.get("name") or "anonymous").strip().lower()
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in raw).strip("._")[:120] or "anonymous"


def record_url(record):
    if isinstance(record, dict):
        return record.get("url") or record.get("source")
    return record

def get_cookie_file():
    for path in (COOKIES_FILE, LOCAL_COOKIES_FILE):
        if os.path.exists(path):
            return path
    return None


def public_origin():
    host = request.headers.get("X-Public-Host") or request.headers.get("X-Forwarded-Host") or request.host
    proto = request.headers.get("X-Public-Proto") or request.headers.get("X-Forwarded-Proto") or "https"
    return f"{proto}://{host}"


def ydl_opts(format_selector):
    opts = {
        "quiet": True,
        "skip_download": True,
        "format": format_selector,
        "nocheckcertificate": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "http_headers": UPSTREAM_HEADERS,
    }
    cookie_file = get_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file
    return opts


# 🎥 video extract (force mp4 for better compatibility)
def extract_video(url):
    with yt_dlp.YoutubeDL(ydl_opts("best[ext=mp4]/best")) as ydl:
        info = ydl.extract_info(url, download=False)
        return info["url"]


# 🎧 audio extract
def extract_audio(url):
    with yt_dlp.YoutubeDL(ydl_opts("bestaudio/best")) as ydl:
        info = ydl.extract_info(url, download=False)
        return info["url"]


def init_routes(app):

    # homepage
    @app.route("/ytplayer/")
    def index():
        return send_from_directory(BASE_DIR, "index.html")

    # live stream page
    @app.route("/ytplayer/live")
    def live_page():
        return send_from_directory(BASE_DIR, "live.html")


    # ➕ add url
    @app.route("/ytplayer/add", methods=["POST"])
    def add_video():
        data = request.get_json() or {}
        url = (data.get("url") or "").strip()
        slug = (data.get("slug") or "").strip()
        if not url:
            return jsonify({"error": "URL is required"}), 400

        videos = load_videos()

        if slug:
            if not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", slug):
                return jsonify({"error": "Slug can use letters, numbers, dash and underscore only"}), 400
            if slug in videos:
                return jsonify({"error": "Slug already exists"}), 409
            video_id = slug
        else:
            video_id = str(int(time.time())) + "-" + uuid.uuid4().hex[:8]
        videos[video_id] = {
            "url": url,
            "owner": current_owner_key(),
            "title": url,
            "slug": video_id,
            "created_at": int(time.time()),
        }

        save_videos(videos)

        base = public_origin()

        return jsonify({
            "video": base + "/ytplayer/stream/" + video_id,
            "audio": base + "/ytplayer/play/" + video_id
        })


    # 🎥 VIDEO STREAM (FIXED WITH RANGE SUPPORT)
    @app.route("/ytplayer/stream/<id>")
    def stream(id):

        videos = load_videos()
        record = videos.get(id)
        url = record_url(record)

        if not url:
            return "Video not found", 404

        video_url = extract_video(url)

        headers = {}

        # 🔥 IMPORTANT: forward range header
        if "Range" in request.headers:
            headers["Range"] = request.headers["Range"]

        headers.update(UPSTREAM_HEADERS)
        r = requests.get(video_url, headers=headers, stream=True, timeout=60)

        def generate():
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        response = Response(
            generate(),
            status=r.status_code,
            content_type=r.headers.get("Content-Type", "video/mp4")
        )

        # 🔥 IMPORTANT HEADERS
        if "Content-Range" in r.headers:
            response.headers["Content-Range"] = r.headers["Content-Range"]

        response.headers["Accept-Ranges"] = "bytes"

        if "Content-Length" in r.headers:
            response.headers["Content-Length"] = r.headers["Content-Length"]

        return response


    # 🎧 AUDIO STREAM (FIXED)
    @app.route("/ytplayer/play/<id>")
    def play_audio(id):

        videos = load_videos()
        record = videos.get(id)
        url = record_url(record)

        if not url:
            return "Audio not found", 404

        audio_url = extract_audio(url)

        headers = {}

        if "Range" in request.headers:
            headers["Range"] = request.headers["Range"]

        headers.update(UPSTREAM_HEADERS)
        r = requests.get(audio_url, headers=headers, stream=True, timeout=60)

        def generate():
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        response = Response(
            generate(),
            status=r.status_code,
            content_type=r.headers.get("Content-Type", "audio/mpeg")
        )

        if "Content-Range" in r.headers:
            response.headers["Content-Range"] = r.headers["Content-Range"]

        response.headers["Accept-Ranges"] = "bytes"

        if "Content-Length" in r.headers:
            response.headers["Content-Length"] = r.headers["Content-Length"]

        return response
