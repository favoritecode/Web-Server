#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find artlist.io audio file URLs (cms-public-artifacts pattern)."""

import re

from curl_cffi import requests

url = 'https://artlist.io/sfx/track/yellowstone-birds---loon-call/127855'
resp = requests.get(url, impersonate='chrome', timeout=30)
html = resp.text
print(f'Status: {resp.status_code}, size: {len(html)}')

print('\n=== cms-public-artifacts URLs ===')
for m in re.findall(r'https?://cms-public-artifacts\.artlist\.io[^\s"\'<>\\]*', html, re.I)[:20]:
    print(m[:300])

print('\n=== Any .aac/.mp3/.wav URLs ===')
for m in re.findall(r'https?://[^\s"\'<>\\]+\.(?:aac|mp3|wav|m4a|flac|ogg)(?:[^\s"\'<>\\]*)', html, re.I)[:20]:
    print(m[:300])

print('\n=== artlist.io CDN / artifacts patterns ===')
for m in re.findall(r'https?://[^\s"\'<>\\]*(?:artifacts|cdn|media|storage|download|preview)[^\s"\'<>\\]*', html, re.I)[:30]:
    print(m[:300])

print('\n=== songData / audioUrl / previewUrl in scripts ===')
for m in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
    text = m.group(1)
    for fm in re.finditer(r'(?:audioUrl|previewUrl|audio_url|preview_url|fileUrl|downloadUrl|streamUrl|url)\s*[:=]\s*["\']([^"\']+)["\']', text, re.I):
        val = fm.group(1)
        if 'artlist' in val or 'http' in val:
            print(val[:300])