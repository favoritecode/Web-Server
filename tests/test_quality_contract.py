import os
import sys
import json
import time
import shutil
import tempfile
import zipfile
import subprocess
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ["FAVORITEWEB_TEST_MODE"] = "1"

from app import app
from video_editor.routes import get_ffmpeg_bin, probe_media

class VideoEditorQualityContractTestSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.temp_dir = tempfile.mkdtemp(prefix="ve-quality-test-")
        cls.ffmpeg = get_ffmpeg_bin("ffmpeg")
        cls.ffprobe = get_ffmpeg_bin("ffprobe")

        # 1. Controlled 720p fixture (1280x720, 3 seconds)
        cls.fixture_720_path = os.path.join(cls.temp_dir, "fixture_720.mp4")
        subprocess.run([
            cls.ffmpeg, "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=1280x720:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
            "-c:v", "libx264", "-c:a", "aac",
            cls.fixture_720_path
        ], capture_output=True, check=True)

        # 2. Controlled 360p fixture (640x360, 2 seconds)
        cls.fixture_360_path = os.path.join(cls.temp_dir, "fixture_360.mp4")
        subprocess.run([
            cls.ffmpeg, "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=800:duration=2",
            "-c:v", "libx264", "-c:a", "aac",
            cls.fixture_360_path
        ], capture_output=True, check=True)

        # 3. Controlled Portrait fixture (720x1280, 2 seconds)
        cls.fixture_portrait_path = os.path.join(cls.temp_dir, "fixture_portrait.mp4")
        subprocess.run([
            cls.ffmpeg, "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=720x1280:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=600:duration=2",
            "-c:v", "libx264", "-c:a", "aac",
            cls.fixture_portrait_path
        ], capture_output=True, check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _wait_for_job(self, job_id, timeout=30):
        start = time.time()
        while time.time() - start < timeout:
            res = self.client.get(f"/video-editor/job-status/{job_id}")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            if data.get("status") in ("ready", "failed", "error"):
                return data
            time.sleep(0.3)
        self.fail(f"Job {job_id} timed out after {timeout}s")

    # -------------------------------------------------------------
    # 1. Payload Validation Tests
    # -------------------------------------------------------------

    def test_01_quality_validation_mismatch(self):
        """Mismatched quality and max_height must return 400 error."""
        src_url = f"file:///{self.fixture_720_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "mode": "export",
            "quality": "720",
            "max_height": 480,
            "quality_contract_version": 1,
        }
        res = self.client.post("/video-editor/export", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Quality mismatch", res.get_json().get("error", ""))

    def test_02_quality_validation_invalid_value(self):
        """Unsupported quality string must return 400 error."""
        src_url = f"file:///{self.fixture_720_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "mode": "export",
            "quality": "999",
        }
        res = self.client.post("/video-editor/export", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid quality", res.get_json().get("error", ""))

    def test_03_quality_validation_invalid_max_height(self):
        """Unsupported max_height value must return 400 error."""
        src_url = f"file:///{self.fixture_720_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "mode": "export",
            "max_height": "invalid_int",
        }
        res = self.client.post("/video-editor/export", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid max_height", res.get_json().get("error", ""))

    # -------------------------------------------------------------
    # 2. Real Downscale & Verification: 240p
    # -------------------------------------------------------------

    def test_04_downscale_720p_to_240p(self):
        """Exporting a 720p source with quality=240 must produce verified 240p output."""
        src_url = f"file:///{self.fixture_720_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "mode": "export",
            "quality": "240",
            "max_height": 240,
            "quality_contract_version": 1,
        }
        res = self.client.post("/video-editor/export", json=payload)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["jobId"]

        job_data = self._wait_for_job(job_id)
        self.assertEqual(job_data["status"], "ready")
        self.assertIn("quality", job_data)
        q = job_data["quality"]
        self.assertTrue(q["verified"])
        self.assertEqual(q["output_height"], 240)
        self.assertEqual(q["requested"], "240")

        # Verify physical file with ffprobe
        file_res = self.client.get(f"/video-editor/job-file/{job_id}")
        self.assertEqual(file_res.status_code, 200)
        out_file = os.path.join(self.temp_dir, f"out_{job_id}.mp4")
        with open(out_file, "wb") as f:
            f.write(file_res.data)

        probe = probe_media(out_file)
        self.assertEqual(probe["height"], 240)
        self.assertEqual(probe["width"], 426)
        self.assertTrue(probe["has_video"])
        self.assertTrue(probe["has_audio"])

    # -------------------------------------------------------------
    # 3. Real Downscale & Verification: 144p
    # -------------------------------------------------------------

    def test_05_downscale_720p_to_144p(self):
        """Exporting a 720p source with quality=144 must produce verified 144p output."""
        src_url = f"file:///{self.fixture_720_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "mode": "export",
            "quality": "144",
            "max_height": 144,
            "quality_contract_version": 1,
        }
        res = self.client.post("/video-editor/export", json=payload)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["jobId"]

        job_data = self._wait_for_job(job_id)
        self.assertEqual(job_data["status"], "ready")
        q = job_data["quality"]
        self.assertTrue(q["verified"])
        self.assertEqual(q["output_height"], 144)

        file_res = self.client.get(f"/video-editor/job-file/{job_id}")
        out_file = os.path.join(self.temp_dir, f"out_{job_id}.mp4")
        with open(out_file, "wb") as f:
            f.write(file_res.data)

        probe = probe_media(out_file)
        self.assertEqual(probe["height"], 144)
        self.assertEqual(probe["width"], 256)

    # -------------------------------------------------------------
    # 4. Source Lower than Requested (Clamping / No Upscale)
    # -------------------------------------------------------------

    def test_06_source_lower_than_requested_no_upscale(self):
        """Requesting 720p on a 360p source must NOT upscale; must clamp to 360p."""
        src_url = f"file:///{self.fixture_360_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "mode": "export",
            "quality": "720",
            "max_height": 720,
            "quality_contract_version": 1,
        }
        res = self.client.post("/video-editor/export", json=payload)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["jobId"]

        job_data = self._wait_for_job(job_id)
        self.assertEqual(job_data["status"], "ready")
        q = job_data["quality"]
        self.assertTrue(q["verified"])
        self.assertEqual(q["output_height"], 360)
        self.assertTrue(q.get("clamped", False))
        self.assertIn("reason", q)

        file_res = self.client.get(f"/video-editor/job-file/{job_id}")
        out_file = os.path.join(self.temp_dir, f"out_{job_id}.mp4")
        with open(out_file, "wb") as f:
            f.write(file_res.data)

        probe = probe_media(out_file)
        self.assertEqual(probe["height"], 360)
        self.assertEqual(probe["width"], 640)

    # -------------------------------------------------------------
    # 5. Split / ZIP Export with Quality Cap
    # -------------------------------------------------------------

    def test_07_split_zip_with_quality_cap(self):
        """Split mode with quality cap must verify every clip inside the ZIP."""
        src_url = f"file:///{self.fixture_720_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "mode": "split",
            "quality": "240",
            "max_height": 240,
            "segments": [
                {"name": "clip_a", "start": 0.0, "end": 1.0},
                {"name": "clip_b", "start": 1.5, "end": 2.5},
            ]
        }
        res = self.client.post("/video-editor/split", json=payload)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["jobId"]

        job_data = self._wait_for_job(job_id)
        self.assertEqual(job_data["status"], "ready")
        q = job_data["quality"]
        self.assertTrue(q["verified"])
        self.assertEqual(q["output_height"], 240)

        # Download ZIP and verify each MP4
        file_res = self.client.get(f"/video-editor/job-file/{job_id}")
        self.assertEqual(file_res.status_code, 200)
        self.assertEqual(file_res.mimetype, "application/zip")

        zip_path = os.path.join(self.temp_dir, f"out_{job_id}.zip")
        with open(zip_path, "wb") as f:
            f.write(file_res.data)

        extract_dir = os.path.join(self.temp_dir, f"extracted_{job_id}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        mp4_files = [f for f in os.listdir(extract_dir) if f.endswith(".mp4")]
        self.assertEqual(len(mp4_files), 2)
        for mp4_name in mp4_files:
            mp4_path = os.path.join(extract_dir, mp4_name)
            probe = probe_media(mp4_path)
            self.assertEqual(probe["height"], 240, f"{mp4_name} height should be 240")
            self.assertEqual(probe["width"], 426, f"{mp4_name} width should be 426")

    # -------------------------------------------------------------
    # 6. Merge Multi-Video with Quality Cap
    # -------------------------------------------------------------

    def test_08_merge_with_quality_cap(self):
        """Merge multiple sources with quality cap must produce a combined MP4 at that cap."""
        src1_url = f"file:///{self.fixture_720_path.replace(os.sep, '/')}"
        src2_url = f"file:///{self.fixture_720_path.replace(os.sep, '/')}"
        payload = {
            "sources": [
                {"url": src1_url, "segments": [{"start": 0.0, "end": 1.0}]},
                {"url": src2_url, "segments": [{"start": 1.0, "end": 2.0}]},
            ],
            "mode": "merge",
            "quality": "360",
            "max_height": 360,
        }
        res = self.client.post("/video-editor/merge", json=payload)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["jobId"]

        job_data = self._wait_for_job(job_id)
        self.assertEqual(job_data["status"], "ready")
        q = job_data["quality"]
        self.assertTrue(q["verified"])
        self.assertEqual(q["output_height"], 360)

        file_res = self.client.get(f"/video-editor/job-file/{job_id}")
        out_file = os.path.join(self.temp_dir, f"out_{job_id}.mp4")
        with open(out_file, "wb") as f:
            f.write(file_res.data)

        probe = probe_media(out_file)
        self.assertEqual(probe["height"], 360)
        self.assertEqual(probe["width"], 640)

    # -------------------------------------------------------------
    # 7. Portrait Video Scaling Preserves Aspect Ratio
    # -------------------------------------------------------------

    def test_09_portrait_aspect_ratio_preservation(self):
        """Portrait 720x1280 scaled with quality=360 must scale height to 360 without stretching."""
        src_url = f"file:///{self.fixture_portrait_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "mode": "export",
            "quality": "360",
            "max_height": 360,
        }
        res = self.client.post("/video-editor/export", json=payload)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["jobId"]

        job_data = self._wait_for_job(job_id)
        self.assertEqual(job_data["status"], "ready")

        file_res = self.client.get(f"/video-editor/job-file/{job_id}")
        out_file = os.path.join(self.temp_dir, f"out_{job_id}.mp4")
        with open(out_file, "wb") as f:
            f.write(file_res.data)

        probe = probe_media(out_file)
        self.assertEqual(probe["height"], 360)
        # Original 720x1280 ratio: 720/1280 = 0.5625. For height 360: width is ~202
        self.assertAlmostEqual(probe["width"] / probe["height"], 720 / 1280, delta=0.02)
        self.assertEqual(probe["width"] % 2, 0) # Even dimension

    # -------------------------------------------------------------
    # 8. Backward Compatibility: Original / No Quality Sent
    # -------------------------------------------------------------

    def test_10_backward_compatibility_no_quality(self):
        """When quality is omitted, original resolution is preserved without error."""
        src_url = f"file:///{self.fixture_720_path.replace(os.sep, '/')}"
        payload = {
            "url": src_url,
            "mode": "export"
        }
        res = self.client.post("/video-editor/export", json=payload)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["jobId"]

        job_data = self._wait_for_job(job_id)
        self.assertEqual(job_data["status"], "ready")
        q = job_data["quality"]
        self.assertEqual(q["requested"], "original")
        self.assertEqual(q["output_height"], 720)
        self.assertTrue(q["verified"])


if __name__ == "__main__":
    unittest.main()

