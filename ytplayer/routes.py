import json
import os
import yt_dlp
import requests
import time
import uuid
import re
import shutil
import subprocess
from flask import request, jsonify, send_from_directory, send_file, Response, session

BASE_DIR = os.path.dirname(__file__)
PROJECT_DIR = os.path.dirname(BASE_DIR)
DATA_FILE = os.path.join(BASE_DIR, "videos.json")
LOCAL_DATA_FILE = os.path.join(BASE_DIR, "videos.local.json")
MEDIA_CACHE_DIR = os.path.join(BASE_DIR, "cache")
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


def is_youtube_short(url):
    return bool(re.search(r"(?:youtube\.com/shorts/|youtu\.be/shorts/)", url or "", re.I))


def should_cache_first(url):
    # Stream through a fresh yt-dlp URL first. Downloading a whole normal
    # YouTube video before responding makes HEAD/curl/browser probes slow and
    # can hit YouTube 403s. Cache remains a last-resort fallback below.
    return False

def get_cookie_file():
    for path in (COOKIES_FILE, LOCAL_COOKIES_FILE):
        if os.path.exists(path):
            return path
    return None


def public_origin():
    host = request.headers.get("X-Public-Host") or request.headers.get("X-Forwarded-Host") or request.host
    proto = request.headers.get("X-Public-Proto") or request.headers.get("X-Forwarded-Proto") or "https"
    return f"{proto}://{host}"


def ydl_opts(format_selector, use_cookies=True, skip_streaming_formats=True):
    youtube_args = {
        "player_client": ["web_safari", "ios", "tv", "android_vr", "web"],
    }
    if skip_streaming_formats:
        youtube_args["skip"] = ["hls", "dash"]

    opts = {
        "quiet": True,
        "skip_download": True,
        "format": format_selector,
        "nocheckcertificate": True,
        "socket_timeout": 30,
        "retries": 0,
        "fragment_retries": 0,
        "http_headers": UPSTREAM_HEADERS,
        "remote_components": ["ejs:github"],
        # rotate multiple player clients to dodge YouTube bot-blocks / 403s
        "extractor_args": {"youtube": youtube_args},
    }
    # Use a JS runtime to solve YouTube's n-challenge (required for regular
    # videos; Shorts work without it). Prefer node (installed) over deno.
    if use_cookies:
        cookie_file = get_cookie_file()
        if cookie_file:
            opts["cookiefile"] = cookie_file
    if shutil.which("node"):
        opts["js_runtimes"] = {"node": {"path": shutil.which("node")}}
    elif shutil.which("deno"):
        opts["js_runtimes"] = {"deno": {"path": shutil.which("deno")}}
    return opts


def _pick_url(info):
    """Return the most reliable direct URL from yt-dlp info."""
    for key in ("url", "manifest_url"):
        if info.get(key):
            return info[key]
    formats = info.get("formats") or []
    if formats:
        for f in formats:
            u = f.get("url") or f.get("manifest_url")
            if u:
                return u
    raise RuntimeError("No direct media URL found")


def _yt_dlp_cli_path():
    return shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")


def _node_runtime_arg():
    node = shutil.which("node")
    if not node and os.path.exists(r"C:\Program Files\nodejs\node.exe"):
        node = r"C:\Program Files\nodejs\node.exe"
    return f"node:{node}" if node else None


def _try_extract_cli(url, fmt, client, use_cookies):
    exe = _yt_dlp_cli_path()
    if not exe:
        raise RuntimeError("yt-dlp CLI was not found")

    args = [
        exe,
        "-g",
        "--no-warnings",
        "--no-playlist",
        "-f",
        fmt,
        "--extractor-args",
        f"youtube:player_client={client}",
    ]

    node_runtime = _node_runtime_arg()
    if node_runtime:
        args.extend(["--js-runtimes", node_runtime])

    cookie_file = get_cookie_file() if use_cookies else None
    if cookie_file:
        args.extend(["--cookies", cookie_file])

    args.append(url)

    result = subprocess.run(
        args,
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith(("http://", "https://")):
            return line

    raise RuntimeError("yt-dlp CLI did not return a direct media URL")


def _direct_url_works(media_url):
    headers = dict(UPSTREAM_HEADERS)
    headers["Range"] = "bytes=0-1"
    try:
        r = requests.get(media_url, headers=headers, stream=True, timeout=20)
        try:
            return r.status_code < 400
        finally:
            r.close()
    except Exception:
        return False


def _try_extract(url, fmt, client, use_cookies):
    # Prefer the standalone yt-dlp executable when present. On this server it is
    # newer than the venv module and handles regular YouTube videos that the old
    # module currently resolves to 403-prone URLs.
    cli_err = None
    try:
        return _try_extract_cli(url, fmt, client, use_cookies)
    except Exception as e:  # noqa: BLE001
        cli_err = e

    opts = ydl_opts(fmt, use_cookies=use_cookies)
    opts["extractor_args"] = {"youtube": {"player_client": [client], "skip": ["hls", "dash"]}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return _pick_url(info)
    except Exception as module_err:  # noqa: BLE001
        raise module_err from cli_err


def _download_to_cache_cli(video_id, url, kind):
    exe = _yt_dlp_cli_path()
    if not exe:
        raise RuntimeError("yt-dlp CLI was not found")

    os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)
    safe_id = _safe_cache_id(video_id)
    outtmpl = os.path.join(MEDIA_CACHE_DIR, f"{safe_id}-{kind}.%(ext)s")
    fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" if kind == "video" else "bestaudio[ext=m4a]/bestaudio/best"

    args = [
        exe,
        "--no-playlist",
        "--continue",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "-f",
        fmt,
        "-o",
        outtmpl,
    ]

    node_runtime = _node_runtime_arg()
    if node_runtime:
        args.extend(["--js-runtimes", node_runtime])

    if kind == "video":
        args.extend(["--merge-output-format", "mp4"])

    cookie_file = get_cookie_file()
    if cookie_file:
        args.extend(["--cookies", cookie_file])

    args.append(url)

    subprocess.run(args, cwd=PROJECT_DIR, timeout=1800, check=True)

    cached = _cached_media_file(video_id, kind)
    if cached:
        return cached
    raise RuntimeError("yt-dlp CLI finished but cached media file was not found")



# 🎥 video extract (force mp4 for better compatibility)
def extract_video(url):
    last_err = None
    clients = ["web_safari", "web_embedded", "mweb", "web", "ios", "tv", "android_vr", "tv_embedded"]
    formats = ["best[ext=mp4]/best", "best"]
    # Try anonymous first (stale cookies cause 403), then with cookies
    for use_cookies in (False, True):
        for client in clients:
            for fmt in formats:
                try:
                    direct = _try_extract(url, fmt, client, use_cookies)
                    if direct and _direct_url_works(direct):
                        return direct
                    last_err = RuntimeError(f"Direct URL from {client} returned HTTP 403/blocked")
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    continue
    if last_err:
        raise last_err
    raise RuntimeError("Video extraction failed for all player clients")


# 🎧 audio extract
def extract_audio(url):
    last_err = None
    clients = ["web_safari", "web_embedded", "mweb", "web", "ios", "tv", "android_vr", "tv_embedded"]
    formats = ["bestaudio/best", "best"]
    # Try anonymous first (stale cookies cause 403), then with cookies
    for use_cookies in (False, True):
        for client in clients:
            for fmt in formats:
                try:
                    direct = _try_extract(url, fmt, client, use_cookies)
                    if direct and _direct_url_works(direct):
                        return direct
                    last_err = RuntimeError(f"Direct URL from {client} returned HTTP 403/blocked")
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    continue
    if last_err:
        raise last_err
    raise RuntimeError("Audio extraction failed for all player clients")


def _safe_cache_id(video_id):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", video_id).strip("._")[:120] or uuid.uuid4().hex


def _cached_media_file(video_id, kind):
    safe_id = _safe_cache_id(video_id)
    if not os.path.isdir(MEDIA_CACHE_DIR):
        return None
    prefix = f"{safe_id}-{kind}."
    for name in os.listdir(MEDIA_CACHE_DIR):
        path = os.path.join(MEDIA_CACHE_DIR, name)
        if name.startswith(prefix) and os.path.isfile(path) and not name.endswith(".part"):
            return path
    return None


def _download_to_cache(video_id, url, kind):
    cached = _cached_media_file(video_id, kind)
    if cached:
        return cached

    os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)
    safe_id = _safe_cache_id(video_id)
    outtmpl = os.path.join(MEDIA_CACHE_DIR, f"{safe_id}-{kind}.%(ext)s")
    fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" if kind == "video" else "bestaudio[ext=m4a]/bestaudio/best"
    last_err = None
    for use_cookies in (False, True):
        opts = ydl_opts(fmt, use_cookies=use_cookies, skip_streaming_formats=False)
        opts.update({
            "skip_download": False,
            "outtmpl": outtmpl,
            "noplaylist": True,
            "continuedl": True,
            "overwrites": False,
            "quiet": True,
            "noprogress": True,
            "retries": 3,
            "fragment_retries": 3,
        })
        if kind == "video":
            opts["merge_output_format"] = "mp4"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
    else:
        try:
            return _download_to_cache_cli(video_id, url, kind)
        except Exception as cli_err:  # noqa: BLE001
            raise cli_err from last_err

    cached = _cached_media_file(video_id, kind)
    if cached:
        return cached
    raise RuntimeError("Download finished but cached media file was not found")


def _proxy_direct_url(media_url, default_content_type):
    headers = {}
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]
    headers.update(UPSTREAM_HEADERS)

    r = requests.get(media_url, headers=headers, stream=True, timeout=60)
    if r.status_code >= 400:
        r.close()
        raise RuntimeError(f"Direct media request failed with HTTP {r.status_code}")

    def generate():
        try:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            r.close()

    response = Response(
        generate(),
        status=r.status_code,
        content_type=r.headers.get("Content-Type", default_content_type)
    )

    if "Content-Range" in r.headers:
        response.headers["Content-Range"] = r.headers["Content-Range"]

    response.headers["Accept-Ranges"] = "bytes"

    if "Content-Length" in r.headers:
        response.headers["Content-Length"] = r.headers["Content-Length"]

    return response


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

        if should_cache_first(url):
            file_path = _download_to_cache(id, url, "video")
            return send_file(file_path, mimetype="video/mp4", conditional=True)

        try:
            return _proxy_direct_url(extract_video(url), "video/mp4")
        except Exception:
            file_path = _download_to_cache(id, url, "video")
            return send_file(file_path, mimetype="video/mp4", conditional=True)

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

        if should_cache_first(url):
            file_path = _download_to_cache(id, url, "audio")
            return send_file(file_path, conditional=True)

        try:
            return _proxy_direct_url(extract_audio(url), "audio/mpeg")
        except Exception:
            file_path = _download_to_cache(id, url, "audio")
            return send_file(file_path, conditional=True)

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
