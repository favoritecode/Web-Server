#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Media Scraper - Flask routes for FavoriteWeb integration.
Integrates the standalone media-scraper server into the main Flask app.
"""

import os
import sys
import json
from flask import send_from_directory, request, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Import the scrape function from server.py
sys.path.insert(0, BASE_DIR)
try:
    from server import scrape, fetch_page
except ImportError:
    # Fallback: define minimal scrape if server.py can't be imported
    def scrape(url):
        return {'url': url, 'title': '', 'videos': [], 'audios': [], 'images': []}


def init_routes(app):
    """Register media-scraper routes on the Flask app."""

    @app.route("/media-scraper")
    @app.route("/media-scraper/")
    def media_scraper_index():
        return send_from_directory(BASE_DIR, "index.html")

    @app.route("/media-scraper/api/scrape")
    def media_scraper_api():
        url = request.args.get("url", "").strip()
        if not url:
            return jsonify({"error": "URL is required"}), 400
        try:
            result = scrape(url)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Serve static assets if any (e.g. css/js referenced by index.html)
    @app.route("/media-scraper/<path:filename>")
    def media_scraper_static(filename):
        return send_from_directory(BASE_DIR, filename)