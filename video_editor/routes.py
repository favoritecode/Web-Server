import os
import sys
import re
import json
import time
import uuid
import shutil
import socket
import tempfile
import threading
import ipaddress
import subprocess
import zipfile
import urllib.parse
from flask import Blueprint, request, jsonify, Response, stream_with_context, send_from_directory
import requests as http_requests

try:
    from yt_dlp import YoutubeDL
except ImportError:
    YoutubeDL = None

video_editor_bp = Blueprint("video_editor", __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")

# Concurrency & Job State
EDITOR_JOBS = {}
EDITOR_JOBS_LOCK = threading.Lock()
JOB_TTL_SECONDS = 6 * 3600  # 6 hours

# Resource Limits
MAX_SOURCES = 10
MAX_SEGMENTS_PER_SOURCE = 50
MAX_TOTAL_SEGMENTS = 100
MAX_CONCURRENT_JOBS = 3
CONCURRENT_JOBS_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_JOBS)
MIN_FREE_DISK_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB free disk requirement
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024   # 2 GB max file size
MAX_DOWNLOAD_TIMEOUT = 120                      # 120 seconds per download
MAX_FFMPEG_TIMEOUT = 300                        # 300 seconds per ffmpeg operation
MAX_REDIRECTS = 5


# =====================================================================
# FFmpeg & ffprobe Binary Resolution
# =====================================================================

def get_ffmpeg_bin(name="ffmpeg"):
    """Locate the ffmpeg or ffprobe executable."""
    candidates = [
        os.path.join("C:\\", "ffmpeg", "bin", f"{name}.exe"),
        os.path.join("C:\\", "ffmpeg", "bin", name),
        shutil.which(name),
        shutil.which(f"{name}.exe"),
        name,
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return name


# =====================================================================
# SSRF & Outbound Request Protection
# =====================================================================

def is_safe_ip(ip_obj):
    """
    Validates an ipaddress object to strictly block private, loopback,
    link-local, multicast, reserved, or internal networks.
    """
    # If IPv4-mapped IPv6 (::ffff:127.0.0.1), unmap and check underlying IPv4
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
        ip_obj = ip_obj.ipv4_mapped

    if (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    ):
        return False

    # Block 6to4 addresses (2002::/16) which map IPv4 addresses into IPv6
    if isinstance(ip_obj, ipaddress.IPv6Address):
        if ip_obj in ipaddress.IPv6Network("2002::/16"):
            return False

    return True


def is_safe_url(url):
    """
    Validates URL scheme, credentials, and resolves destination IP to block
    private, loopback, link-local, multicast, or reserved networks.
    """
    if os.environ.get("FAVORITEWEB_TEST_MODE") == "1" and str(url).startswith("file://"):
        # Explicit test hook for synthetic test files
        return True, None

    try:
        parsed = urllib.parse.urlparse(url or "")
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return False, f"Unsupported URL scheme '{scheme}'. Only HTTP and HTTPS are permitted."

        # Block user:pass@host URL credential tricks
        if parsed.username or parsed.password:
            return False, "URLs with embedded credentials are not permitted."

        hostname = parsed.hostname
        if not hostname:
            return False, "Missing hostname in URL."

        # Block literal localhost / local domains explicitly
        lower_host = hostname.lower()
        if (
            lower_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
            or lower_host.endswith(".local")
            or lower_host.endswith(".internal")
            or lower_host.endswith(".localhost")
        ):
            return False, f"Access to '{hostname}' is blocked."

        # Resolve hostname to all addresses
        port = parsed.port or (443 if scheme == "https" else 80)
        addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        if not addr_info:
            return False, "Could not resolve hostname."

        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            if not is_safe_ip(ip_obj):
                return False, f"Access to IP address '{ip_str}' is blocked (private or restricted network)."

        return True, None
    except Exception as exc:
        return False, f"URL validation failed: {str(exc)}"


def safe_download_file(url, dest_path, timeout=MAX_DOWNLOAD_TIMEOUT):
    """
    Downloads a media file from a URL with step-by-step redirect inspection
    for SSRF protection, strict TLS verification, and streaming directly into dest_path.
    """
    curr_url = url
    session = http_requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FavoriteWeb-Editor/1.0",
        "Accept": "*/*",
    })

    for _ in range(MAX_REDIRECTS):
        safe, err = is_safe_url(curr_url)
        if not safe:
            raise ValueError(f"SSRF safety check failed: {err}")

        # Always enforce TLS certificate verification (verify=True)
        resp = session.get(curr_url, stream=True, allow_redirects=False, timeout=timeout, verify=True)
        if resp.status_code in (301, 302, 303, 307, 308):
            redirect_url = resp.headers.get("Location")
            if not redirect_url:
                raise ValueError("Redirect response missing Location header.")
            curr_url = urllib.parse.urljoin(curr_url, redirect_url)
            # Re-validate target immediately
            safe_redir, redir_err = is_safe_url(curr_url)
            if not safe_redir:
                raise ValueError(f"Redirect target blocked by SSRF policy: {redir_err}")
            continue

        resp.raise_for_status()

        downloaded_bytes = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > MAX_DOWNLOAD_BYTES:
                        raise ValueError(f"Download exceeded maximum permitted size ({MAX_DOWNLOAD_BYTES} bytes).")

        if downloaded_bytes == 0:
            raise ValueError("Downloaded file is empty (0 bytes).")
        return dest_path

    raise ValueError("Too many redirects encountered while downloading media.")


# =====================================================================
# Timestamp Parsing & Validation
# =====================================================================

def parse_timestamp(val):
    """
    Parses a timestamp input into float seconds.
    Accepts floats, ints, or string formats: 'SS', 'MM:SS', 'HH:MM:SS', 'HH:MM:SS.mmm'.
    """
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip()
        try:
            return float(val)
        except ValueError:
            pass
        parts = val.split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"Invalid timestamp value: '{val}'. Expected seconds or 'HH:MM:SS' format.")


def sanitize_filename(name, default="video"):
    """Sanitizes a file name for safe filesystem usage."""
    if not name:
        return default
    clean = re.sub(r'[\/\\:*?"<>|]', "_", str(name)).strip("._ ")
    clean = re.sub(r"\s+", "_", clean)
    return clean[:100] or default


def sanitize_stderr(stderr_str):
    """Sanitizes FFmpeg stderr to remove system paths and internal details."""
    if not stderr_str:
        return "Unknown processing error"
    lines = [line.strip() for line in stderr_str.splitlines() if line.strip()]
    meaningful = [
        line for line in lines
        if any(keyword in line.lower() for keyword in ("error", "invalid", "failed", "cannot", "unsupported"))
    ]
    raw_msg = meaningful[-1] if meaningful else (lines[-1] if lines else "FFmpeg process failed")
    # Mask absolute windows or unix paths
    cleaned = re.sub(r"[A-Za-z]:\\[\w\-\\\.]+", "[path]", raw_msg)
    cleaned = re.sub(r"/[\w\-/]+", "[path]", cleaned)
    return cleaned[:300]


# =====================================================================
# FFmpeg & ffprobe Operations
# =====================================================================

def probe_media(file_path):
    """Probes media duration and streams using ffprobe."""
    ffprobe = get_ffmpeg_bin("ffprobe")
    cmd = [
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height",
        "-of", "json",
        file_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=MAX_FFMPEG_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"Media probe failed: {sanitize_stderr(proc.stderr)}")

    data = json.loads(proc.stdout or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    duration = float(fmt.get("duration") or 0.0)
    size = int(fmt.get("size") or os.path.getsize(file_path))

    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    return {
        "duration": duration,
        "size": size,
        "has_video": has_video,
        "has_audio": has_audio,
    }


def trim_segment(input_path, output_path, start, end):
    """Trims a segment [start, end] accurately with FFmpeg re-encoding."""
    ffmpeg = get_ffmpeg_bin("ffmpeg")
    cmd = [
        ffmpeg, "-y",
        "-ss", f"{start:.3f}",
        "-to", f"{end:.3f}",
        "-i", input_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=MAX_FFMPEG_TIMEOUT)
    if proc.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"FFmpeg trim failed: {sanitize_stderr(proc.stderr)}")
    return output_path


def concatenate_clips(clip_paths, output_path, temp_dir):
    """Concatenates multiple MP4 clips into a single video."""
    if not clip_paths:
        raise ValueError("No video clips provided for concatenation.")
    if len(clip_paths) == 1:
        shutil.copy2(clip_paths[0], output_path)
        return output_path

    ffmpeg = get_ffmpeg_bin("ffmpeg")
    concat_list_file = os.path.join(temp_dir, f"concat_{uuid.uuid4().hex[:8]}.txt")
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            escaped = p.replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    cmd = [
        ffmpeg, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_file,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=MAX_FFMPEG_TIMEOUT)
    if proc.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"FFmpeg concat failed: {sanitize_stderr(proc.stderr)}")
    return output_path


def transcode_full(input_path, output_path):
    """Transcodes or remuxes a full input video to web-ready MP4."""
    ffmpeg = get_ffmpeg_bin("ffmpeg")
    cmd = [
        ffmpeg, "-y",
        "-i", input_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=MAX_FFMPEG_TIMEOUT)
    if proc.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"FFmpeg transcode failed: {sanitize_stderr(proc.stderr)}")
    return output_path


def package_zip(clip_entries, zip_path):
    """
    Packages individual video clips into a zip archive.
    clip_entries: list of (file_path, archive_name) tuples.
    """
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fpath, aname in clip_entries:
            zf.write(fpath, arcname=aname)

    if not os.path.exists(zip_path) or os.path.getsize(zip_path) == 0:
        raise RuntimeError("Failed to generate zip archive or zip archive is empty.")
    return zip_path


# =====================================================================
# Job State & Lifecycle Management
# =====================================================================

def _set_job(job_id, **updates):
    if not job_id:
        return
    with EDITOR_JOBS_LOCK:
        job = EDITOR_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = time.time()


def _get_job(job_id):
    with EDITOR_JOBS_LOCK:
        job = EDITOR_JOBS.get(job_id)
        if not job:
            return None
        return dict(job)


def _cleanup_old_jobs():
    """
    Concurrency-safe cleanup of old jobs and temporary directories.
    Jobs are strictly protected from removal while an active download is running.
    """
    now = time.time()
    to_delete = []

    with EDITOR_JOBS_LOCK:
        for job_id, job in list(EDITOR_JOBS.items()):
            active = job.get("active_downloads", 0)
            if active > 0:
                continue

            updated_at = job.get("updated_at", now)
            downloaded_at = job.get("downloaded_at")

            # Prune if expired by TTL or if already downloaded and held for 5 minutes
            if (now - updated_at > JOB_TTL_SECONDS) or (downloaded_at and now - downloaded_at > 300):
                to_delete.append((job_id, job.get("temp_dir")))
                EDITOR_JOBS.pop(job_id, None)

    for _, temp_dir in to_delete:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


# =====================================================================
# Media Extraction & Download Logic
# =====================================================================

def download_source_video(url, temp_dir, index=0):
    """
    Downloads source video to a file inside temp_dir using yt-dlp metadata inspection
    coupled with strict SSRF inspection and TLS certificate validation.
    """
    # Check if URL is a local file in test mode
    if os.environ.get("FAVORITEWEB_TEST_MODE") == "1" and str(url).startswith("file://"):
        local_path = url[7:]
        if os.name == "nt" and local_path.startswith("/"):
            local_path = local_path.lstrip("/")
        if os.path.exists(local_path):
            dest = os.path.join(temp_dir, f"source_{index}.mp4")
            shutil.copy2(local_path, dest)
            return dest

    safe, err = is_safe_url(url)
    if not safe:
        raise ValueError(f"SSRF validation failed for source URL: {err}")

    out_pattern = os.path.join(temp_dir, f"source_{index}_%(id)s.%(ext)s")

    # If yt-dlp is available, inspect metadata first
    if YoutubeDL is not None:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": False,  # Strict TLS certificate verification
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": out_pattern,
            "merge_output_format": "mp4",
            "socket_timeout": 30,
            "retries": 3,
            "noplaylist": True,
            "max_downloads": 1,
        }
        if os.path.exists(COOKIES_FILE):
            opts["cookiefile"] = COOKIES_FILE

        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                # Audit any direct media URL discovered by yt-dlp
                extracted_url = info.get("url")
                if extracted_url:
                    stream_safe, stream_err = is_safe_url(extracted_url)
                    if not stream_safe:
                        raise ValueError(f"Media stream target blocked by SSRF policy: {stream_err}")
                    # Download direct stream via our strict, redirect-inspected downloader
                    direct_dest = os.path.join(temp_dir, f"source_{index}.mp4")
                    return safe_download_file(extracted_url, direct_dest)

                # For fragmented or multi-stream formats where yt-dlp manages muxing
                ydl.download([url])

            matches = [
                os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
                if f.startswith(f"source_{index}_") and not f.endswith(".part")
            ]
            if matches and os.path.getsize(matches[0]) > 0:
                return matches[0]
        except Exception as exc:
            # Re-raise explicit SSRF violations immediately
            if "SSRF policy" in str(exc):
                raise
            # Otherwise fall back to direct HTTP stream download
            pass

    # Direct HTTP download with strict redirect inspection and TLS verification
    direct_dest = os.path.join(temp_dir, f"source_{index}.mp4")
    return safe_download_file(url, direct_dest)


# =====================================================================
# Background Worker Engine
# =====================================================================

def _editor_worker(job_id, sources, mode, export_individual, output_format):
    temp_dir = None
    acquired = CONCURRENT_JOBS_SEMAPHORE.acquire(timeout=600)
    if not acquired:
        _set_job(job_id, status="error", phase="Failed", pct=0, progress=0, error="Job timed out waiting for an available processing slot.")
        return

    try:
        with EDITOR_JOBS_LOCK:
            job = EDITOR_JOBS.get(job_id)
            if not job:
                return
            temp_dir = job.get("temp_dir")

        _set_job(job_id, status="working", phase="Downloading source media...", pct=10, progress=10)

        # 1. Download and probe all source videos
        downloaded_sources = []
        for i, src_info in enumerate(sources):
            url = src_info["url"]
            _set_job(job_id, phase=f"Downloading source {i+1} of {len(sources)}...", pct=10 + int(i * 20 / len(sources)))
            file_path = download_source_video(url, temp_dir, index=i)
            probe = probe_media(file_path)
            duration = probe.get("duration", 0.0)

            # Validate and clamp segments for this source
            raw_segments = src_info.get("segments") or []
            validated_segments = []

            if raw_segments:
                for seg in raw_segments:
                    start = parse_timestamp(seg.get("start"))
                    end = parse_timestamp(seg.get("end"))

                    if start is None or end is None:
                        raise ValueError(f"Segment requires both 'start' and 'end' timestamps: {seg}")
                    if start < 0:
                        raise ValueError(f"Segment start timestamp cannot be negative: {start}")
                    if end <= start:
                        raise ValueError(f"Segment end time ({end}s) must be greater than start time ({start}s)")
                    if end - start < 0.2:
                        raise ValueError(f"Segment duration ({end - start:.2f}s) is too short. Minimum duration is 0.2s.")

                    if duration > 0:
                        if start >= duration:
                            raise ValueError(f"Segment start ({start}s) is beyond video duration ({duration:.2f}s)")
                        if end > duration:
                            end = duration
                        if end - start < 0.2:
                            raise ValueError(f"Segment duration after video boundary clamping is too short ({end - start:.2f}s)")

                    validated_segments.append({
                        "start": start,
                        "end": end,
                        "label": seg.get("label") or seg.get("name") or f"clip_{len(validated_segments)+1}",
                    })

            downloaded_sources.append({
                "file_path": file_path,
                "duration": duration,
                "segments": validated_segments,
            })

        # 2. Execute Edit Plan
        _set_job(job_id, phase="Processing video edits...", pct=40, progress=40)

        all_clips = []  # List of (clip_path, label)
        for s_idx, src in enumerate(downloaded_sources):
            fpath = src["file_path"]
            segs = src["segments"]

            if segs:
                # Trimming specific segments
                for c_idx, seg in enumerate(segs):
                    clip_out = os.path.join(temp_dir, f"segment_{s_idx}_{c_idx}.mp4")
                    trim_segment(fpath, clip_out, seg["start"], seg["end"])
                    label = sanitize_filename(seg["label"], f"clip_{s_idx+1}_{c_idx+1}")
                    all_clips.append((clip_out, f"{label}.mp4"))
            else:
                # Full video source without split
                full_out = os.path.join(temp_dir, f"full_{s_idx}.mp4")
                transcode_full(fpath, full_out)
                all_clips.append((full_out, f"source_{s_idx+1}.mp4"))

        if not all_clips:
            raise RuntimeError("No valid video clips were produced.")

        # 3. Handle Output Mode: combined MP4, single MP4, or ZIP
        final_file = None
        final_filename = None
        content_type = "video/mp4"

        is_merge_mode = (mode == "merge") or (mode == "combined") or (not export_individual and len(all_clips) > 1)

        if is_merge_mode:
            _set_job(job_id, phase="Combining video clips...", pct=80, progress=80)
            combined_dest = os.path.join(temp_dir, "combined_export.mp4")
            clip_paths_only = [c[0] for c in all_clips]
            concatenate_clips(clip_paths_only, combined_dest, temp_dir)
            final_file = combined_dest
            final_filename = "combined_export.mp4"
            content_type = "video/mp4"
        else:
            if len(all_clips) == 1:
                final_file = all_clips[0][0]
                final_filename = all_clips[0][1]
                content_type = "video/mp4"
            else:
                _set_job(job_id, phase="Packaging zip archive...", pct=85, progress=85)
                zip_dest = os.path.join(temp_dir, "video_clips.zip")
                package_zip(all_clips, zip_dest)
                final_file = zip_dest
                final_filename = "video_clips.zip"
                content_type = "application/zip"

        if not os.path.exists(final_file) or os.path.getsize(final_file) == 0:
            raise RuntimeError("Final output file was not created or is empty.")

        file_size = os.path.getsize(final_file)
        _set_job(
            job_id,
            status="ready",
            phase="Ready",
            pct=100,
            progress=100,
            file_path=final_file,
            filename=final_filename,
            content_type=content_type,
            size=file_size,
            downloadUrl=f"/video-editor/job-file/{job_id}",
            error=None,
        )

    except Exception as exc:
        err_msg = sanitize_stderr(str(exc))
        _set_job(
            job_id,
            status="error",
            phase="Failed",
            pct=0,
            progress=0,
            error=err_msg,
        )
    finally:
        CONCURRENT_JOBS_SEMAPHORE.release()


def _create_editor_job(default_mode="export"):
    """Validates incoming payload and starts an asynchronous editor job."""
    _cleanup_old_jobs()

    # Reject non-JSON bodies or malformed payload types
    if request.content_length and not request.is_json:
        return jsonify({"error": "Malformed request. Expected application/json content-type."}), 400

    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return jsonify({"error": "Malformed payload. Request body must be a JSON object."}), 400

    # Disk space check
    try:
        temp_root = tempfile.gettempdir()
        free_bytes = shutil.disk_usage(temp_root).free
        if free_bytes < MIN_FREE_DISK_BYTES:
            return jsonify({"error": "Insufficient server disk space to process video job. Please try again later."}), 507
    except Exception:
        pass

    # Extract sources and segments with strict type checking
    raw_sources = data.get("sources")
    if raw_sources is None:
        raw_sources = data.get("videos")

    if raw_sources is not None and not isinstance(raw_sources, list):
        return jsonify({"error": "'sources' or 'videos' must be a JSON array."}), 400

    single_url = data.get("url") or data.get("videoUrl") or data.get("source")
    if single_url is not None and not isinstance(single_url, str):
        return jsonify({"error": "Source URL must be a string."}), 400

    top_segments = data.get("segments")
    if top_segments is not None and not isinstance(top_segments, list):
        return jsonify({"error": "'segments' must be a JSON array."}), 400

    normalized_sources = []
    if raw_sources:
        for item in raw_sources:
            if isinstance(item, str):
                normalized_sources.append({"url": item.strip(), "segments": []})
            elif isinstance(item, dict) and item.get("url"):
                item_segs = item.get("segments") or []
                if not isinstance(item_segs, list):
                    return jsonify({"error": "Item segments must be a JSON array."}), 400
                normalized_sources.append({
                    "url": str(item["url"]).strip(),
                    "segments": item_segs,
                })
            else:
                return jsonify({"error": "Each source item must be a URL string or an object containing 'url'."}), 400
    elif single_url:
        normalized_sources.append({
            "url": str(single_url).strip(),
            "segments": top_segments or [],
        })

    if not normalized_sources:
        return jsonify({"error": "No source video URL provided."}), 400

    # Resource Limit: Source Count Check
    if len(normalized_sources) > MAX_SOURCES:
        return jsonify({"error": f"Too many video sources ({len(normalized_sources)}). Maximum permitted is {MAX_SOURCES}."}), 400

    # Resource Limit: Segment Count Check
    total_segments = 0
    for src in normalized_sources:
        src_segs = src.get("segments") or []
        if len(src_segs) > MAX_SEGMENTS_PER_SOURCE:
            return jsonify({"error": f"Too many segments for a single source ({len(src_segs)}). Maximum is {MAX_SEGMENTS_PER_SOURCE}."}), 400
        total_segments += len(src_segs)

    if total_segments > MAX_TOTAL_SEGMENTS:
        return jsonify({"error": f"Too many total segments ({total_segments}). Maximum permitted is {MAX_TOTAL_SEGMENTS}."}), 400

    # Validate URLs before queuing
    for src in normalized_sources:
        safe, err = is_safe_url(src["url"])
        if not safe:
            return jsonify({"error": f"Invalid source URL: {err}"}), 400

    # Validate segments upfront
    for src in normalized_sources:
        for seg in (src.get("segments") or []):
            if not isinstance(seg, dict):
                return jsonify({"error": "Each segment must be a JSON object with 'start' and 'end' timestamps."}), 400
            try:
                start = parse_timestamp(seg.get("start"))
                end = parse_timestamp(seg.get("end"))
                if start is None or end is None:
                    return jsonify({"error": "Each segment must include both 'start' and 'end' timestamps."}), 400
                if start < 0:
                    return jsonify({"error": f"Start timestamp cannot be negative: {start}"}), 400
                if end <= start:
                    return jsonify({"error": f"Segment end time ({end}) must be greater than start time ({start})."}), 400
                if end - start < 0.2:
                    return jsonify({"error": f"Segment duration ({end - start:.2f}s) is too short. Minimum duration is 0.2s."}), 400
            except ValueError as val_err:
                return jsonify({"error": str(val_err)}), 400

    mode = (data.get("mode") or default_mode).lower()
    raw_export_individual = data.get("exportIndividual")
    if raw_export_individual is None:
        raw_export_individual = data.get("export_individual")

    if raw_export_individual is not None:
        export_individual = raw_export_individual in (True, "true", "1", 1)
    else:
        export_individual = (mode == "split" or mode == "individual")

    output_format = data.get("format") or "mp4"

    job_id = uuid.uuid4().hex
    temp_dir = tempfile.mkdtemp(prefix="favoriteweb-editor-")

    job = {
        "id": job_id,
        "jobId": job_id,
        "status": "queued",
        "phase": "Queued...",
        "pct": 0,
        "progress": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
        "temp_dir": temp_dir,
        "file_path": None,
        "filename": None,
        "content_type": None,
        "size": 0,
        "active_downloads": 0,
        "downloaded_at": None,
        "error": None,
    }

    with EDITOR_JOBS_LOCK:
        EDITOR_JOBS[job_id] = job

    worker_thread = threading.Thread(
        target=_editor_worker,
        args=(job_id, normalized_sources, mode, export_individual, output_format),
        daemon=True,
    )
    worker_thread.start()

    return jsonify({
        "id": job_id,
        "jobId": job_id,
        "status": "queued",
    }), 200


# =====================================================================
# REST Endpoints
# =====================================================================

@video_editor_bp.route("/video-editor", methods=["GET"])
@video_editor_bp.route("/video-editor/", methods=["GET"])
@video_editor_bp.route("/social-video-editor", methods=["GET"])
@video_editor_bp.route("/social-video-editor/", methods=["GET"])
def video_editor_index():
    editor_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(editor_dir, "index.html")


@video_editor_bp.route("/video-editor/info", methods=["GET", "POST"])
def video_editor_info():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        url = data.get("url") or ""
    else:
        url = request.args.get("url") or ""

    url = str(url).strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    safe, err = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {err}"}), 400

    from download.route import _base_ydl_opts
    opts = _base_ydl_opts({"skip_download": True}, url)

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        return jsonify({"error": f"Failed to inspect media: {str(exc)}"}), 502

    title = info.get("title", "Video")
    duration = info.get("duration") or 0
    thumbnail = info.get("thumbnail") or ""
    uploader = info.get("uploader") or info.get("channel") or ""
    webpage_url = info.get("webpage_url") or url

    if duration:
        hrs = int(duration // 3600)
        mins = int((duration % 3600) // 60)
        secs = int(duration % 60)
        duration_fmt = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"
    else:
        duration_fmt = "00:00"

    video_id = info.get("id")
    is_yt = bool(info.get("extractor", "").lower().startswith("youtube"))

    return jsonify({
        "url": webpage_url,
        "title": title,
        "duration": duration,
        "duration_formatted": duration_fmt,
        "thumbnail": thumbnail,
        "uploader": uploader,
        "video_id": video_id if is_yt else None,
        "is_youtube": is_yt,
    })


@video_editor_bp.route("/video-editor/split", methods=["POST"])
def video_editor_split():
    """Splits a video into segments (defaults to individual clips / ZIP)."""
    return _create_editor_job(default_mode="split")


@video_editor_bp.route("/video-editor/merge", methods=["POST"])
def video_editor_merge():
    """Merges multiple videos or segments into a single combined output."""
    return _create_editor_job(default_mode="merge")


@video_editor_bp.route("/video-editor/export", methods=["POST"])
def video_editor_export():
    """Unified video editor export supporting full, split, merge, and zip."""
    return _create_editor_job(default_mode="export")


@video_editor_bp.route("/video-editor/job-status/<job_id>", methods=["GET"])
def video_editor_job_status(job_id):
    """Retrieves current processing status of an editor job."""
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify({
        "id": job["id"],
        "jobId": job["jobId"],
        "status": job["status"],
        "phase": job.get("phase"),
        "pct": job.get("pct", 0),
        "progress": job.get("progress", 0),
        "filename": job.get("filename"),
        "size": job.get("size", 0),
        "downloadUrl": f"/video-editor/job-file/{job_id}" if job["status"] == "ready" else None,
        "error": job.get("error"),
    })


@video_editor_bp.route("/video-editor/job-file/<job_id>", methods=["GET"])
def video_editor_job_file(job_id):
    """
    Streams the finished output file.
    Atomically verifies readiness and output path, and acquires an active download
    reference under EDITOR_JOBS_LOCK before releasing, guaranteeing retention
    cleanup never deletes the file while in-flight.
    """
    with EDITOR_JOBS_LOCK:
        job = EDITOR_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404

        if job.get("status") != "ready":
            return jsonify({
                "error": "File is not ready",
                "status": job.get("status"),
                "details": job.get("error"),
            }), 400

        file_path = job.get("file_path")
        if not file_path or not os.path.exists(file_path):
            return jsonify({"error": "File expired or missing"}), 404

        file_size = os.path.getsize(file_path)
        filename = job.get("filename") or "download.mp4"
        content_type = job.get("content_type") or "video/mp4"

        # Atomically increment active-download reference
        job["active_downloads"] = job.get("active_downloads", 0) + 1
        job["updated_at"] = time.time()

    def generate():
        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            with EDITOR_JOBS_LOCK:
                curr_job = EDITOR_JOBS.get(job_id)
                if curr_job:
                    active = curr_job.get("active_downloads", 1) - 1
                    curr_job["active_downloads"] = max(0, active)
                    curr_job["downloaded_at"] = time.time()
                    curr_job["updated_at"] = time.time()

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(file_size),
        "Cache-Control": "no-store, no-cache, must-revalidate",
    }

    return Response(
        stream_with_context(generate()),
        mimetype=content_type,
        headers=headers,
    )
