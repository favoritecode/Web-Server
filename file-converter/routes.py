from flask import after_this_request, jsonify, request, send_file, send_from_directory
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
import csv
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAX_CONVERT_BYTES = 1024 * 1024 * 1024

IMAGE_FORMATS = {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "gif", "ico", "pdf"}
VIDEO_FORMATS = {"mp4", "mkv", "webm", "mov", "avi", "flv", "m4v", "ogv"}
AUDIO_FORMATS = {"mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "wma"}
DOCUMENT_FORMATS = {"pdf", "docx", "doc", "odt", "rtf", "txt", "html", "md", "csv", "json"}
TEXT_DOCUMENTS = {"txt", "html", "md", "csv", "json", "rtf", "docx", "odt"}


def init_routes(app):
    @app.route("/file-converter")
    @app.route("/file-converter/")
    def file_converter_page():
        return send_from_directory(BASE_DIR, "index.html")

    @app.route("/file-converter/convert", methods=["POST"])
    def convert_file():
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        file = request.files["file"]
        if not file or not file.filename:
            return jsonify({"error": "No file selected"}), 400

        category = (request.form.get("category") or "").strip().lower()
        target = normalize_ext(request.form.get("target") or "")
        quality = (request.form.get("quality") or "balanced").strip().lower()
        source_ext = normalize_ext(Path(file.filename).suffix)
        if not category or not target:
            return jsonify({"error": "Choose converter type and output format"}), 400
        if not target_allowed(category, target):
            return jsonify({"error": "Unsupported output format for this converter"}), 400
        if request.content_length and request.content_length > MAX_CONVERT_BYTES:
            return jsonify({"error": "File is too large for online conversion"}), 413

        temp_dir = tempfile.mkdtemp(prefix="favoriteweb-convert-")
        try:
            safe_name = safe_filename(file.filename) or "input"
            input_path = Path(temp_dir) / safe_name
            file.save(input_path)
            output_path = dispatch_convert(category, input_path, source_ext, target, quality, request.form, temp_dir)
            if not output_path or not output_path.exists():
                return jsonify({"error": "Conversion failed"}), 500
            download_name = f"{Path(safe_name).stem or 'converted'}.{target}"

            @after_this_request
            def cleanup(response):
                shutil.rmtree(temp_dir, ignore_errors=True)
                return response

            return send_file(output_path, as_attachment=True, download_name=download_name)
        except ConverterError as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({"error": str(exc)}), exc.status
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({"error": "Conversion error: " + str(exc)}), 500


class ConverterError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def normalize_ext(value):
    return (value or "").strip().lower().lstrip(".")


def safe_filename(name):
    name = os.path.basename(name or "")
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" ._")


def target_allowed(category, target):
    return target in {
        "document": DOCUMENT_FORMATS,
        "image": IMAGE_FORMATS,
        "video": VIDEO_FORMATS | AUDIO_FORMATS,
        "audio": AUDIO_FORMATS,
    }.get(category, set())


def dispatch_convert(category, input_path, source_ext, target, quality, form, temp_dir):
    if category == "document":
        return convert_document(input_path, source_ext, target, temp_dir)
    if category == "image":
        return convert_image(input_path, target, form, temp_dir)
    if category == "video":
        return convert_video(input_path, target, quality, form, temp_dir)
    if category == "audio":
        return convert_audio(input_path, target, quality, form, temp_dir)
    raise ConverterError("Unknown converter type")


def convert_image(input_path, target, form, temp_dir):
    try:
        with Image.open(input_path) as img:
            img = ImageOps.exif_transpose(img)
            if target in {"jpg", "jpeg", "pdf"} and img.mode in {"RGBA", "P"}:
                bg = Image.new("RGB", img.size, "white")
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.getchannel("A") if img.mode == "RGBA" else None)
                img = bg
            elif target not in {"gif", "ico"}:
                img = img.convert("RGBA" if img.mode == "RGBA" and target == "png" else "RGB")
            width = int(form.get("width") or 0)
            height = int(form.get("height") or 0)
            if width > 0 or height > 0:
                if width <= 0:
                    width = round(img.width * (height / img.height))
                if height <= 0:
                    height = round(img.height * (width / img.width))
                img = img.resize((max(1, width), max(1, height)), Image.Resampling.LANCZOS)
            out_ext = "jpg" if target == "jpeg" else target
            output = Path(temp_dir) / f"converted.{out_ext}"
            save_kwargs = {}
            if target in {"jpg", "jpeg", "webp"}:
                save_kwargs["quality"] = int(form.get("imageQuality") or 92)
                save_kwargs["optimize"] = True
            img.save(output, format=("JPEG" if target in {"jpg", "jpeg"} else target.upper()), **save_kwargs)
            return output
    except UnidentifiedImageError:
        raise ConverterError("Could not read this image file")


def convert_video(input_path, target, quality, form, temp_dir):
    if target in AUDIO_FORMATS:
        return convert_audio(input_path, target, quality, form, temp_dir)
    ffmpeg = require_ffmpeg()
    output = Path(temp_dir) / f"converted.{target}"
    crf = {"small": "30", "balanced": "24", "high": "18"}.get(quality, "24")
    preset = "medium" if quality == "high" else "veryfast"
    args = [ffmpeg, "-y", "-i", str(input_path)]
    resolution = (form.get("resolution") or "source").strip().lower()
    if resolution in {"2160", "1440", "1080", "720", "480", "360"}:
        args += ["-vf", f"scale=-2:{resolution}"]
    if target == "webm":
        args += ["-c:v", "libvpx-vp9", "-crf", crf, "-b:v", "0", "-c:a", "libopus"]
    else:
        args += ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-c:a", "aac", "-b:a", audio_bitrate(quality)]
    args.append(str(output))
    run_command(args)
    return output


def convert_audio(input_path, target, quality, form, temp_dir):
    ffmpeg = require_ffmpeg()
    output = Path(temp_dir) / f"converted.{target}"
    bitrate = form.get("audioBitrate") or audio_bitrate(quality)
    args = [ffmpeg, "-y", "-i", str(input_path), "-vn"]
    if target == "mp3":
        args += ["-c:a", "libmp3lame", "-b:a", bitrate]
    elif target in {"m4a", "aac"}:
        args += ["-c:a", "aac", "-b:a", bitrate]
    elif target == "ogg":
        args += ["-c:a", "libvorbis", "-b:a", bitrate]
    elif target == "opus":
        args += ["-c:a", "libopus", "-b:a", bitrate]
    elif target == "flac":
        args += ["-c:a", "flac"]
    elif target == "wav":
        args += ["-c:a", "pcm_s16le"]
    else:
        args += ["-b:a", bitrate]
    args.append(str(output))
    run_command(args)
    return output


def convert_document(input_path, source_ext, target, temp_dir):
    if source_ext in TEXT_DOCUMENTS and target in {"txt", "html", "md", "csv", "json", "rtf", "doc", "docx", "odt", "pdf"}:
        return convert_text_document(input_path, source_ext, target, temp_dir)
    soffice = find_soffice()
    if not soffice:
        checked = "; ".join(SOFFICE_CHECKED_PATHS[:8])
        raise ConverterError("This document type needs LibreOffice on the server. Install LibreOffice or set SOFFICE_PATH/LIBREOFFICE_PATH. Checked: " + checked, 503)
    out_dir = Path(temp_dir) / "doc-out"
    out_dir.mkdir(exist_ok=True)
    target_filter = "html" if target == "html" else target
    run_command([soffice, "--headless", "--convert-to", target_filter, "--outdir", str(out_dir), str(input_path)], timeout=120)
    candidates = list(out_dir.glob(f"*.{target}"))
    if not candidates and target == "html":
        candidates = list(out_dir.glob("*.htm"))
    if not candidates:
        raise ConverterError("Document conversion failed")
    return candidates[0]


def read_document_text(input_path, source_ext):
    if source_ext == "docx":
        return read_docx_text(input_path)
    if source_ext == "odt":
        return read_odt_text(input_path)
    raw = input_path.read_text(encoding="utf-8", errors="ignore")
    if source_ext == "html":
        raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
        raw = re.sub(r"</p\s*>", "\n", raw, flags=re.I)
        raw = re.sub(r"<[^>]+>", "", raw)
        return html.unescape(raw)
    if source_ext == "json":
        try:
            return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except Exception:
            return raw
    if source_ext == "rtf":
        return strip_rtf(raw)
    return raw


def convert_text_document(input_path, source_ext, target, temp_dir):
    text = read_document_text(input_path, source_ext)
    output = Path(temp_dir) / f"converted.{target}"
    if target == "html":
        output.write_text("<!doctype html><meta charset=\"utf-8\"><pre>" + html.escape(text) + "</pre>", encoding="utf-8")
    elif target == "json":
        output.write_text(json.dumps({"text": text}, ensure_ascii=False, indent=2), encoding="utf-8")
    elif target == "csv":
        with output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            for line in text.splitlines():
                writer.writerow([line])
    elif target == "doc":
        output.write_text("<html><head><meta charset=\"utf-8\"></head><body><pre>" + html.escape(text) + "</pre></body></html>", encoding="utf-8")
    elif target == "docx":
        write_docx(output, text)
    elif target == "odt":
        write_odt(output, text)
    elif target == "pdf":
        write_text_pdf(output, text)
    elif target == "rtf":
        escaped = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\par ")
        output.write_text(r"{\rtf1\ansi " + escaped + "}", encoding="utf-8")
    else:
        output.write_text(text, encoding="utf-8")
    return output

def strip_rtf(value):
    value = re.sub(r"\\par[d]?", "\n", value)
    value = re.sub(r"\\'[0-9a-fA-F]{2}", "", value)
    value = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", value)
    value = value.replace("{", "").replace("}", "")
    return value.strip()


def read_docx_text(path):
    try:
        with zipfile.ZipFile(path) as docx:
            xml = docx.read("word/document.xml")
        root = ET.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        lines = []
        for para in root.findall(".//w:p", ns):
            parts = [node.text or "" for node in para.findall(".//w:t", ns)]
            if parts:
                lines.append("".join(parts))
        return "\n".join(lines)
    except Exception as exc:
        raise ConverterError("Could not read DOCX text: " + str(exc), 400)

def read_odt_text(path):
    try:
        with zipfile.ZipFile(path) as odt:
            xml = odt.read("content.xml")
        root = ET.fromstring(xml)
        ns = {"text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}
        lines = []
        for para in root.findall(".//text:p", ns):
            parts = [node.text or "" for node in para.iter()]
            line = "".join(parts).strip()
            if line:
                lines.append(line)
        return "\n".join(lines)
    except Exception as exc:
        raise ConverterError("Could not read ODT text: " + str(exc), 400)


def write_docx(path, text):
    paragraphs = "".join("<w:p><w:r><w:t>{}</w:t></w:r></w:p>".format(html.escape(line)) for line in (text.splitlines() or [""]))
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
    document = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{}<w:sectPr/></w:body></w:document>'''.format(paragraphs)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/document.xml", document)


def write_odt(path, text):
    paragraphs = "".join('<text:p text:style-name="Standard">{}</text:p>'.format(html.escape(line)) for line in (text.splitlines() or [""]))
    content = '''<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2"><office:body><office:text>{}</office:text></office:body></office:document-content>'''.format(paragraphs)
    styles = '''<?xml version="1.0" encoding="UTF-8"?><office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" office:version="1.2"/>'''
    manifest = '''<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/><manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/></manifest:manifest>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as odt:
        odt.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        odt.writestr("content.xml", content)
        odt.writestr("styles.xml", styles)
        odt.writestr("META-INF/manifest.xml", manifest)


def load_pdf_font(size=24):
    for candidate in (
        r"C:\Windows\Fonts\Nirmala.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def write_text_pdf(path, text):
    font = load_pdf_font()
    lines = []
    for line in text.splitlines() or [""]:
        lines.extend(textwrap.wrap(line, width=95) or [""])
    if not lines:
        lines = [""]
    pages = []
    for start in range(0, len(lines), 48):
        img = Image.new("RGB", (1240, 1754), "white")
        draw = ImageDraw.Draw(img)
        y = 80
        for line in lines[start:start + 48]:
            draw.text((80, y), line, fill="black", font=font)
            y += 32
        pages.append(img)
    first, rest = pages[0], pages[1:]
    first.save(path, "PDF", resolution=150.0, save_all=True, append_images=rest)


def audio_bitrate(quality):
    return {"small": "96k", "balanced": "160k", "high": "320k"}.get(quality, "160k")


def require_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    common = Path(r"C:\ffmpeg\bin\ffmpeg.exe")
    if common.exists():
        return str(common)
    raise ConverterError("FFmpeg is not installed on this server.", 503)


SOFFICE_CHECKED_PATHS = []


def find_soffice():
    global SOFFICE_CHECKED_PATHS
    candidates = []
    for key in ("SOFFICE_PATH", "LIBREOFFICE_PATH", "LIBREOFFICE_CMD"):
        value = (os.environ.get(key) or "").strip().strip('"')
        if value:
            candidates.append(value)
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for root in (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"D:\Program Files",
        r"E:\Program Files",
    ):
        if root:
            candidates.append(str(Path(root) / "LibreOffice" / "program" / "soffice.exe"))
    candidates.extend([
        r"C:\LibreOffice\program\soffice.exe",
        r"D:\LibreOffice\program\soffice.exe",
        r"E:\LibreOffice\program\soffice.exe",
    ])
    unique = []
    for item in candidates:
        if item and item not in unique:
            unique.append(item)
    SOFFICE_CHECKED_PATHS = unique
    for item in unique:
        if Path(item).exists():
            return item
    return None


def run_command(args, timeout=900):
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ConverterError("Conversion timed out")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "Conversion command failed"
        raise ConverterError(message[:240], 500)
