#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find IndStreamPlayerConfigs / stream config in page HTML."""

import re
import sys
import urllib.request

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

url = sys.argv[1]
req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
html = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', errors='replace')
print(f'HTML size: {len(html)}')

print('\n=== IndStream / Stream config ===')
for m in re.findall(r'IndStreamPlayerConfigs\s*=\s*\{[^}]+\}', html):
    print(m[:500])
    print('---')

print('\n=== src / data-src / data-player / data-video attributes ===')
for m in re.findall(r'(?:data-(?:src|player|video|file|source|url|id)|src)\s*=\s*["\']([^"\']+)["\']', html, re.I):
    if any(k in m.lower() for k in ('stream', 'play', 'video', 'embed', 'http')):
        print(m[:300])

print('\n=== All script srcs ===')
for m in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I):
    print(m[:300])

print('\n=== All iframe/embed ===')
for m in re.findall(r'<(?:iframe|embed)[^>]*>', html, re.I):
    print(m[:300])