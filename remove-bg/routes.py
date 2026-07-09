from flask import Response, jsonify, request, send_from_directory
from pathlib import Path
from PIL import Image, ImageFilter, ImageStat
import io
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
REMBG_TIMEOUT_SECONDS = 70
_REMBG_SESSION = None
_REMBG_EXECUTOR = ThreadPoolExecutor(max_workers=1)


def _load_image(data):
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.convert("RGBA")


def _save_png(image):
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out.getvalue()


def _rembg_remove(data):
    global _REMBG_SESSION
    from rembg import new_session, remove

    if _REMBG_SESSION is None:
        _REMBG_SESSION = new_session("u2net")
    result = remove(data, session=_REMBG_SESSION)
    return _save_png(_load_image(result))


def _auto_remove_with_timeout(data):
    future = _REMBG_EXECUTOR.submit(_rembg_remove, data)
    try:
        return future.result(timeout=REMBG_TIMEOUT_SECONDS), "rembg-u2net"
    except TimeoutError:
        return _fallback_remove(data), "fallback-timeout"


def _corner_background_color(image):
    width, height = image.size
    sample = max(4, min(width, height) // 28)
    boxes = [
        (0, 0, sample, sample),
        (width - sample, 0, width, sample),
        (0, height - sample, sample, height),
        (width - sample, height - sample, width, height),
    ]
    pixels = []
    for box in boxes:
        pixels.extend(list(image.crop(box).convert("RGB").getdata()))
    if not pixels:
        return (255, 255, 255)
    # Median is stable for flat product/photo backgrounds.
    channels = list(zip(*pixels))
    return tuple(sorted(channel)[len(channel) // 2] for channel in channels)


def _fallback_remove(data):
    image = _load_image(data)
    width, height = image.size
    bg = _corner_background_color(image)
    rgb = image.convert("RGB")
    alpha = Image.new("L", (width, height), 255)
    px = rgb.load()
    ax = alpha.load()
    tolerance = 46
    softness = 44
    for y in range(height):
        for x in range(width):
            r, g, b = px[x, y]
            dist = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5
            if dist <= tolerance:
                ax[x, y] = 0
            elif dist < tolerance + softness:
                ax[x, y] = int(255 * (dist - tolerance) / softness)
    alpha = alpha.filter(ImageFilter.GaussianBlur(radius=1.1))
    image.putalpha(alpha)
    return _save_png(image)


def init_routes(app):
    @app.route("/remove-bg")
    def remove_bg_page():
        return send_from_directory(BASE_DIR, "index.html")

    @app.route("/remove-bg/process", methods=["POST"])
    def remove_bg_process():
        uploaded = request.files.get("image")
        if not uploaded:
            return jsonify({"error": "image required"}), 400

        data = uploaded.read(MAX_UPLOAD_BYTES + 1)
        if not data:
            return jsonify({"error": "empty image"}), 400
        if len(data) > MAX_UPLOAD_BYTES:
            return jsonify({"error": "image too large"}), 413

        try:
            try:
                output, engine = _auto_remove_with_timeout(data)
            except Exception:
                output = _fallback_remove(data)
                engine = "fallback"
        except Exception as exc:
            return jsonify({"error": f"Could not process image: {exc}"}), 500

        response = Response(output, mimetype="image/png")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-FavoriteWeb-RemoveBg-Engine"] = engine
        return response