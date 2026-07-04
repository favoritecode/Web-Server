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

IMAGE_FORMATS = {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "gif", "ico", "pdf", "eps", "psd", "ai"}
VIDEO_FORMATS = {"mp4", "mkv", "webm", "mov", "avi", "flv", "m4v", "ogv"}
AUDIO_FORMATS = {"mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "wma"}
DOCUMENT_FORMATS = {"pdf", "eps", "psd", "ai", "docx", "doc", "odt", "rtf", "txt", "html", "md", "csv", "json", "xlsx"}
TEXT_DOCUMENTS = {"txt", "html", "md", "csv", "json", "rtf", "docx", "odt", "xlsx"}


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
            output_ext = output_path.suffix.lstrip(".") or target
            download_name = f"{Path(safe_name).stem or 'converted'}.{output_ext}"

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
        return convert_image(input_path, source_ext, target, form, temp_dir)
    if category == "video":
        return convert_video(input_path, target, quality, form, temp_dir)
    if category == "audio":
        return convert_audio(input_path, target, quality, form, temp_dir)
    raise ConverterError("Unknown converter type")


def convert_image(input_path, source_ext, target, form, temp_dir):
    design_formats = {"pdf", "eps", "psd", "ai"}
    if source_ext in design_formats or target in {"eps", "psd", "ai"}:
        return convert_design_image(input_path, source_ext, target, form, temp_dir)
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


def convert_design_image(input_path, source_ext, target, form, temp_dir):
    if source_ext == "pdf" and target == "eps":
        return convert_pdf_to_eps(input_path, temp_dir)

    output = Path(temp_dir) / f"converted.{target}"
    if source_ext not in {"pdf", "eps", "psd", "ai"} and target == "eps":
        try:
            with Image.open(input_path) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.save(output, format="EPS")
                return output
        except UnidentifiedImageError:
            raise ConverterError("Could not read this image file")
    magick = find_magick()
    if not magick:
        raise ConverterError("PDF/EPS/PSD/AI conversion needs ImageMagick and Ghostscript on the server. Install them to enable these formats.", 503)
    density = str(int(form.get("density") or 220))
    input_spec = str(input_path)
    if source_ext == "pdf":
        input_spec += "[0]"
    args = [magick, "-density", density, input_spec, "-background", "white", "-alpha", "remove"]
    if target == "jpg":
        args += ["-quality", str(int(form.get("imageQuality") or 92))]
    if target == "ai":
        # Modern Illustrator files are PDF-compatible; ImageMagick writes PDF data and we keep the requested extension.
        args += ["pdf:" + str(output)]
    else:
        args.append(str(output))
    run_command(args, timeout=180)
    if not output.exists():
        raise ConverterError("Design file conversion failed")
    return output


def convert_pdf_to_eps(input_path, temp_dir):
    page_count = pdf_page_count(input_path) or 1
    gs = find_ghostscript()
    if gs:
        if page_count <= 1:
            output = Path(temp_dir) / "converted.eps"
            run_command([
                gs,
                "-dNOPAUSE",
                "-dBATCH",
                "-dSAFER",
                "-sDEVICE=eps2write",
                f"-sOutputFile={output}",
                str(input_path),
            ], timeout=180)
            if not output.exists():
                raise ConverterError("PDF to EPS conversion failed")
            return output

        package_dir = Path(temp_dir) / "pdf-eps-package"
        eps_dir = package_dir / "eps-pages"
        eps_dir.mkdir(parents=True, exist_ok=True)
        eps_files = []
        for page in range(1, page_count + 1):
            output = eps_dir / f"page-{page:03d}.eps"
            run_command([
                gs,
                "-dNOPAUSE",
                "-dBATCH",
                "-dSAFER",
                "-sDEVICE=eps2write",
                f"-dFirstPage={page}",
                f"-dLastPage={page}",
                f"-sOutputFile={output}",
                str(input_path),
            ], timeout=180)
            if output.exists():
                eps_files.append(output)
        if not eps_files:
            raise ConverterError("PDF to EPS conversion failed")

        combined_ps = package_dir / "combined-pages.ps"
        run_command([
            gs,
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            "-sDEVICE=ps2write",
            f"-sOutputFile={combined_ps}",
            str(input_path),
        ], timeout=180)
        readme = package_dir / "README.txt"
        readme.write_text(
            "EPS is a single-page format in most software. This package keeps every PDF page as its own EPS file.\n"
            "Use eps-pages/page-001.eps, page-002.eps, etc. The combined-pages.ps file is included for apps that can open multi-page PostScript.\n",
            encoding="utf-8",
        )
        zip_output = Path(temp_dir) / "converted-eps-pages.zip"
        with zipfile.ZipFile(zip_output, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(package_dir.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(package_dir))
        return zip_output

    if page_count > 1:
        raise ConverterError("Multi-page PDF to EPS needs Ghostscript on the server.", 503)

    magick = find_magick()
    if not magick:
        raise ConverterError("PDF to EPS needs Ghostscript or ImageMagick on the server.", 503)
    output = Path(temp_dir) / "converted.eps"
    run_command([magick, "-density", "220", f"{input_path}[0]", "-background", "white", "-alpha", "remove", str(output)], timeout=180)
    if not output.exists():
        raise ConverterError("PDF to EPS conversion failed")
    return output


def pdf_page_count(path):
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
            reader = module.PdfReader(str(path))
            return len(reader.pages)
        except Exception:
            continue
    return 0

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
        args += ["-c:v", "libvpx-vp9", "-crf", crf, "-b:v", "0", "-c:a", "libopus", "-b:a", audio_bitrate(quality)]
    elif target == "avi":
        args += ["-c:v", "mpeg4", "-q:v", {"small": "7", "balanced": "5", "high": "3"}.get(quality, "5"), "-c:a", "libmp3lame", "-b:a", audio_bitrate(quality)]
    elif target == "flv":
        args += ["-c:v", "flv", "-c:a", "libmp3lame", "-b:a", audio_bitrate(quality)]
    elif target == "ogv":
        args += ["-c:v", "libtheora", "-q:v", {"small": "5", "balanced": "7", "high": "9"}.get(quality, "7"), "-c:a", "libvorbis", "-b:a", audio_bitrate(quality)]
    else:
        args += ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-c:a", "aac", "-b:a", audio_bitrate(quality)]
        if target in {"mp4", "m4v", "mov"}:
            args += ["-movflags", "+faststart"]
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
    elif target == "wma":
        args += ["-c:a", "wmav2", "-b:a", bitrate]
    else:
        args += ["-c:a", "aac", "-b:a", bitrate]
    args.append(str(output))
    run_command(args)
    return output


def convert_document(input_path, source_ext, target, temp_dir):
    design_document_formats = {"pdf", "eps", "psd", "ai"}
    if source_ext in design_document_formats or target in design_document_formats - {"pdf"}:
        if source_ext in design_document_formats and target in design_document_formats:
            return convert_design_image(input_path, source_ext, target, {}, temp_dir)
        raise ConverterError("PDF/EPS/PSD/AI document conversion only works between those design formats.", 422)

    text_targets = {"txt", "html", "md", "csv", "json", "rtf", "doc", "docx", "odt", "pdf", "xlsx"}
    if source_ext in TEXT_DOCUMENTS and target in text_targets:
        return convert_text_document(input_path, source_ext, target, temp_dir)
    if source_ext == "pdf" and target in text_targets:
        text = extract_pdf_text(input_path, temp_dir)
        if text:
            text_path = Path(temp_dir) / "pdf-text.txt"
            text_path.write_text(text, encoding="utf-8")
            return convert_text_document(text_path, "txt", target, temp_dir)
        raise ConverterError("PDF to editable document needs selectable text. Scanned/image PDFs need OCR first, then convert the OCR text.", 422)
    soffice = find_soffice()
    if not soffice:
        checked = "; ".join(SOFFICE_CHECKED_PATHS[:8])
        raise ConverterError("This document type needs LibreOffice on the server. Install LibreOffice or set SOFFICE_PATH/LIBREOFFICE_PATH. Checked: " + checked, 503)
    out_dir = Path(temp_dir) / "doc-out"
    out_dir.mkdir(exist_ok=True)
    target_filter = libreoffice_filter(target)
    try:
        run_command([soffice, "--headless", "--convert-to", target_filter, "--outdir", str(out_dir), str(input_path)], timeout=120)
    except ConverterError as exc:
        if "no export filter" in str(exc).lower():
            raise ConverterError(f"LibreOffice cannot export {source_ext.upper()} to {target.upper()} on this server. Try PDF/TXT/HTML or convert through an editable document format first.", 422)
        raise
    candidates = list(out_dir.glob(f"*.{target}"))
    if not candidates and target == "html":
        candidates = list(out_dir.glob("*.htm"))
    if not candidates:
        raise ConverterError("Document conversion failed")
    return candidates[0]


def libreoffice_filter(target):
    return {
        "pdf": "pdf:writer_pdf_Export",
        "docx": "docx:Office Open XML Text",
        "doc": "doc:MS Word 97",
        "odt": "odt:writer8",
        "rtf": "rtf:Rich Text Format",
        "html": "html:HTML (StarWriter)",
        "txt": "txt:Text",
        "xlsx": "xlsx:Calc MS Excel 2007 XML",
    }.get(target, target)


def extract_pdf_text(input_path, temp_dir):
    text = extract_pdf_text_with_python(input_path)
    if text:
        return text
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        output = Path(temp_dir) / "pdf-text.txt"
        try:
            run_command([pdftotext, "-layout", "-enc", "UTF-8", str(input_path), str(output)], timeout=120)
            if output.exists():
                return output.read_text(encoding="utf-8", errors="ignore").strip()
        except ConverterError:
            pass
    return ""


def extract_pdf_text_with_python(input_path):
    reader_cls = None
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
            reader_cls = getattr(module, "PdfReader")
            break
        except Exception:
            continue
    if not reader_cls:
        return ""
    try:
        reader = reader_cls(str(input_path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n\n".join(page.strip() for page in pages if page.strip()).strip()
    except Exception:
        return ""


def read_document_text(input_path, source_ext):
    if source_ext == "docx":
        return read_docx_text(input_path)
    if source_ext == "odt":
        return read_odt_text(input_path)
    if source_ext == "xlsx":
        return read_xlsx_text(input_path)
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
    elif target == "xlsx":
        write_xlsx(output, text)
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


def read_xlsx_text(path):
    try:
        with zipfile.ZipFile(path) as xlsx:
            shared = []
            if "xl/sharedStrings.xml" in xlsx.namelist():
                shared_root = ET.fromstring(xlsx.read("xl/sharedStrings.xml"))
                ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for item in shared_root.findall(".//a:si", ns):
                    shared.append("".join(node.text or "" for node in item.findall(".//a:t", ns)))
            sheet_names = sorted(name for name in xlsx.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", name))
            rows = []
            ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for sheet_name in sheet_names:
                root = ET.fromstring(xlsx.read(sheet_name))
                for row in root.findall(".//a:row", ns):
                    values = []
                    for cell in row.findall("a:c", ns):
                        cell_type = cell.get("t")
                        value = ""
                        if cell_type == "inlineStr":
                            value = "".join(node.text or "" for node in cell.findall(".//a:t", ns))
                        else:
                            value_node = cell.find("a:v", ns)
                            value = value_node.text if value_node is not None else ""
                            if cell_type == "s" and value.isdigit() and int(value) < len(shared):
                                value = shared[int(value)]
                        values.append(value)
                    if values:
                        rows.append(",".join(values))
            return "\n".join(rows)
    except Exception as exc:
        raise ConverterError("Could not read XLSX text: " + str(exc), 400)


def write_docx(path, text):
    paragraphs = "".join("<w:p><w:r><w:t>{}</w:t></w:r></w:p>".format(html.escape(line)) for line in (text.splitlines() or [""]))
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
    document = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{}<w:sectPr/></w:body></w:document>'''.format(paragraphs)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/document.xml", document)


def write_xlsx(path, text):
    rows = []
    for line in text.splitlines() or [""]:
        if "," in line:
            rows.append([part.strip() for part in next(csv.reader([line]))])
        else:
            rows.append([line])
    sheet_rows = []
    for r_index, row in enumerate(rows, start=1):
        cells = []
        for c_index, value in enumerate(row, start=1):
            col = chr(ord("A") + min(c_index - 1, 25))
            cells.append(f'<c r="{col}{r_index}" t="inlineStr"><is><t>{html.escape(value)}</t></is></c>')
        sheet_rows.append(f'<row r="{r_index}">{"".join(cells)}</row>')
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'''
    workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'''
    sheet = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as xlsx:
        xlsx.writestr("[Content_Types].xml", content_types)
        xlsx.writestr("_rels/.rels", rels)
        xlsx.writestr("xl/workbook.xml", workbook)
        xlsx.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        xlsx.writestr("xl/worksheets/sheet1.xml", sheet)


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


def find_ghostscript():
    for name in ("gswin64c", "gswin32c", "gs"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        r"C:\Program Files\gs\gs10.07.1\bin\gswin64c.exe",
        r"C:\Program Files\gs\gs10.05.1\bin\gswin64c.exe",
        r"C:\Program Files\gs\gs10.04.0\bin\gswin64c.exe",
        r"C:\Program Files\gs\gs10.03.1\bin\gswin64c.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def find_magick():
    for name in ("magick", "magick.exe", "convert"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe",
        r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe",
        r"C:\Program Files\ImageMagick-7.0.11-Q16-HDRI\magick.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


SOFFICE_CHECKED_PATHS = []


def normalize_candidate_path(value):
    value = (value or "").strip().strip('"').replace("/", "\\")
    if value and Path(value).is_dir():
        value = str(Path(value) / "soffice.exe")
    return value


def find_soffice():
    global SOFFICE_CHECKED_PATHS
    candidates = []
    for key in ("SOFFICE_PATH", "LIBREOFFICE_PATH", "LIBREOFFICE_CMD"):
        value = normalize_candidate_path(os.environ.get(key))
        if value:
            candidates.append(value)
    for root in (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"D:\Program Files",
        r"E:\Program Files",
    ):
        if root:
            program_dir = Path(root) / "LibreOffice" / "program"
            candidates.append(str(program_dir / "soffice.exe"))
            candidates.append(str(program_dir / "soffice.com"))
    candidates.extend([
        r"C:\LibreOffice\program\soffice.exe",
        r"D:\LibreOffice\program\soffice.exe",
        r"E:\LibreOffice\program\soffice.exe",
    ])
    for name in ("soffice.exe", "soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    unique = []
    seen = set()
    for item in candidates:
        item = normalize_candidate_path(item)
        key = item.lower()
        if item and key not in seen:
            unique.append(item)
            seen.add(key)
    SOFFICE_CHECKED_PATHS = unique
    for item in unique:
        if Path(item).is_file():
            return item
    return None


def run_command(args, timeout=900):
    env = os.environ.copy()
    if args and str(args[0]).lower().endswith(("soffice.exe", "soffice.com")):
        program_dir = str(Path(args[0]).parent)
        env["PATH"] = program_dir + os.pathsep + env.get("PATH", "")
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise ConverterError("Conversion timed out")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "Conversion command failed"
        raise ConverterError(message[:240], 500)

