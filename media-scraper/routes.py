#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Media Scraper - Flask routes for FavoriteWeb integration.
Integrates the standalone media-scraper server into the main Flask app.
"""

import os
import sys
import json
import urllib.parse
import urllib.request
from flask import send_from_directory, request, jsonify, Response, stream_with_context

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Import the scrape function from server.py
sys.path.insert(0, BASE_DIR)
try:
    from server import scrape, fetch_page, resolve_direct_links, YTDLP_AVAILABLE
except ImportError:
    # Fallback: define minimal scrape if server.py can't be imported
    def scrape(url):
        return {'url': url, 'title': '', 'videos': [], 'audios': [], 'images': []}
    def resolve_direct_links(url):
        return None
    YTDLP_AVAILABLE = False

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


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

    @app.route("/media-scraper/api/resolve")
    def media_scraper_resolve():
        """Resolve direct playable/downloadable links for a URL using yt-dlp."""
        url = request.args.get("url", "").strip()
        if not url:
            return jsonify({"error": "URL is required"}), 400
        if not YTDLP_AVAILABLE:
            return jsonify({"error": "yt-dlp is not installed on this server", "ytdlp_available": False}), 501
        try:
            result = resolve_direct_links(url)
            if not result:
                return jsonify({"error": "Could not resolve direct links for this URL", "ytdlp_available": True}), 404
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e), "ytdlp_available": True}), 500

    @app.route("/media-scraper/api/download")
    def media_scraper_download():
        """Proxy a media URL so the server can download/stream it directly."""
        url = request.args.get("url", "").strip()
        if not url:
            return jsonify({"error": "URL is required"}), 400
        if not url.startswith(("http://", "https://")):
            return jsonify({"error": "Invalid URL"}), 400

        # Add Referer header (some CDNs like artlist.io require the page domain)
        parsed_url = urllib.parse.urlparse(url)
        # For artlist.io CDN, the Referer must be the artlist.io page domain
        if 'artlist.io' in parsed_url.netloc:
            referer = 'https://artlist.io/'
        else:
            referer = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Referer": referer,
        }

        # Try curl_cffi first (bypasses Cloudflare for artlist.io CDN etc.)
        try:
            from curl_cffi import requests as curl_requests
            downstream = curl_requests.get(url, headers=headers, impersonate='chrome', timeout=60, stream=True)
            if downstream.status_code == 200:
                def gen():
                    for chunk in downstream.iter_content(chunk_size=65536):
                        yield chunk
                ctype = downstream.headers.get("Content-Type", "application/octet-stream")
                clen = downstream.headers.get("Content-Length")
                hdrs = {"Content-Type": ctype}
                if clen:
                    hdrs["Content-Length"] = clen
                return Response(stream_with_context(gen()), headers=hdrs)
        except Exception:
            pass

        # Fallback to urllib
        try:
            req = urllib.request.Request(url, headers=headers)
            upstream = urllib.request.urlopen(req, timeout=30)

            def generate():
                while True:
                    chunk = upstream.read(65536)
                    if not chunk:
                        break
                    yield chunk

            content_type = upstream.headers.get("Content-Type", "application/octet-stream")
            content_length = upstream.headers.get("Content-Length")
            hdrs = {"Content-Type": content_type}
            if content_length:
                hdrs["Content-Length"] = content_length
            return Response(stream_with_context(generate()), headers=hdrs)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Serve static assets if any (e.g. css/js referenced by index.html)
    @app.route("/media-scraper/<path:filename>")
    def media_scraper_static(filename):
        return send_from_directory(BASE_DIR, filename)