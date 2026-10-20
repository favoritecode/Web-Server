import os
import sys
import json
import time
import shutil
import tempfile
import zipfile
import subprocess
import unittest
from unittest.mock import patch, MagicMock

# Ensure E:\web is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Set test mode environment variable for synthetic test media
os.environ["FAVORITEWEB_TEST_MODE"] = "1"

from app import app
from video_editor.routes import (
    is_safe_url,
    is_safe_ip,
    safe_download_file,
    parse_timestamp,
    get_ffmpeg_bin,
    probe_media,
    EDITOR_JOBS,
    EDITOR_JOBS_LOCK,
    _cleanup_old_jobs,
    MAX_SOURCES,
    MAX_TOTAL_SEGMENTS,
)
import ipaddress


class SocialVideoEditorTestSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.temp_dir = tempfile.mkdtemp(prefix="video-editor-test-")
        cls.ffmpeg = get_ffmpeg_bin("ffmpeg")
        cls.ffprobe = get_ffmpeg_bin("ffprobe")

        # Generate synthetic test clip 1 (5.0 seconds)
        cls.clip1_path = os.path.join(cls.temp_dir, "clip1.mp4")
        subprocess.run([
            cls.ffmpeg, "-y",
            "-f", "lavfi", "-i", "testsrc=duration=5:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=5",
            "-c:v", "libx264", "-c:a", "aac",
            cls.clip1_path
        ], capture_output=True, check=True)

        # Generate synthetic test clip 2 (3.0 seconds)
        cls.clip2_path = os.path.join(cls.temp_dir, "clip2.mp4")
        subprocess.run([
            cls.ffmpeg, "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=600:duration=3",
            "-c:v", "libx264", "-c:a", "aac",
            cls.clip2_path
        ], capture_output=True, check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    # -----------------------------------------------------------------
    # 1. SSRF & URL Validation Tests
    # -----------------------------------------------------------------

    def test_01_ssrf_ip_and_range_blocking(self):
        # Test individual IP addresses
        blocked_ips = [
            "127.0.0.1",
            "127.1.2.3",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "0.0.0.0",
            "::1",
            "::ffff:127.0.0.1",
            "::ffff:169.254.169.254",
            "::ffff:192.168.1.1",
            "fe80::1",
            "fc00::1",
            "2002:c0a8:0101::",  # 6to4 mapped
        ]
        for ip_str in blocked_ips:
            ip_obj = ipaddress.ip_address(ip_str)
            self.assertFalse(is_safe_ip(ip_obj), f"IP {ip_str} should be blocked")

        # Public IPs should be allowed
        allowed_ips = ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"]
        for ip_str in allowed_ips:
            ip_obj = ipaddress.ip_address(ip_str)
            self.assertTrue(is_safe_ip(ip_obj), f"IP {ip_str} should be allowed")

    def test_02_ssrf_url_policy(self):
        os.environ["FAVORITEWEB_TEST_MODE"] = "0"
        try:
            # Blocked hostnames / IPs
            self.assertFalse(is_safe_url("http://127.0.0.1/video.mp4")[0])
            self.assertFalse(is_safe_url("http://localhost:8080/video.mp4")[0])
            self.assertFalse(is_safe_url("http://internal.service.local/video.mp4")[0])
            self.assertFalse(is_safe_url("http://metadata.google.internal/")[0])
            self.assertFalse(is_safe_url("http://169.254.169.254/latest/meta-data")[0])
            self.assertFalse(is_safe_url("http://192.168.1.100/video.mp4")[0])

            # Blocked schemes
            self.assertFalse(is_safe_url("file:///etc/passwd")[0])
            self.assertFalse(is_safe_url("ftp://malicious.com/file.mp4")[0])
            self.assertFalse(is_safe_url("gopher://127.0.0.1:70/")[0])

            # Block embedded credentials
            self.assertFalse(is_safe_url("http://user:pass@example.com/video.mp4")[0])
        finally:
            os.environ["FAVORITEWEB_TEST_MODE"] = "1"

    def test_03_ssrf_redirect_to_blocked_ip(self):
        os.environ["FAVORITEWEB_TEST_MODE"] = "0"
        try:
            with patch("requests.Session.get") as mock_get:
                # Step 1 returns 302 redirecting to AWS metadata service
                mock_resp_redir = MagicMock()
                mock_resp_redir.status_code = 302
                mock_resp_redir.headers = {"Location": "http://169.254.169.254/latest/meta-data"}

                # Initial safe call returns redirect
                mock_get.return_value = mock_resp_redir

                with patch("video_editor.routes.is_safe_url", side_effect=[
                    (True, None),  # Initial URL passes
                    (False, "Access to IP 169.254.169.254 is blocked")  # Redirect target blocked
                ]):
                    with self.assertRaises(ValueError) as ctx:
                        safe_download_file("https://safe-domain.com/video.mp4", "/tmp/dummy.mp4")
                    self.assertIn("blocked by SSRF policy", str(ctx.exception))
        finally:
            os.environ["FAVORITEWEB_TEST_MODE"] = "1"

    # -----------------------------------------------------------------
    # 2. Timestamp Parser & Malformed Payload Validation
    # -----------------------------------------------------------------

    def test_04_timestamp_parsing(self):
        self.assertEqual(parse_timestamp(15), 15.0)
        self.assertEqual(parse_timestamp(12.75), 12.75)
        self.assertEqual(parse_timestamp("01:23.5"), 83.5)
        self.assertEqual(parse_timestamp("01:02:03"), 3723.0)

        with self.assertRaises(ValueError):
            parse_timestamp("invalid_time")

    def test_05_malformed_payload_and_resource_limits(self):
        # 1. Non-dict payload (JSON array)
        res = self.client.post("/video-editor/export", data="[1, 2, 3]", content_type="application/json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("JSON object", res.get_json()["error"])

        # 2. Non-JSON body
        res = self.client.post("/video-editor/export", data="not json", content_type="text/plain")
        self.assertEqual(res.status_code, 400)

        # 3. Malformed 'sources' type (string instead of array)
        res = self.client.post("/video-editor/export", json={"sources": "invalid_string"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("must be a JSON array", res.get_json()["error"])

        # 4. Malformed 'segments' type
        res = self.client.post("/video-editor/split", json={"url": "https://example.com/v.mp4", "segments": "not_an_array"})
        self.assertEqual(res.status_code, 400)

        # 5. Non-dict segment inside array
        res = self.client.post("/video-editor/split", json={"url": "https://example.com/v.mp4", "segments": ["string_segment"]})
        self.assertEqual(res.status_code, 400)

        # 6. Exceeding MAX_SOURCES
        too_many_sources = [{"url": f"https://example.com/v{i}.mp4"} for i in range(MAX_SOURCES + 2)]
        res = self.client.post("/video-editor/export", json={"sources": too_many_sources})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Too many video sources", res.get_json()["error"])

        # 7. Exceeding MAX_TOTAL_SEGMENTS (distributed across sources so no single source exceeds MAX_SEGMENTS_PER_SOURCE)
        multi_source_segments = [
            {"url": "https://example.com/v1.mp4", "segments": [{"start": i, "end": i + 1} for i in range(40)]},
            {"url": "https://example.com/v2.mp4", "segments": [{"start": i, "end": i + 1} for i in range(40)]},
            {"url": "https://example.com/v3.mp4", "segments": [{"start": i, "end": i + 1} for i in range(30)]},
        ]
        res = self.client.post("/video-editor/export", json={"sources": multi_source_segments})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Too many total segments", res.get_json()["error"])

    def test_06_zero_duration_and_invalid_timestamps(self):
        # Zero duration segment
        payload = {
            "url": "https://example.com/video.mp4",
            "segments": [{"start": 10.0, "end": 10.0}]
        }
        res = self.client.post("/video-editor/split", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("must be greater than start time", res.get_json()["error"])

        # Inverted timestamps
        payload = {
            "url": "https://example.com/video.mp4",
            "segments": [{"start": 20.0, "end": 10.0}]
        }
        res = self.client.post("/video-editor/split", json=payload)
        self.assertEqual(res.status_code, 400)

        # Sub-0.2s duration
        payload = {
            "url": "https://example.com/video.mp4",
            "segments": [{"start": 10.0, "end": 10.1}]
        }
        res = self.client.post("/video-editor/split", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("too short", res.get_json()["error"])

    # -----------------------------------------------------------------
    # Helper: Poll Job to Completion
    # -----------------------------------------------------------------

    def _wait_for_job(self, job_id, timeout=30):
        start = time.time()
        while time.time() - start < timeout:
            res = self.client.get(f"/video-editor/job-status/{job_id}")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            status = data.get("status")
            if status == "ready":
                return data
            if status == "error":
                self.fail(f"Job {job_id} failed: {data.get('error')}")
            time.sleep(0.5)
        self.fail(f"Job {job_id} timed out after {timeout}s")

    # -----------------------------------------------------------------
    # 3. Export, Split, and Merge Integration Tests
    # -----------------------------------------------------------------

    def test_07_full_video_export(self):
        src_url = f"file:///{self.clip1_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "mode": "export"
        }
        res = self.client.post("/video-editor/export", json=payload)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["jobId"]

        job_data = self._wait_for_job(job_id)
        self.assertEqual(job_data["status"], "ready")
        self.assertTrue(job_data["size"] > 0)

        file_res = self.client.get(f"/video-editor/job-file/{job_id}")
        self.assertEqual(file_res.status_code, 200)
        self.assertEqual(file_res.mimetype, "video/mp4")
        self.assertTrue(len(file_res.data) > 0)

        out_path = os.path.join(self.temp_dir, f"out_{job_id}.mp4")
        with open(out_path, "wb") as f:
            f.write(file_res.data)

        probe = probe_media(out_path)
        self.assertAlmostEqual(probe["duration"], 5.0, delta=0.5)
        self.assertTrue(probe["has_video"])

    def test_08_individual_split_zip_export(self):
        src_url = f"file:///{self.clip1_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "segments": [
                {"start": 1.0, "end": 2.5, "label": "part_one"},
                {"start": 3.0, "end": 4.8, "label": "part_two"},
            ],
            "exportIndividual": True
        }
        res = self.client.post("/video-editor/split", json=payload)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["jobId"]

        job_data = self._wait_for_job(job_id)
        self.assertEqual(job_data["status"], "ready")
        self.assertEqual(job_data["filename"], "video_clips.zip")

        file_res = self.client.get(f"/video-editor/job-file/{job_id}")
        self.assertEqual(file_res.status_code, 200)
        self.assertEqual(file_res.mimetype, "application/zip")

        zip_path = os.path.join(self.temp_dir, f"out_{job_id}.zip")
        with open(zip_path, "wb") as f:
            f.write(file_res.data)

        extract_dir = os.path.join(self.temp_dir, f"extracted_{job_id}")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
            namelist = zf.namelist()

        self.assertIn("part_one.mp4", namelist)
        self.assertIn("part_two.mp4", namelist)

        probe1 = probe_media(os.path.join(extract_dir, "part_one.mp4"))
        self.assertAlmostEqual(probe1["duration"], 1.5, delta=0.4)
        self.assertTrue(probe1["size"] > 0)

        probe2 = probe_media(os.path.join(extract_dir, "part_two.mp4"))
        self.assertAlmostEqual(probe2["duration"], 1.8, delta=0.4)
        self.assertTrue(probe2["size"] > 0)

    def test_09_multi_video_merge_export(self):
        src1_url = f"file:///{self.clip1_path.replace(os.sep, '/')}"
        src2_url = f"file:///{self.clip2_path.replace(os.sep, '/')}"

        payload = {
            "sources": [
                {"url": src1_url, "segments": [{"start": 0.5, "end": 2.5}]},
                {"url": src2_url, "segments": [{"start": 0.0, "end": 2.0}]},
            ],
            "mode": "combined"
        }
        res = self.client.post("/video-editor/merge", json=payload)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["jobId"]

        job_data = self._wait_for_job(job_id)
        self.assertEqual(job_data["status"], "ready")
        self.assertEqual(job_data["filename"], "combined_export.mp4")

        file_res = self.client.get(f"/video-editor/job-file/{job_id}")
        self.assertEqual(file_res.status_code, 200)
        self.assertEqual(file_res.mimetype, "video/mp4")

        out_path = os.path.join(self.temp_dir, f"out_{job_id}.mp4")
        with open(out_path, "wb") as f:
            f.write(file_res.data)

        probe = probe_media(out_path)
        self.assertAlmostEqual(probe["duration"], 4.0, delta=0.6)
        self.assertTrue(probe["size"] > 0)

    # -----------------------------------------------------------------
    # 4. Atomic Download Lifecycle vs Concurrent Cleanup
    # -----------------------------------------------------------------

    def test_10_atomic_download_lifecycle_and_cleanup(self):
        job_id = "test_atomic_download_job"
        dummy_temp = tempfile.mkdtemp(prefix="test-atomic-")
        dummy_file = os.path.join(dummy_temp, "test.mp4")
        with open(dummy_file, "wb") as f:
            f.write(b"SAMPLE_VIDEO_DATA")

        with EDITOR_JOBS_LOCK:
            EDITOR_JOBS[job_id] = {
                "id": job_id,
                "jobId": job_id,
                "status": "ready",
                "file_path": dummy_file,
                "filename": "test.mp4",
                "content_type": "video/mp4",
                "size": len(b"SAMPLE_VIDEO_DATA"),
                "updated_at": time.time() - 36000,  # Expired
                "temp_dir": dummy_temp,
                "active_downloads": 0,
            }

        # Request file stream
        file_res = self.client.get(f"/video-editor/job-file/{job_id}")
        self.assertEqual(file_res.status_code, 200)
        # Read content and close response stream to release Windows file handle
        _ = file_res.data
        file_res.close()

        # Simulate active stream: increment active_downloads
        with EDITOR_JOBS_LOCK:
            EDITOR_JOBS[job_id]["active_downloads"] = 1

        # Run cleanup while download is active
        _cleanup_old_jobs()

        # Job and file MUST NOT be deleted
        with EDITOR_JOBS_LOCK:
            self.assertIn(job_id, EDITOR_JOBS)
            self.assertTrue(os.path.exists(dummy_file))

            # Simulate stream termination and post-download retention expiry (held for 5 mins / 300s)
            EDITOR_JOBS[job_id]["active_downloads"] = 0
            EDITOR_JOBS[job_id]["downloaded_at"] = time.time() - 400
            EDITOR_JOBS[job_id]["updated_at"] = time.time() - 400

        # Run cleanup after stream ended and retention expired
        _cleanup_old_jobs()

        with EDITOR_JOBS_LOCK:
            self.assertNotIn(job_id, EDITOR_JOBS)
        self.assertFalse(os.path.exists(dummy_temp))

    # -----------------------------------------------------------------
    # 5. Downloader API Regression Test
    # -----------------------------------------------------------------

    def test_11_downloader_api_regression(self):
        res = self.client.get("/download/api")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("error", data)
        self.assertEqual(data["error"], "No URL")

        res = self.client.get("/download/job-status/non_existent_job_123")
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
