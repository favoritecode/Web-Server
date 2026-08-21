#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyze a webpage for video sources and image issues."""

import re
import sys
import urllib.parse
import urllib.request

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


def fetch(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode('utf-8', errors='replace')


def main():
    url = sys.argv[1]
    print(f'Fetching: {url}')
    html = fetch(url)
    print(f'HTML size: {len(html)} bytes')

    print('\n=== iframe/embed/video/object tags ===')
    for m in re.findall(r'<(?:iframe|embed|object|video)[^>]*>', html, re.I):
        print(m[:300])
        print('---')

    print('\n=== Direct media URLs (.mp4/.m3u8/.webm/.ogg/.ts) ===')
    for m in re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8|webm|ogg|ts)(?:[^\s"\'<>]*)', html, re.I):
        print(m[:300])

    print('\n=== file/src/playlist patterns ===')
    for m in re.findall(
            r'(?:file|src|playlist|video_url|download_url|contentUrl|embedUrl)\s*[:=]\s*(["\'])(.*?)\1',
            html, re.I):
        print(str(m)[:300])

    print('\n=== data-thumb / data-video / data-url attributes ===')
    for m in re.findall(r'data-(?:video|video-src|video-url|file|source|src|url|thumb)\s*=\s*["\'](.*?)["\']', html, re.I):
        print(m[:300])

    print('\n=== woff/woff2/ttf/eot font files ===')
    for m in re.findall(r'https?://[^\s"\'<>]+\.(?:woff2?|ttf|eot|otf)(?:[^\s"\'<>]*)', html, re.I):
        print(m[:200])


if __name__ == '__main__':
    main()