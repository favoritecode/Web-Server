import os
import sys
import unittest
import json
import io
import time
import subprocess
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

TEST_TOKEN = "test_fwt_secret_token_12345_media_relay"
os.environ["FWT_MEDIA_RELAY_TOKEN"] = TEST_TOKEN
os.environ["FAVORITEWEB_TEST_MODE"] = "1"

from app import app
from download import route as download_route


class TestPartialStreamRelay(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = app.test_client()
        self.auth_headers = {"Authorization": f"Bearer {TEST_TOKEN}"}

    def test_01_capabilities_unauthorized(self):
        # No header
        resp = self.client.get("/download/partial-capabilities")
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertEqual(data.get("error"), "UNAUTHORIZED")

        # Wrong token
        resp = self.client.get(
            "/download/partial-capabilities",
            headers={"Authorization": "Bearer invalid_secret_token"}
        )
        self.assertEqual(resp.status_code, 401)

    def test_02_capabilities_authorized(self):
        resp = self.client.get(
            "/download/partial-capabilities",
            headers=self.auth_headers
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("version"), 1)
        self.assertEqual(data.get("max_chunk_bytes"), 524288)
        self.assertEqual(data.get("single_range"), True)
        self.assertEqual(data.get("full_download_fallback"), False)
        self.assertEqual(resp.headers.get("Cache-Control"), "private, no-store")

    def test_03_partial_stream_unauthorized(self):
        resp = self.client.get("/download/partial-stream?url=https://www.youtube.com/watch?v=ZTQjnm_iiRE")
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertEqual(data.get("error"), "UNAUTHORIZED")

    def test_04_partial_stream_missing_url(self):
        resp = self.client.get(
            "/download/partial-stream",
            headers=self.auth_headers
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("error"), "MISSING_URL")

    def test_05_partial_stream_ssrf_blocked(self):
        blocked_urls = [
            "http://127.0.0.1/video.mp4",
            "http://localhost:8010/secret",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/internal.mp4",
            "http://192.168.1.1/router.mp4",
        ]
        for b_url in blocked_urls:
            with patch.dict(os.environ, {"FAVORITEWEB_TEST_MODE": "0"}):
                resp = self.client.get(
                    f"/download/partial-stream?url={b_url}",
                    headers={**self.auth_headers, "Range": "bytes=0-1023"}
                )
                self.assertIn(resp.status_code, (403, 502), f"URL {b_url} was not blocked: {resp.status_code}")

    def test_06_range_validation(self):
        dummy_entry = {
            "stream_url": "https://example.com/test.mp4",
            "http_headers": {},
            "total_size": 1000000,
            "source_id": "a" * 64,
            "content_type": "video/mp4",
            "ydl_opts": {},
            "expires_at": time.time() + 900,
            "last_accessed": time.time(),
            "cache_key": "https://example.com/test.mp4::",
        }
        with patch("download.route._resolve_partial_source", return_value=(dummy_entry, None)):
            # Missing Range
            resp = self.client.get(
                "/download/partial-stream?url=https://example.com/test.mp4",
                headers=self.auth_headers
            )
            self.assertEqual(resp.status_code, 416)
            self.assertEqual(resp.get_json().get("error"), "RANGE_REQUIRED")

            # Malformed Range
            resp = self.client.get(
                "/download/partial-stream?url=https://example.com/test.mp4",
                headers={**self.auth_headers, "Range": "bytes=abc"}
            )
            self.assertEqual(resp.status_code, 416)
            self.assertEqual(resp.get_json().get("error"), "INVALID_RANGE")

            # Multiple ranges
            resp = self.client.get(
                "/download/partial-stream?url=https://example.com/test.mp4",
                headers={**self.auth_headers, "Range": "bytes=0-100,200-300"}
            )
            self.assertEqual(resp.status_code, 416)
            self.assertEqual(resp.get_json().get("error"), "MULTIPLE_RANGES_UNSUPPORTED")

            # Inverted range
            resp = self.client.get(
                "/download/partial-stream?url=https://example.com/test.mp4",
                headers={**self.auth_headers, "Range": "bytes=500-200"}
            )
            self.assertEqual(resp.status_code, 416)
            self.assertEqual(resp.get_json().get("error"), "INVALID_RANGE")

            # Range start >= total_size
            resp = self.client.get(
                "/download/partial-stream?url=https://example.com/test.mp4",
                headers={**self.auth_headers, "Range": "bytes=1500000-"}
            )
            self.assertEqual(resp.status_code, 416)
            self.assertEqual(resp.get_json().get("error"), "RANGE_NOT_SATISFIABLE")
            self.assertEqual(resp.headers.get("Content-Range"), "bytes */1000000")

    def test_07_source_changed_409(self):
        dummy_entry = {
            "stream_url": "https://example.com/test.mp4",
            "http_headers": {},
            "total_size": 1000000,
            "source_id": "a" * 64,
            "content_type": "video/mp4",
            "ydl_opts": {},
            "expires_at": time.time() + 900,
            "last_accessed": time.time(),
            "cache_key": "https://example.com/test.mp4::",
        }
        with patch("download.route._resolve_partial_source", return_value=(dummy_entry, None)):
            resp = self.client.get(
                f"/download/partial-stream?url=https://example.com/test.mp4&source_id={'b'*64}",
                headers={**self.auth_headers, "Range": "bytes=0-1023"}
            )
            self.assertEqual(resp.status_code, 409)
            data = resp.get_json()
            self.assertEqual(data.get("error"), "SOURCE_CHANGED")
            self.assertEqual(data.get("current_source_id"), "a" * 64)

    def test_08_upstream_full_content_rejected_422(self):
        dummy_entry = {
            "stream_url": "https://example.com/test.mp4",
            "http_headers": {},
            "total_size": 1000000,
            "source_id": "a" * 64,
            "content_type": "video/mp4",
            "ydl_opts": {},
            "expires_at": time.time() + 900,
            "last_accessed": time.time(),
            "cache_key": "https://example.com/test.mp4::",
        }
        mock_res = MagicMock()
        mock_res.status = 200  # Upstream ignored Range and sent HTTP 200

        with patch("download.route._resolve_partial_source", return_value=(dummy_entry, None)), \
             patch("download.route.YoutubeDL.urlopen", return_value=mock_res):
            resp = self.client.get(
                "/download/partial-stream?url=https://example.com/test.mp4",
                headers={**self.auth_headers, "Range": "bytes=0-1023"}
            )
            self.assertEqual(resp.status_code, 422)
            data = resp.get_json()
            self.assertEqual(data.get("error"), "RANGE_UNSUPPORTED")
            mock_res.close.assert_called_once()

    def test_09_real_partial_range_fetch(self):
        test_url = "https://www.youtube.com/watch?v=ZTQjnm_iiRE"

        # Request chunk 0: bytes 0-524287 (512 KiB)
        resp = self.client.get(
            f"/download/partial-stream?url={test_url}&format_id=18",
            headers={**self.auth_headers, "Range": "bytes=0-524287"}
        )
        if resp.status_code != 206:
            print("TEST_09 FAILURE BODY:", resp.get_json())
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp.headers.get("Content-Range"), "bytes 0-524287/634611013")
        self.assertEqual(resp.headers.get("Content-Length"), "524288")
        self.assertEqual(resp.headers.get("Accept-Ranges"), "bytes")
        self.assertEqual(resp.headers.get("Cache-Control"), "private, no-store")
        source_id = resp.headers.get("X-Media-Source-ID")
        self.assertTrue(source_id and len(source_id) == 64)

        data = resp.data
        self.assertEqual(len(data), 524288)
        # Verify MP4 container: bytes 4-8 should be 'ftyp'
        self.assertEqual(data[4:8], b"ftyp")

        # Request chunk 1: bytes 524288-1048575 (512 KiB)
        resp2 = self.client.get(
            f"/download/partial-stream?url={test_url}&format_id=18&source_id={source_id}",
            headers={**self.auth_headers, "Range": "bytes=524288-1048575"}
        )
        self.assertEqual(resp2.status_code, 206)
        self.assertEqual(resp2.headers.get("Content-Range"), "bytes 524288-1048575/634611013")
        self.assertEqual(len(resp2.data), 524288)

        # Request oversized chunk: bytes 0-10000000 (10 MB requested -> must be clamped to 512 KiB)
        resp3 = self.client.get(
            f"/download/partial-stream?url={test_url}&format_id=18",
            headers={**self.auth_headers, "Range": "bytes=0-10000000"}
        )
        self.assertEqual(resp3.status_code, 206)
        self.assertEqual(resp3.headers.get("Content-Range"), "bytes 0-524287/634611013")
        self.assertEqual(len(resp3.data), 524288)

    def test_10_existing_downloader_route_regression(self):
        # Ensure /download/api still responds properly
        resp = self.client.get("/download/api")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"error": "No URL"})


if __name__ == "__main__":
    unittest.main()
