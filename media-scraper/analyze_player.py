#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyze player.js for video URL patterns."""

import re
import urllib.request

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

url = 'https://allmovieland.link/player.js?v=5'
req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
data = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='replace')
print(f'Size: {len(data)} bytes')

print('\n=== All URLs ===')
for m in re.findall(r'https?://[^\s"\'<>]+', data)[:40]:
    print(m[:250])

print('\n=== Video-related patterns ===')
for m in re.findall(r'(?:file|src|url|video|playlist|source|embed|stream|hls|mp4|m3u8)[^,;]{0,200}', data, re.I)[:30]:
    print(m[:250])
    print('---')