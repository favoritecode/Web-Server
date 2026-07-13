from flask import jsonify, request, send_file, send_from_directory
from pathlib import Path
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid

BASE_DIR = Path(__file__).resolve().parent
JOBS_DIR = BASE_DIR / "jobs"
MAX_UPLOAD_BYTES = int(os.environ.get("MEDIA_TRANSCRIBE_MAX_MB", "1024")) * 1024 * 1024
JOB_TTL_SECONDS = int(os.environ.get("MEDIA_TRANSCRIBE_JOB_TTL", "86400"))
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".m4v", ".ogv"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma"}
_ALLOWED_DOWNLOADS = {"captions.srt", "captioned.mp4"}
_FAST_WHISPER_MODEL = None
_WHISPER_MODEL = None


class MediaTranscribeError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def init_routes(app):
    JOBS_DIR.mkdir(exist_ok=True)

    @app.route("/media-transcribe")
    @app.route("/media-transcribe/")
    def media_transcribe_page():
        return send_from_directory(BASE_DIR, "index.html")

    @app.route("/media-transcribe/api/transcribe", methods=["POST"])
    def media_transcribe_upload():
        cleanup_old_jobs()
        if request.content_length and request.content_length > MAX_UPLOAD_BYTES:
            return jsonify({"error": "File is too large for transcription."}), 413
        if "media" not in request.files:
            return jsonify({"error": "No media file uploaded."}), 400
        upload = request.files["media"]
        if not upload or not upload.filename:
            return jsonify({"error": "No file selected."}), 400
        original_ext = Path(upload.filename).suffix.lower()
        if original_ext not in VIDEO_EXTS and original_ext not in AUDIO_EXTS:
            return jsonify({"error": "Upload an audio or video file."}), 400
        language = normalize_language(request.form.get("language"))
        job_id = uuid.uuid4().hex
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        safe_name = safe_filename(upload.filename) or f"input{original_ext or '.media'}"
        input_path = job_dir / safe_name
        audio_path = job_dir / "audio.wav"
        try:
            upload.save(input_path)
            extract_audio(input_path, audio_path)
            segments, detected_language = run_transcription(audio_path, language)
            if not segments:
                raise MediaTranscribeError("No speech was detected in this media.", 422)
            duration = get_duration(input_path) or max((seg["end"] for seg in segments), default=0)
            (job_dir / "captions.srt").write_text(segments_to_srt(segments), encoding="utf-8")
            job = {"job_id": job_id, "created_at": time.time(), "input": str(input_path), "input_name": safe_name, "is_video": original_ext in VIDEO_EXTS, "duration": duration, "language": detected_language or language or "auto", "segments": segments}
            save_job(job_dir, job)
            return jsonify({"jobId": job_id, "filename": safe_name, "duration": duration, "language": job["language"], "segments": segments, "srtUrl": f"/media-transcribe/api/download/{job_id}/captions.srt"})
        except MediaTranscribeError as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({"error": str(exc)}), exc.status
        except Exception as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({"error": "Transcription failed: " + str(exc)}), 500

    @app.route("/media-transcribe/api/export-srt", methods=["POST"])
    def media_transcribe_export_srt():
        data = request.get_json(silent=True) or {}
        segments = normalize_segments(data.get("segments") or [])
        if not segments:
            return jsonify({"error": "No captions to export."}), 400
        temp_path = JOBS_DIR / f"srt-{uuid.uuid4().hex}.srt"
        temp_path.write_text(segments_to_srt(segments), encoding="utf-8")
        return send_file(temp_path, as_attachment=True, download_name="captions.srt", mimetype="application/x-subrip")

    @app.route("/media-transcribe/api/export-video", methods=["POST"])
    def media_transcribe_export_video():
        data = request.get_json(silent=True) or {}
        job_id = safe_job_id(data.get("jobId"))
        if not job_id:
            return jsonify({"error": "Missing job id."}), 400
        job_dir = JOBS_DIR / job_id
        job = load_job(job_dir)
        if not job:
            return jsonify({"error": "This transcription job expired. Please upload again."}), 404
        segments = normalize_segments(data.get("segments") or job.get("segments") or [])
        if not segments:
            return jsonify({"error": "No captions to export."}), 400
        input_path = Path(job.get("input", ""))
        if not input_path.exists():
            return jsonify({"error": "Original media file is missing. Please upload again."}), 404
        ass_path = job_dir / "captions.ass"
        out_path = job_dir / "captioned.mp4"
        ass_path.write_text(segments_to_ass(segments, normalize_style(data.get("style") or {})), encoding="utf-8-sig")
        try:
            burn_captions(input_path, ass_path, out_path, bool(job.get("is_video")))
        except MediaTranscribeError as exc:
            return jsonify({"error": str(exc)}), exc.status
        job["segments"] = segments
        save_job(job_dir, job)
        return jsonify({"downloadUrl": f"/media-transcribe/api/download/{job_id}/captioned.mp4"})

    @app.route("/media-transcribe/api/download/<job_id>/<filename>")
    def media_transcribe_download(job_id, filename):
        job_id = safe_job_id(job_id)
        filename = os.path.basename(filename or "")
        if not job_id or filename not in _ALLOWED_DOWNLOADS:
            return jsonify({"error": "Invalid download."}), 404
        path = JOBS_DIR / job_id / filename
        if not path.exists():
            return jsonify({"error": "File not found or expired."}), 404
        mimetype = "application/x-subrip" if filename.endswith(".srt") else "video/mp4"
        return send_file(path, as_attachment=True, download_name=filename, mimetype=mimetype)

def cleanup_old_jobs():
    now = time.time()
    JOBS_DIR.mkdir(exist_ok=True)
    for path in JOBS_DIR.iterdir():
        try:
            if path.is_dir() and now - path.stat().st_mtime > JOB_TTL_SECONDS:
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file() and now - path.stat().st_mtime > 3600:
                path.unlink(missing_ok=True)
        except Exception:
            pass


def normalize_language(value):
    value = (value or "auto").strip().lower()
    if value in {"bn", "bangla", "bengali"}:
        return "bn"
    if value in {"en", "english"}:
        return "en"
    return None


def safe_filename(name):
    name = os.path.basename(name or "")
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" ._")[:150]


def safe_job_id(value):
    value = str(value or "").strip()
    return value if re.fullmatch(r"[a-fA-F0-9]{32}", value) else ""


def save_job(job_dir, job):
    (job_dir / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def load_job(job_dir):
    path = job_dir / "job.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def require_binary(name, env_var=None):
    configured = os.environ.get(env_var or "") if env_var else ""
    if configured and Path(configured).exists():
        return configured
    found = shutil.which(name)
    if found:
        return found
    raise MediaTranscribeError(f"{name} was not found on this server.", 500)


def run_command(args, timeout=1800):
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise MediaTranscribeError("Media processing took too long. Try a shorter file.", 504)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["Unknown ffmpeg error"]
        raise MediaTranscribeError(detail[0], 500)
    return proc


def extract_audio(input_path, audio_path):
    ffmpeg = require_binary("ffmpeg", "FFMPEG_PATH")
    run_command([ffmpeg, "-y", "-i", str(input_path), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(audio_path)])


def get_duration(path):
    try:
        ffprobe = require_binary("ffprobe", "FFPROBE_PATH")
        proc = run_command([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], timeout=60)
        return float((proc.stdout or "0").strip() or 0)
    except Exception:
        return 0


def run_transcription(audio_path, language):
    engine = os.environ.get("MEDIA_TRANSCRIBE_ENGINE", "faster-whisper").strip().lower()
    errors = []
    if engine in {"faster-whisper", "auto"}:
        try:
            return transcribe_with_faster_whisper(audio_path, language)
        except ImportError:
            errors.append("faster-whisper is not installed")
        except Exception as exc:
            errors.append(str(exc))
            if engine != "auto":
                raise
    try:
        return transcribe_with_openai_whisper(audio_path, language)
    except ImportError:
        errors.append("openai-whisper is not installed")
    except Exception as exc:
        errors.append(str(exc))
    raise MediaTranscribeError("Transcription engine is not ready. Install faster-whisper on this server. " + "; ".join(errors), 500)


def transcribe_with_faster_whisper(audio_path, language):
    global _FAST_WHISPER_MODEL
    from faster_whisper import WhisperModel
    model_name = os.environ.get("MEDIA_TRANSCRIBE_MODEL", "small")
    device = os.environ.get("MEDIA_TRANSCRIBE_DEVICE", "cpu")
    compute_type = os.environ.get("MEDIA_TRANSCRIBE_COMPUTE", "int8")
    if _FAST_WHISPER_MODEL is None:
        _FAST_WHISPER_MODEL = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments_iter, info = _FAST_WHISPER_MODEL.transcribe(str(audio_path), language=language, word_timestamps=True, vad_filter=True, beam_size=5)
    segments = []
    for idx, seg in enumerate(segments_iter, start=1):
        text = clean_caption_text(seg.text)
        if not text:
            continue
        words = []
        for word in getattr(seg, "words", None) or []:
            word_text = clean_caption_text(getattr(word, "word", ""))
            if word_text:
                words.append({"start": round(float(word.start or seg.start), 3), "end": round(float(word.end or seg.end), 3), "word": word_text})
        if not words:
            words = distribute_words(text, float(seg.start), float(seg.end))
        segments.append({"id": idx, "start": round(float(seg.start), 3), "end": round(float(seg.end), 3), "text": text, "words": words})
    return segments, getattr(info, "language", None) or language or "auto"


def transcribe_with_openai_whisper(audio_path, language):
    global _WHISPER_MODEL
    import whisper
    model_name = os.environ.get("MEDIA_TRANSCRIBE_MODEL", "small")
    if _WHISPER_MODEL is None:
        _WHISPER_MODEL = whisper.load_model(model_name)
    result = _WHISPER_MODEL.transcribe(str(audio_path), language=language)
    segments = []
    for idx, seg in enumerate(result.get("segments") or [], start=1):
        text = clean_caption_text(seg.get("text", ""))
        if not text:
            continue
        start = float(seg.get("start") or 0)
        end = float(seg.get("end") or start + 1)
        segments.append({"id": idx, "start": round(start, 3), "end": round(end, 3), "text": text, "words": distribute_words(text, start, end)})
    return segments, result.get("language") or language or "auto"

def clean_caption_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def distribute_words(text, start, end):
    tokens = [w for w in re.split(r"\s+", text) if w]
    if not tokens:
        return []
    duration = max(0.08, (end - start) / len(tokens))
    words = []
    for i, token in enumerate(tokens):
        ws = start + duration * i
        we = start + duration * (i + 1)
        words.append({"start": round(ws, 3), "end": round(min(we, end), 3), "word": token})
    return words


def normalize_segments(raw_segments):
    segments = []
    for idx, item in enumerate(raw_segments, start=1):
        try:
            start = max(0, float(item.get("start", 0)))
            end = max(start + 0.08, float(item.get("end", start + 1)))
        except Exception:
            continue
        text = clean_caption_text(item.get("text", ""))
        if not text:
            continue
        words = []
        for word in item.get("words") or []:
            wt = clean_caption_text(word.get("word", ""))
            if not wt:
                continue
            try:
                ws = float(word.get("start", start))
                we = float(word.get("end", end))
            except Exception:
                ws, we = start, end
            words.append({"start": round(max(start, ws), 3), "end": round(min(end, max(ws + 0.04, we)), 3), "word": wt, "selected": bool(word.get("selected"))})
        segments.append({"id": idx, "start": round(start, 3), "end": round(end, 3), "text": text[:600], "words": words or distribute_words(text, start, end)})
    return segments[:1200]


def format_srt_time(seconds):
    seconds = max(0, float(seconds or 0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - math.floor(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments):
    parts = []
    for idx, seg in enumerate(normalize_segments(segments), start=1):
        parts.append(str(idx))
        parts.append(f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}")
        parts.append(seg["text"])
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def normalize_style(style):
    def color(value, fallback):
        value = str(value or "").strip()
        return value if re.fullmatch(r"#[0-9A-Fa-f]{6}", value) else fallback
    preset = str(style.get("preset") or "neon").lower()
    animation = str(style.get("animation") or "fade").lower()
    position = str(style.get("position") or "bottom").lower()
    return {
        "preset": preset if preset in {"classic", "neon", "highlight", "karaoke", "lower"} else "neon",
        "font": re.sub(r"[^A-Za-z0-9 _-]+", "", str(style.get("font") or "Arial"))[:40] or "Arial",
        "fontSize": clamp_int(style.get("fontSize"), 24, 96, 48),
        "textColor": color(style.get("textColor"), "#FFFFFF"),
        "accentColor": color(style.get("accentColor"), "#38BDF8"),
        "outlineColor": color(style.get("outlineColor"), "#0F172A"),
        "position": position if position in {"bottom", "center", "top"} else "bottom",
        "animation": animation if animation in {"none", "fade", "pop", "karaoke"} else "fade",
    }


def clamp_int(value, low, high, fallback):
    try:
        return min(high, max(low, int(value)))
    except Exception:
        return fallback


def ass_color(hex_color, alpha="00"):
    hex_color = hex_color.lstrip("#")
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"&H{alpha}{b}{g}{r}"


def format_ass_time(seconds):
    seconds = max(0, float(seconds or 0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - math.floor(seconds)) * 100))
    if centis >= 100:
        secs += 1
        centis -= 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def escape_ass_text(text):
    return clean_caption_text(text).replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def segments_to_ass(segments, style):
    style = normalize_style(style)
    alignment = {"bottom": 2, "center": 5, "top": 8}[style["position"]]
    header = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['font']},{style['fontSize']},{ass_color(style['textColor'])},{ass_color(style['accentColor'])},{ass_color(style['outlineColor'])},&H66000000,-1,0,0,0,100,100,0,0,1,4,1,{alignment},80,80,{70 if style['position'] == 'bottom' else 35},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for seg in normalize_segments(segments):
        override = ""
        if style["animation"] == "fade":
            override += r"{\fad(140,140)}"
        elif style["animation"] == "pop":
            override += r"{\fad(80,120)\t(0,180,\fscx112\fscy112)\t(180,320,\fscx100\fscy100)}"
        if style["preset"] == "lower":
            override += r"{\bord3\shad0}"
        elif style["preset"] == "highlight":
            override += r"{\bord5}"
        text = karaoke_text(seg, style) if style["animation"] == "karaoke" or style["preset"] == "karaoke" else escape_ass_text(seg["text"])
        lines.append(f"Dialogue: 0,{format_ass_time(seg['start'])},{format_ass_time(seg['end'])},Default,,0,0,0,,{override}{text}\n")
    return "".join(lines)


def karaoke_text(seg, style):
    pieces = []
    for word in seg.get("words") or distribute_words(seg["text"], seg["start"], seg["end"]):
        duration = max(1, int(round((float(word.get("end", seg["end"])) - float(word.get("start", seg["start"]))) * 100)))
        word_text = escape_ass_text(word.get("word", ""))
        if word.get("selected"):
            pieces.append(r"{\c" + ass_color(style["accentColor"]) + "}" + word_text + r"{\r} ")
        else:
            pieces.append(f"{{\\k{duration}}}{word_text} ")
    return "".join(pieces).strip() or escape_ass_text(seg["text"])


def ffmpeg_filter_path(path):
    value = str(path.resolve()).replace("\\", "/")
    value = value.replace(":", r"\:").replace("'", r"\'")
    return value


def burn_captions(input_path, ass_path, out_path, is_video):
    ffmpeg = require_binary("ffmpeg", "FFMPEG_PATH")
    filter_arg = f"subtitles='{ffmpeg_filter_path(ass_path)}'"
    if is_video:
        args = [ffmpeg, "-y", "-i", str(input_path), "-vf", filter_arg, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", str(out_path)]
    else:
        args = [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=#0f172a:s=1280x720:r=30", "-i", str(input_path), "-shortest", "-vf", filter_arg, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", str(out_path)]
    run_command(args, timeout=3600)
    if not out_path.exists() or out_path.stat().st_size < 1024:
        raise MediaTranscribeError("Captioned video export failed.", 500)
