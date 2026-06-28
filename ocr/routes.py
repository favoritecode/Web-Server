from flask import send_from_directory, request, jsonify
import pytesseract
from PIL import Image
import os
import re

# tesseract path (Windows)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def init_routes(app):

    # OCR PAGE
    @app.route("/ocr")
    @app.route("/ocr/")
    def ocr_page():
        return send_from_directory("ocr", "index.html")


    # OCR API - supports language parameter
    @app.route("/ocr/extract", methods=["POST"])
    def ocr_extract():

        try:

            if "image" not in request.files:
                return jsonify({"error": "No image uploaded"}), 400

            file = request.files["image"]
            lang = request.form.get("lang", "eng")  # default English

            upload_folder = "ocr/uploads"

            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)

            # Sanitize filename
            safe_name = re.sub(r'[^\w\.\-]', '_', file.filename)
            filepath = os.path.join(upload_folder, safe_name)

            file.save(filepath)

            # OCR process with language support
            img = Image.open(filepath)
            
            # Language config: eng=English, ben=Bangla, eng+ben=both
            if lang == "ben":
                text = pytesseract.image_to_string(img, lang="ben")
            elif lang == "both":
                text = pytesseract.image_to_string(img, lang="eng+ben")
            else:
                text = pytesseract.image_to_string(img, lang="eng")

            # Clean up uploaded file
            try:
                os.remove(filepath)
            except:
                pass

            return jsonify({"text": text, "lang": lang})

        except Exception as e:
            return jsonify({"error": "OCR Error: " + str(e)}), 500
