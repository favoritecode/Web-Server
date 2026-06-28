from flask import Blueprint, send_from_directory, request, jsonify, Response, stream_with_context
from yt_dlp import YoutubeDL
import json
import requests as http_requests
import os
import tempfile
import shutil
import subprocess
import re
import unicodedata
import urllib.parse
import mimetypes
import threading
import uuid
import time

download = Blueprint("download", __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")
DOWNLOAD_JOBS = {}
DOWNLOAD_JOBS_LOCK = threading.Lock()
JOB_TTL_SECONDS = 6 * 60 * 60


def _find_cookies():
    """Find cookies.txt from multiple possible locations."""
    candidates = [
        COOKIES_FILE,
        os.path.join(BASE_DIR, "ytplayer", "cookies.txt"),
        os.path.join(os.path.dirname(BASE_DIR), "cookies.txt"),
        "cookies.txt",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _base_ydl_opts(extra=None):
    """Base yt-dlp options with cookies, headers, and error handling."""
    opts = {
        "quiet": True,
        "nocheckcertificate": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "skip_unavailable_fragments": False,
        "noplaylist": True,
    }

    cookies_path = _find_cookies()
    if cookies_path:
        opts["cookiefile"] = cookies_path

    opts["http_headers"] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Mode": "navigate",
    }

    if extra:
        opts.update(extra)

    return opts



def _normalize_media_url(url):
    """Normalize social video URLs so playlist/share parameters do not break single-video downloads."""
    if not url:
        return url

    value = url.strip()
    if not value:
        return value

    if re.match(r"^[A-Za-z0-9_-]{11}$", value):
        return f"https://www.youtube.com/watch?v={value}"

    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value

    parsed = urllib.parse.urlparse(value)
    host = (parsed.netloc or "").lower()
    host = host.split("@")[-1].split(":")[0]
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    video_id = ""

    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if parsed.path == "/watch" and query.get("v"):
            video_id = query.get("v", [""])[0]
        else:
            match = re.match(r"^/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{6,})", parsed.path)
            if match:
                video_id = match.group(1)

    if video_id:
        clean_query = {"v": video_id}
        for keep_key in ("t", "start"):
            if query.get(keep_key):
                clean_query[keep_key] = query[keep_key][0]
        return urllib.parse.urlunparse(("https", "www.youtube.com", "/watch", "", urllib.parse.urlencode(clean_query), ""))

    return value

def _sanitize_filename(name):
    """Remove or replace characters that are unsafe in filenames/headers."""
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name)
    name = re.sub(r'[_\s]+', ' ', name).strip()
    if len(name) > 200:
        name = name[:200].rstrip()
    return name or "video"


def _stream_file_response(file_path, temp_dir, filename, content_type=None):
    file_size = os.path.getsize(file_path)
    content_type = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

    def generate():
        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    response = Response(
        stream_with_context(generate()),
        content_type=content_type,
    )
    encoded_name = urllib.parse.quote(filename, safe="")
    response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_name}"
    response.headers["Content-Length"] = str(file_size)
    response.headers["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Length"
    response.headers["Cache-Control"] = "no-cache"
    return response


def _as_int(value, default=0):
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def _codec_name(codec):
    if not codec or codec == "none":
        return ""

    codec = codec.split(".")[0].lower()
    names = {
        "avc1": "H.264",
        "h264": "H.264",
        "hev1": "H.265",
        "hvc1": "H.265",
        "vp09": "VP9",
        "vp9": "VP9",
        "av01": "AV1",
        "mp4a": "AAC",
        "aac": "AAC",
        "opus": "Opus",
    }
    return names.get(codec, codec.upper())


def _format_label(fmt, kind):
    ext = (fmt.get("ext") or "").upper()

    if kind == "audio":
        abr = _as_int(fmt.get("abr"))
        codec = _codec_name(fmt.get("acodec"))
        parts = [f"{abr} kbps" if abr else "Best audio", codec, ext]
    else:
        height = _as_int(fmt.get("height"))
        fps = _as_int(fmt.get("fps"))
        vcodec = _codec_name(fmt.get("vcodec"))
        acodec = _codec_name(fmt.get("acodec"))
        parts = [f"{height}p" if height else (fmt.get("format_note") or "Video")]
        if fps and fps > 30:
            parts.append(f"{fps}fps")
        parts.extend([vcodec, acodec, ext])

    return " - ".join(part for part in parts if part)


def _format_size(fmt):
    return fmt.get("filesize") or fmt.get("filesize_approx") or 0


def _ffmpeg_bin(name):
    candidates = [
        os.path.join("C:\\", "ffmpeg", "bin", f"{name}.exe"),
        name,
    ]
    for candidate in candidates:
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
    return name


def _compat_score(fmt):
    ext = (fmt.get("ext") or "").lower()
    vcodec = (fmt.get("vcodec") or "").lower()
    acodec = (fmt.get("acodec") or "").lower()
    score = 0

    if ext == "mp4":
        score += 40
    if vcodec.startswith(("avc1", "h264")):
        score += 35
    if acodec.startswith(("mp4a", "aac")):
        score += 25
    if fmt.get("protocol") in {"https", "http"}:
        score += 5

    return score


def _build_formats(info):
    videos = []
    audios = []
    seen_video = set()
    seen_audio = set()

    if info.get("url") and not info.get("formats"):
        videos.append({
            "formatId": info.get("format_id"),
            "url": info["url"],
            "label": "Best Video + Audio",
            "quality": _as_int(info.get("height")),
            "fps": _as_int(info.get("fps")),
            "ext": info.get("ext", "mp4"),
            "vcodec": _codec_name(info.get("vcodec")),
            "acodec": _codec_name(info.get("acodec")),
            "hasAudio": True,
            "filesize": info.get("filesize") or info.get("filesize_approx"),
            "smooth": 100,
        })
        return videos, audios

    for fmt in info.get("formats", []):
        url = fmt.get("url")
        if not url:
            continue

        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        has_video = vcodec and vcodec != "none"
        has_audio = acodec and acodec != "none"

        if has_video:
            key = (
                _as_int(fmt.get("height")),
                _as_int(fmt.get("fps")),
                fmt.get("ext"),
                vcodec,
                acodec if has_audio else "video-only",
            )
            if key not in seen_video:
                seen_video.add(key)
                videos.append({
                    "formatId": fmt.get("format_id"),
                    "url": url,
                    "label": _format_label(fmt, "video"),
                    "quality": _as_int(fmt.get("height")),
                    "fps": _as_int(fmt.get("fps")),
                    "ext": fmt.get("ext"),
                    "vcodec": _codec_name(vcodec),
                    "acodec": _codec_name(acodec),
                    "hasAudio": has_audio,
                    "filesize": _format_size(fmt),
                    "smooth": _compat_score(fmt),
                })

        if has_audio and not has_video:
            key = (_as_int(fmt.get("abr")), fmt.get("ext"), acodec)
            if key not in seen_audio:
                seen_audio.add(key)
                audios.append({
                    "formatId": fmt.get("format_id"),
                    "url": url,
                    "label": _format_label(fmt, "audio"),
                    "bitrate": _as_int(fmt.get("abr")),
                    "ext": fmt.get("ext"),
                    "acodec": _codec_name(acodec),
                    "filesize": _format_size(fmt),
                    "smooth": _compat_score(fmt),
                })

    videos.sort(
        key=lambda item: (
            item["hasAudio"],
            item["quality"],
            item["fps"],
            item["smooth"],
        ),
        reverse=True,
    )
    audios.sort(key=lambda item: (item["bitrate"], item["smooth"]), reverse=True)

    best_audio_size = audios[0]["filesize"] if audios else 0
    for item in videos:
        if not item["hasAudio"] and item["filesize"] and best_audio_size:
            item["filesize"] += best_audio_size
            item["filesizeApprox"] = True

    return videos, audios


def _extract_info_safe(url):
    """Try to extract info with multiple format fallbacks."""
    url = _normalize_media_url(url)
    errors = []

    strategies = [
        {"format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"},
        {"format": "best"},
        {"format": "mp4"},
        {"format": "bestaudio/best"},
    ]

    for strategy in strategies:
        try:
            opts = _base_ydl_opts({**strategy, "skip_download": True})
            with YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as e:
            errors.append(str(e))
            continue

    raise Exception(
        "All download strategies failed. Last error: " + errors[-1] if errors else "Unknown error"
    )


# ----------------------------
# Download Page
# ----------------------------

@download.route("/download")
def download_page():
    return send_from_directory("download/public", "index.html")


@download.route("/download/")
def download_page_slash():
    return send_from_directory("download/public", "index.html")


# ----------------------------
# API
# ----------------------------

@download.route("/download/api")
def api():

    url = _normalize_media_url(request.args.get("url"))

    if not url:
        return jsonify({"error": "No URL"})

    try:
        info = _extract_info_safe(url)
    except Exception as exc:
        error_msg = str(exc)
        social_media_domains = ["facebook.com", "fb.com", "fb.watch", "instagram.com", "tiktok.com", "vm.tiktok.com", "youtube.com", "youtu.be"]
        is_social = any(d in url.lower() for d in social_media_domains)
        
        if is_social:
            return jsonify({
                "title": "Social Media Video",
                "thumbnail": None,
                "duration": None,
                "duration_string": None,
                "video": None,
                "audio": None,
                "videos": [{"url": None, "label": "Best Video + Audio (Server Download)", "hasAudio": True, "filesize": None, "quality": 0, "ext": "mp4"}],
                "audios": [],
                "_server_download": True,
            })
        
        if "Unsupported URL" in error_msg:
            return jsonify({"error": "Unsupported website or URL"}), 400
        if "Private video" in error_msg or "Sign in" in error_msg:
            return jsonify({"error": "This video may be private or require login. Try adding cookies."}), 400
        if "HTTP Error" in error_msg:
            return jsonify({"error": "Download blocked by the website. Try again later."}), 400
        return jsonify({"error": "Video not available", "details": error_msg}), 400

    if info.get("_type") == "playlist" and info.get("entries"):
        info = next((entry for entry in info["entries"] if entry), info)

    videos, audios = _build_formats(info)
    best_video = next((item for item in videos if item["hasAudio"]), videos[0] if videos else None)
    best_audio = audios[0] if audios else None

    return jsonify({
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "duration_string": info.get("duration_string"),
        "video": best_video["url"] if best_video else None,
        "audio": best_audio["url"] if best_audio else None,
        "videos": videos,
        "audios": audios,
    })


# ----------------------------
# Proxy Download (with progress tracking)
# ----------------------------

@download.route("/download/proxy")
def proxy_download():
    """Proxies a remote URL through our server so the browser
    can track real byte-by-byte download progress via Fetch API + ReadableStream."""
    url = request.args.get("url")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        resp = http_requests.get(
            url,
            stream=True,
            timeout=60,
            allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": url,
            },
        )
        resp.raise_for_status()

        total_size = resp.headers.get("Content-Length")
        content_type = resp.headers.get("Content-Type", "application/octet-stream")

        def generate():
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk

        response = Response(
            stream_with_context(generate()),
            content_type=content_type,
        )

        if total_size:
            response.headers["Content-Length"] = str(total_size)
        response.headers["Access-Control-Expose-Headers"] = "Content-Length"
        response.headers["Cache-Control"] = "no-cache"

        return response

    except Exception as exc:
        return jsonify({"error": "Download failed", "details": str(exc)}), 500


# ----------------------------
# Server-Side Download (uses yt-dlp with H.264 post-processing)
# ----------------------------

def _set_job(job_id, **updates):
    if not job_id:
        return
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = time.time()


def _cleanup_old_jobs():
    now = time.time()
    expired = []
    with DOWNLOAD_JOBS_LOCK:
        for job_id, job in DOWNLOAD_JOBS.items():
            if now - job.get("updated_at", now) > JOB_TTL_SECONDS:
                expired.append((job_id, job.get("temp_dir")))
        for job_id, _ in expired:
            DOWNLOAD_JOBS.pop(job_id, None)
    for _, temp_dir in expired:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _download_progress_hook(job_id):
    def hook(data):
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            pct = int(max(0, min(95, (downloaded / total) * 95))) if total else 0
            _set_job(
                job_id,
                phase="Downloading media...",
                pct=pct,
                downloaded=downloaded,
                total=total,
            )
        elif status == "finished":
            _set_job(job_id, phase="Merging media...", pct=96)
    return hook


def _run_server_download(url, requested_format, selected_type, selected_has_audio, force_compat, job_id=None):
    url = _normalize_media_url(url)
    cookies_path = _find_cookies()
    temp_dir = tempfile.mkdtemp(prefix="favoriteweb-download-")
    safe_title = "video"

    try:
        _set_job(job_id, phase="Extracting video details...", pct=2, temp_dir=temp_dir)
        try:
            info_opts = _base_ydl_opts({"skip_download": True})
            with YoutubeDL(info_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            raw_title = info.get("title", "video")
            safe_title = _sanitize_filename(raw_title)
            _set_job(job_id, title=safe_title)
        except Exception:
            pass

        safe_outtmpl = os.path.join(temp_dir, "%(id)s.%(ext)s")

        if requested_format:
            if selected_type == "audio" or selected_has_audio:
                selected_format = requested_format
            else:
                selected_format = f"{requested_format}+bestaudio/best"
        else:
            selected_format = "bestvideo+bestaudio/best"

        dl_opts = _base_ydl_opts({
            "format": selected_format,
            "outtmpl": safe_outtmpl,
            "socket_timeout": 120,
            "retries": 25,
            "fragment_retries": 25,
            "extractor_retries": 5,
            "file_access_retries": 5,
            "continuedl": True,
            "noprogress": True,
            "nooverwrites": False,
            "concurrent_fragment_downloads": 4,
            "progress_hooks": [_download_progress_hook(job_id)],
        })
        if force_compat:
            dl_opts["merge_output_format"] = "mp4"

        format_strategies = [{}] if requested_format else [
            {},
            {"format": "best[ext=mp4]/best"},
            {"format": "best"},
            {"format": "mp4"},
        ]

        last_error = None
        downloaded = False
        for strategy in format_strategies:
            try:
                dl_opts_try = dict(dl_opts)
                dl_opts_try.update(strategy)
                _set_job(job_id, phase="Downloading media...", pct=5)
                with YoutubeDL(dl_opts_try) as ydl:
                    ydl.extract_info(url, download=True)
                downloaded = True
                break
            except Exception as e:
                last_error = str(e)[-700:]
                continue

        if not downloaded:
            error_msg = last_error or "Unknown download error"
            try:
                _set_job(job_id, phase="Retrying with yt-dlp command...", pct=5)
                output_template = os.path.join(temp_dir, "%(id)s.%(ext)s")
                ytdlp_cmd = [
                    "yt-dlp",
                    "--format", selected_format,
                    "--output", output_template,
                    "--no-playlist",
                    "--quiet",
                    "--no-warnings",
                    "--no-check-certificate",
                    "--continue",
                    "--retries", "25",
                    "--fragment-retries", "25",
                    "--extractor-retries", "5",
                    "--file-access-retries", "5",
                    "--socket-timeout", "120",
                    "--concurrent-fragments", "4",
                ]
                if force_compat:
                    ytdlp_cmd.extend(["--merge-output-format", "mp4"])
                if cookies_path:
                    ytdlp_cmd.extend(["--cookies", cookies_path])
                ytdlp_cmd.append(url)
                subprocess.run(ytdlp_cmd, check=True, timeout=7200, capture_output=True)
                downloaded = bool(os.listdir(temp_dir))
            except Exception:
                raise Exception(error_msg)

        files = [
            name for name in os.listdir(temp_dir)
            if not name.endswith((".part", ".ytdl", ".temp", ".tmp"))
        ]
        if not files:
            raise Exception("No file was downloaded")

        files.sort(key=lambda name: os.path.getsize(os.path.join(temp_dir, name)), reverse=True)
        file_path = os.path.join(temp_dir, files[0])

        if os.path.getsize(file_path) < 1024:
            raise Exception("Downloaded file is too small")

        _set_job(job_id, phase="Checking audio/video streams...", pct=97)
        probe_cmd = [
            _ffmpeg_bin("ffprobe"), "-v", "error",
            "-show_entries", "stream=codec_type,codec_name",
            "-of", "csv=p=0",
            file_path,
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        has_video = "video" in probe_result.stdout
        has_audio = "audio" in probe_result.stdout

        final_ext = os.path.splitext(file_path)[1].lstrip(".") or ("m4a" if selected_type == "audio" else "mp4")
        final_filename = safe_title + (".mp4" if has_video and force_compat else "." + final_ext)

        if not (has_video and force_compat):
            return {
                "file_path": file_path,
                "temp_dir": temp_dir,
                "filename": final_filename,
                "content_type": mimetypes.guess_type(final_filename)[0] or "application/octet-stream",
            }

        _set_job(job_id, phase="Converting for Premiere Pro...", pct=98)
        final_path = os.path.join(temp_dir, "final-output.mp4")
        ffmpeg_cmd = [
            _ffmpeg_bin("ffmpeg"), "-y",
            "-i", file_path,
        ]
        if not has_audio:
            ffmpeg_cmd.extend([
                "-f", "lavfi",
                "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-shortest",
            ])
        ffmpeg_cmd.extend([
            "-map", "0:v:0",
            "-map", "0:a:0" if has_audio else "1:a:0",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "21",
            "-profile:v", "high",
            "-level:v", "4.1",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-ac", "2",
            "-movflags", "+faststart",
            final_path,
        ])
        subprocess.run(ffmpeg_cmd, check=True, timeout=7200, capture_output=True)

        if os.path.getsize(final_path) < 1024:
            raise Exception("Converted file is too small")

        return {
            "file_path": final_path,
            "temp_dir": temp_dir,
            "filename": final_filename,
            "content_type": "video/mp4",
        }
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _stream_ready_file(result):
    return _stream_file_response(
        result["file_path"],
        result["temp_dir"],
        result["filename"],
        result.get("content_type"),
    )


@download.route("/download/server-download")
def server_download():
    url = _normalize_media_url(request.args.get("url"))
    requested_format = request.args.get("format")
    selected_type = (request.args.get("type") or "video").lower()
    selected_has_audio = request.args.get("hasAudio") == "1"
    force_compat = request.args.get("compat") == "1"

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        result = _run_server_download(url, requested_format, selected_type, selected_has_audio, force_compat)
        return _stream_ready_file(result)
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Download timed out"}), 500
    except Exception as exc:
        return jsonify({"error": "Download failed", "details": str(exc)[-700:]}), 500


@download.route("/download/start-download", methods=["POST"])
def start_download_job():
    _cleanup_old_jobs()
    data = request.get_json(silent=True) or {}
    url = _normalize_media_url(data.get("url"))
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "queued",
        "phase": "Queued...",
        "pct": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
        "temp_dir": None,
    }
    with DOWNLOAD_JOBS_LOCK:
        DOWNLOAD_JOBS[job_id] = job

    def worker():
        try:
            _set_job(job_id, status="working", phase="Preparing download...", pct=1)
            result = _run_server_download(
                url,
                data.get("format"),
                (data.get("type") or "video").lower(),
                data.get("hasAudio") == "1",
                data.get("compat") == "1",
                job_id,
            )
            _set_job(
                job_id,
                status="ready",
                phase="Ready",
                pct=100,
                file_path=result["file_path"],
                temp_dir=result["temp_dir"],
                filename=result["filename"],
                content_type=result.get("content_type"),
                size=os.path.getsize(result["file_path"]),
            )
        except Exception as exc:
            _set_job(job_id, status="error", phase="Failed", pct=0, error=str(exc)[-700:])

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"jobId": job_id})


@download.route("/download/job-status/<job_id>")
def download_job_status(job_id):
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        safe_job = {
            "id": job["id"],
            "status": job.get("status"),
            "phase": job.get("phase"),
            "pct": job.get("pct", 0),
            "downloaded": job.get("downloaded", 0),
            "total": job.get("total", 0),
            "filename": job.get("filename"),
            "size": job.get("size", 0),
            "error": job.get("error"),
        }
    return jsonify(safe_job)


@download.route("/download/job-file/<job_id>")
def download_job_file(job_id):
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        if not job or job.get("status") != "ready":
            return jsonify({"error": "File is not ready"}), 404
        result = {
            "file_path": job.get("file_path"),
            "temp_dir": job.get("temp_dir"),
            "filename": job.get("filename"),
            "content_type": job.get("content_type"),
        }
        DOWNLOAD_JOBS.pop(job_id, None)

    if not result["file_path"] or not os.path.exists(result["file_path"]):
        return jsonify({"error": "File expired"}), 404

    return _stream_ready_file(result)


# ----------------------------
# Static files & Video ID handler (single catch-all)
# ----------------------------

@download.route("/download/<path:subpath>")
def download_static_or_video(subpath):
    """Serves static files OR handles video IDs like /download/YwfH_-6rJkQ"""
    static_dir = os.path.join(BASE_DIR, "download", "public")
    
    # First try to serve as static file
    file_path = os.path.join(static_dir, subpath)
    if os.path.abspath(file_path).startswith(os.path.abspath(static_dir)) and os.path.exists(file_path):
        response = send_from_directory(static_dir, subpath)
        response.headers["Cache-Control"] = "no-cache"
        return response
    
    # Not a static file - treat as video ID (must not have file extension)
    if '.' not in subpath and len(subpath) >= 6:
        try:
            html = open(os.path.join(static_dir, "index.html"), "r", encoding="utf-8").read()
            script = '<script>window.__VIDEO_ID__ = ' + json.dumps(subpath) + ';</script>'
            html = html.replace("</head>", script + "</head>")
            return Response(html, content_type="text/html; charset=utf-8")
        except Exception as e:
            return jsonify({"error": "Failed to load download page", "details": str(e)}), 500
    
    # Nothing found
    return ("Not found", 404)
