from flask import send_from_directory, request, jsonify
import os
import re
import tempfile

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
MAX_OCR_BYTES = 25 * 1024 * 1024
DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

if os.environ.get("TESSERACT_CMD"):
    pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
elif os.path.exists(DEFAULT_TESSERACT):
    pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESSERACT


def clean_text(value):
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def score_text(value):
    text = clean_text(value)
    if not text:
        return 0
    useful = re.findall(r"[A-Za-z0-9\u0980-\u09FF]", text)
    return len(useful) + min(len(text), 2000) * 0.03


def safe_lang(requested):
    requested = (requested or "eng").strip().lower()
    requested = "eng+ben" if requested == "both" else requested
    requested = requested if requested in {"eng", "ben", "eng+ben"} else "eng"
    warnings = []
    try:
        installed = set(pytesseract.get_languages(config=""))
    except Exception:
        installed = set()
    if installed:
        parts = [part for part in requested.split("+") if part in installed]
        missing = [part for part in requested.split("+") if part not in installed]
        if missing:
            warnings.append("Missing Tesseract language data: " + ", ".join(missing))
        if parts:
            return "+".join(parts), warnings
        warnings.append("Selected language data is unavailable, using English.")
    return "eng", warnings


def image_variants(image):
    image = ImageOps.exif_transpose(image).convert("RGB")
    max_side = max(image.size)
    if max_side > 2600:
        scale = 2600 / float(max_side)
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)

    variants = [image]
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.7)
    gray = ImageEnhance.Sharpness(gray).enhance(1.35)

    if max(gray.size) < 1800:
        scale = min(2.0, 1800 / float(max(gray.size)))
        if scale > 1.05:
            gray = gray.resize((int(gray.width * scale), int(gray.height * scale)), Image.Resampling.LANCZOS)

    variants.append(gray)
    variants.append(gray.filter(ImageFilter.SHARPEN))
    threshold = gray.point(lambda px: 255 if px > 170 else 0)
    variants.append(threshold)
    return variants


def run_ocr(image, lang):
    configs = (
        "--oem 3 --psm 6 -c preserve_interword_spaces=1",
        "--oem 3 --psm 4 -c preserve_interword_spaces=1",
        "--oem 3 --psm 11",
    )
    best = ""
    best_score = -1
    for variant in image_variants(image):
        for config in configs:
            try:
                text = pytesseract.image_to_string(variant, lang=lang, config=config, timeout=45)
            except RuntimeError:
                continue
            current_score = score_text(text)
            if current_score > best_score:
                best = text
                best_score = current_score
    return clean_text(best)


def init_routes(app):

    @app.route("/ocr")
    @app.route("/ocr/")
    def ocr_page():
        return send_from_directory(BASE_DIR, "index.html")

    @app.route("/ocr/extract", methods=["POST"])
    def ocr_extract():
        if "image" not in request.files:
            return jsonify({"error": "No image uploaded"}), 400

        file = request.files["image"]
        if not file or not file.filename:
            return jsonify({"error": "No image selected"}), 400

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify({"error": "Unsupported image type"}), 400

        content_length = request.content_length or 0
        if content_length > MAX_OCR_BYTES:
            return jsonify({"error": "Image is too large. Maximum size is 25 MB."}), 413

        lang, warnings = safe_lang(request.form.get("lang", "eng"))

        try:
            with tempfile.NamedTemporaryFile(prefix="favoriteweb-ocr-", suffix=ext, delete=False) as tmp:
                temp_path = tmp.name
                file.save(temp_path)
            try:
                with Image.open(temp_path) as image:
                    text = run_ocr(image, lang)
            finally:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        except UnidentifiedImageError:
            return jsonify({"error": "Could not read this image file"}), 400
        except pytesseract.TesseractNotFoundError:
            return jsonify({"error": "Tesseract OCR is not installed on this server."}), 503
        except Exception as exc:
            return jsonify({"error": "OCR Error: " + str(exc)}), 500

        return jsonify({
            "text": text,
            "lang": request.form.get("lang", "eng"),
            "engine_lang": lang,
            "warnings": warnings,
            "preprocessed": True,
        })
