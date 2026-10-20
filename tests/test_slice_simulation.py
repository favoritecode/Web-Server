import os
import sys
import time
import subprocess
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

TEST_TOKEN = "test_fwt_secret_token_12345_media_relay"
os.environ["FWT_MEDIA_RELAY_TOKEN"] = TEST_TOKEN

from app import app

client = app.test_client()
auth_headers = {"Authorization": f"Bearer {TEST_TOKEN}"}
test_url = "https://www.youtube.com/watch?v=ZTQjnm_iiRE"

print("--- Starting Partial Stream Simulation & Measurement ---")
# 1. Read first 512 KiB chunk
t0 = time.time()
resp0 = client.get(
    f"/download/partial-stream?url={test_url}&format_id=18",
    headers={**auth_headers, "Range": "bytes=0-524287"}
)
dt0 = time.time() - t0
print(f"Chunk 0 (0-524287): status={resp0.status_code}, len={len(resp0.data)}, time={dt0:.3f}s")
source_id = resp0.headers.get("X-Media-Source-ID")
content_range = resp0.headers.get("Content-Range")
print(f"Source ID: {source_id}")
print(f"Content-Range: {content_range}")

# Total video size from Content-Range
total_size = int(content_range.split("/")[1])
print(f"Total video size: {total_size:,} bytes ({total_size / (1024*1024):.2f} MB)")

# Target clip: 58:21.663 to 01:01:37.554 (195.891s)
# Total video duration: 13198.8s
video_duration = 13198.8
clip_start = 58 * 60 + 21.663      # 3501.663s
clip_end = 1 * 3600 + 1 * 60 + 37.554 # 3697.554s
clip_duration = clip_end - clip_start  # 195.891s

# Calculate proportional byte range in mdat
# Moov size is 4,172,045 bytes.
moov_size = 4172045
mdat_size = total_size - moov_size
byte_start = int(moov_size + (clip_start / video_duration) * mdat_size)
byte_end = int(moov_size + (clip_end / video_duration) * mdat_size)
clip_bytes = byte_end - byte_start

print(f"Clip duration: {clip_duration:.3f}s out of {video_duration:.1f}s")
print(f"Estimated media byte range: {byte_start:,} to {byte_end:,} ({clip_bytes:,} bytes, {clip_bytes / (1024*1024):.2f} MB)")

# Read a sample chunk from the target clip media range to verify seeking
t1 = time.time()
resp_clip = client.get(
    f"/download/partial-stream?url={test_url}&format_id=18&source_id={source_id}",
    headers={**auth_headers, "Range": f"bytes={byte_start}-{byte_start + 524288 - 1}"}
)
dt1 = time.time() - t1
print(f"Sample clip chunk ({byte_start}-{byte_start + 524288 - 1}): status={resp_clip.status_code}, len={len(resp_clip.data)}, time={dt1:.3f}s")

# Total transfer measurement for the clip
total_transferred = moov_size + clip_bytes
saved_bytes = total_size - total_transferred
savings_pct = (saved_bytes / total_size) * 100

print("--- Transfer Comparison Summary ---")
print(f"Full video download would transfer: {total_size:,} bytes ({total_size / (1024*1024):.2f} MB)")
print(f"Bounded partial stream transfers : {total_transferred:,} bytes ({total_transferred / (1024*1024):.2f} MB)")
print(f"Bandwidth saved                   : {saved_bytes:,} bytes ({savings_pct:.2f}% reduction)")
print("--- Check Complete ---")

