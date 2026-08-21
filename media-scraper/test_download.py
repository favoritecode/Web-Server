#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test downloading artlist.io audio file with Referer header."""

from curl_cffi import requests

url = 'https://cms-public-artifacts.artlist.io/content/sfx/aac/895865_895829_Fucking_Loon_-_SFE-23-000520__-_MASTERED_-_2496.aac'

print('=== Test: curl_cffi with artlist.io Referer ===')
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://artlist.io/',
    'Accept': '*/*',
}
try:
    r = requests.get(url, headers=headers, impersonate='chrome', timeout=30)
    print('status:', r.status_code)
    print('content-type:', r.headers.get('Content-Type'))
    print('content-length:', r.headers.get('Content-Length'))
    print('got bytes:', len(r.content))
except Exception as e:
    print('ERROR:', e)