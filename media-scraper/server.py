#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Media Scraper Server
====================
A web scraper tool that extracts video, audio, and image URLs from any webpage.

Run:  python server.py
Then open:  http://localhost:8000

Uses only Python standard library — no external dependencies required.
"""

import base64
import json
import os
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.server import HTTPServer, BaseHTTPRequestHandler

# Optional yt-dlp for direct video/audio URL resolution
try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

# Optional curl_cffi for Cloudflare-protected pages
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_RESPONSE_SIZE = 20 * 1024 * 1024  # 20 MB

VIDEO_EXTENSIONS = (
    '.mp4', '.webm', '.ogg', '.ogv', '.mov', '.m4v', '.mkv', '.avi',
    '.flv', '.wmv', '.3gp', '.m3u8', '.mpd', '.ts', '.m2ts', '.mpeg', '.mpg',
)
AUDIO_EXTENSIONS = (
    '.mp3', '.wav', '.ogg', '.oga', '.m4a', '.aac', '.flac', '.wma',
    '.opus', '.mid', '.midi', '.amr', '.aiff', '.caf', '.weba',
)
IMAGE_EXTENSIONS = (
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico', '.bmp',
    '.avif', '.apng', '.jfif', '.pjpeg', '.pjp', '.tiff', '.tif',
    '.heic', '.heif',
)

# Font files that should NOT be treated as images
FONT_EXTENSIONS = (
    '.woff', '.woff2', '.ttf', '.eot', '.otf', '.otc',
)

# Known video hosting/embed domains — URLs from these are treated as videos
VIDEO_HOST_DOMAINS = (
    'youtube.com/embed', 'youtube-nocookie.com/embed', 'player.vimeo.com',
    'vimeo.com', 'dailymotion.com/embed', 'dailymotion.com/video',
    'facebook.com/plugins/video', 'player.twitch.tv', 'w.soundcloud.com/player',
    'spotify.com/embed', 'archive.org/embed', 'youtube.com/watch',
    'youtu.be/', 'bilibili.com/video', 'ok.ru/video', 'vk.com/video',
    'tiktok.com/', 'instagram.com/reel', 'instagram.com/p/',
)

# Domains that should NOT be treated as video iframes (ads, login, etc.)
IFRAME_BLOCKLIST = (
    'googleads', 'doubleclick', 'googlesyndication', 'accounts.google.com',
    'google.com/recaptcha', 'gstatic.com', 'facebook.com/plugins/page',
    'facebook.com/plugins/like', 'twitter.com/i/', 'x.com/i/',
    'addthis.com', 'disqus.com', 'cookiebot', 'onetrust',
)

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


class MediaParser(HTMLParser):
    """HTML parser that extracts video, audio, and image URLs from a page."""

    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.videos = []
        self.audios = []
        self.images = []
        self.external_scripts = []
        self.external_styles = []
        self._in_video = False
        self._in_audio = False
        self._in_script = False
        self._in_style = False
        self._script_parts = []
        self._style_parts = []

    # ---------- helpers ----------

    def _resolve(self, url):
        if not url:
            return None
        url = url.strip().strip('"').strip("'").strip()
        if not url:
            return None
        if url.startswith(('data:', 'javascript:', 'mailto:', 'tel:',
                           'blob:', 'about:', 'chrome:', 'file:', 'vbscript:')):
            return None
        return urllib.parse.urljoin(self.base_url, url)

    def _add(self, collection, url):
        resolved = self._resolve(url)
        if resolved and resolved not in collection:
            collection.append(resolved)

    def _add_video(self, url):
        resolved = self._resolve(url)
        if not resolved or resolved in self.videos:
            return
        path = urllib.parse.urlparse(resolved).path.lower()
        if (path.endswith(VIDEO_EXTENSIONS)
                or '/play/' in path
                or '/embed/' in path
                or any(host in resolved.lower() for host in VIDEO_HOST_DOMAINS)):
            self.videos.append(resolved)

    def _add_audio(self, url):
        self._add(self.audios, url)

    def _add_image(self, url):
        resolved = self._resolve(url)
        if not resolved or resolved in self.images:
            return
        # Skip font files (woff2, ttf, eot, etc.)
        path = urllib.parse.urlparse(resolved).path.lower()
        if path.endswith(FONT_EXTENSIONS):
            return
        # Skip SVG symbols/defs references (e.g. page.html#wp-duotone-...)
        if '#' in resolved:
            return
        self.images.append(resolved)

    def _check_extension(self, url):
        """Add URL to the right collection if it points to a media file."""
        path = urllib.parse.urlparse(url).path.lower()
        if path.endswith(VIDEO_EXTENSIONS):
            self._add_video(url)
        elif path.endswith(AUDIO_EXTENSIONS):
            self._add_audio(url)
        elif path.endswith(IMAGE_EXTENSIONS):
            self._add_image(url)

    def _extract_srcset(self, srcset):
        """Extract URLs from a srcset attribute."""
        if not srcset:
            return
        for part in srcset.split(','):
            candidate = part.strip().split(' ')[0].strip()
            if candidate:
                self._add_image(candidate)

    def _extract_css_urls(self, css):
        """Extract url(...) references from CSS text."""
        if not css:
            return
        for m in re.finditer(r'url\(\s*(["\']?)(.*?)\1\s*\)', css):
            self._add_image(m.group(2))

    # ---------- parser callbacks ----------

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)

        # CSS background images inside style="" attribute
        style = attrs.get('style')
        if style:
            self._extract_css_urls(style)

        # lazy-load background attributes
        for attr in ('data-bg', 'data-background', 'data-bg-image'):
            if attrs.get(attr):
                self._add_image(attrs[attr])

        if tag == 'video':
            self._in_video = True
            if attrs.get('src'):
                self._add_video(attrs['src'])
            if attrs.get('poster'):
                self._add_image(attrs['poster'])

        elif tag == 'audio':
            self._in_audio = True
            if attrs.get('src'):
                self._add_audio(attrs['src'])

        elif tag == 'source':
            src = attrs.get('src')
            srcset = attrs.get('srcset')
            stype = attrs.get('type', '')
            if src:
                if self._in_video or 'video' in stype:
                    self._add_video(src)
                elif self._in_audio or 'audio' in stype:
                    self._add_audio(src)
                else:
                    self._check_extension(src)
            if srcset:
                self._extract_srcset(srcset)

        elif tag == 'img':
            for attr in ('src', 'data-src', 'data-original', 'data-lazy-src',
                         'data-url', 'data-image', 'data-lazy'):
                if attrs.get(attr):
                    self._add_image(attrs[attr])
            for attr in ('srcset', 'data-srcset'):
                if attrs.get(attr):
                    self._extract_srcset(attrs[attr])
            if attrs.get('poster'):
                self._add_image(attrs['poster'])

        elif tag == 'iframe':
            src = attrs.get('src')
            if src:
                # iframes often embed videos (YouTube, Vimeo, etc.)
                # Add iframe src as video if it's a known video host
                resolved = self._resolve(src)
                if resolved and resolved not in self.videos:
                    lower = resolved.lower()
                    if not any(block in lower for block in IFRAME_BLOCKLIST):
                        self.videos.append(resolved)
            # Also check data-src / data-lazy-src for lazy-loaded iframes
            for attr in ('data-src', 'data-lazy-src', 'data-original'):
                lazy_src = attrs.get(attr)
                if lazy_src:
                    resolved = self._resolve(lazy_src)
                    if resolved and resolved not in self.videos:
                        lower = resolved.lower()
                        if not any(block in lower for block in IFRAME_BLOCKLIST):
                            self.videos.append(resolved)

        elif tag == 'a':
            href = attrs.get('href')
            if href:
                self._check_extension(href)

        elif tag == 'link':
            href = attrs.get('href')
            if href:
                self._check_extension(href)
            # Track external CSS files for deep scan
            if attrs.get('rel', '').lower() == 'stylesheet' and href:
                resolved = self._resolve(href)
                if resolved and resolved not in self.external_styles:
                    self.external_styles.append(resolved)

        elif tag == 'meta':
            content = attrs.get('content', '')
            prop = (attrs.get('property') or attrs.get('name') or '').lower()
            if content:
                if 'image' in prop:
                    self._add_image(content)
                elif 'video' in prop:
                    self._add_video(content)
                elif 'audio' in prop:
                    self._add_audio(content)

        elif tag == 'script':
            self._in_script = True
            self._script_parts = []
            # Track external script files for deep scan
            src = attrs.get('src')
            if src:
                resolved = self._resolve(src)
                if resolved and resolved not in self.external_scripts:
                    self.external_scripts.append(resolved)

        elif tag == 'style':
            self._in_style = True
            self._style_parts = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == 'video':
            self._in_video = False
        elif tag == 'audio':
            self._in_audio = False
        elif tag == 'script':
            self._in_script = False
            self._scan_text_for_media(''.join(self._script_parts))
        elif tag == 'style':
            self._in_style = False
            self._extract_css_urls(''.join(self._style_parts))

    def handle_data(self, data):
        if self._in_script:
            self._script_parts.append(data)
        elif self._in_style:
            self._style_parts.append(data)

    def _scan_text_for_media(self, text):
        """Scan script/CSS text for direct media file URLs."""
        for m in re.finditer(r'https?://[^\s"\'<>\\]+', text):
            url = m.group(0).rstrip('.,;:!?)]}\'"')
            self._check_extension(url)


def extract_title(html):
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        html, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return ''


def fetch_page(url):
    """Fetch a webpage and return its decoded HTML content."""
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': ('text/html,application/xhtml+xml,application/xml;q=0.9,'
                   'image/avif,image/webp,*/*;q=0.8'),
        'Accept-Language': 'en-US,en;q=0.9',
    }

    # If curl_cffi is available, use it first to bypass Cloudflare anti-bot
    if CURL_CFFI_AVAILABLE:
        try:
            resp = curl_requests.get(url, headers=headers, impersonate='chrome', timeout=30, allow_redirects=True)
            if resp.status_code == 200:
                data = resp.content
                content_type = resp.headers.get('Content-Type', '')
                charset = 'utf-8'
                m = re.search(r'charset=([\w-]+)', content_type, re.IGNORECASE)
                if m:
                    charset = m.group(1)
                try:
                    return data.decode(charset)
                except (LookupError, UnicodeDecodeError):
                    return data.decode('utf-8', errors='replace')
        except Exception:
            pass

    # Fallback to urllib
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        content_type = resp.headers.get('Content-Type', '')
        data = resp.read(MAX_RESPONSE_SIZE)
        charset = 'utf-8'
        m = re.search(r'charset=([\w-]+)', content_type, re.IGNORECASE)
        if m:
            charset = m.group(1)
        try:
            return data.decode(charset)
        except (LookupError, UnicodeDecodeError):
            return data.decode('utf-8', errors='replace')


def fetch_text(url):
    """Fetch a URL and return its text content, or None on failure."""
    try:
        return fetch_page(url)
    except Exception:
        return None


def extract_jsonld_media(html, base_url):
    """Extract audio/video URLs from JSON-LD (schema.org) embedded in a page."""
    found_audio = []
    found_video = []
    # Find application/ld+json blocks
    for m in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE):
        try:
            data_text = m.group(1).strip()
            data = json.loads(data_text)
        except Exception:
            continue
        # Handle single object or array/list
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get('@type') or '').lower()
            if 'audio' in item_type or 'video' in item_type:
                content_url = item.get('contentUrl') or item.get('url') or ''
                if content_url:
                    resolved = urllib.parse.urljoin(base_url, content_url)
                    # Skip if it's just the page URL itself (not actual media file)
                    if resolved.rstrip('/') != base_url.rstrip('/'):
                        if 'audio' in item_type:
                            found_audio.append(resolved)
                        else:
                            found_video.append(resolved)
                # Also check "encoding" / "associatedMedia"
                for enc_key in ('encoding', 'associatedMedia'):
                    enc = item.get(enc_key)
                    if isinstance(enc, dict):
                        enc_url = enc.get('contentUrl') or enc.get('url') or ''
                        if enc_url:
                            resolved = urllib.parse.urljoin(base_url, enc_url)
                            if resolved.rstrip('/') != base_url.rstrip('/'):
                                if 'audio' in item_type:
                                    found_audio.append(resolved)
                                else:
                                    found_video.append(resolved)
    return found_audio, found_video


def extract_media_from_scripts(html, base_url):
    """Scan inline scripts for media URLs / API references."""
    found = {'audio': [], 'video': [], 'image': []}
    for m in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
        text = m.group(1)
        # Direct audio/video file URLs
        for fm in re.finditer(
                r'https?://[^\s"\'<>\\]+\.(?:mp3|wav|m4a|aac|flac|ogg|opus|weba|oga)',
                text, re.IGNORECASE):
            u = fm.group(0).rstrip('.,;:!?)]}\'"')
            if u not in found['audio']:
                found['audio'].append(u)
        for fm in re.finditer(
                r'https?://[^\s"\'<>\\]+\.(?:mp4|webm|m3u8|ogv|mov|mkv)',
                text, re.IGNORECASE):
            u = fm.group(0).rstrip('.,;:!?)]}\'"')
            if u not in found['video']:
                found['video'].append(u)
        # JSON-LD / songData style URLs with preview/audio keywords
        for fm in re.finditer(r'["\'](https?://[^"\']*(?:preview|audio|stream|sound|track)[^"\']*)["\']',
                              text, re.IGNORECASE):
            u = fm.group(1)
            if any(ext in u.lower() for ext in ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg')):
                if u not in found['audio']:
                    found['audio'].append(u)
            elif any(ext in u.lower() for ext in ('.mp4', '.webm', '.m3u8', '.mov')):
                if u not in found['video']:
                    found['video'].append(u)
    return found


def deep_scan(parser, html=''):
    """Scan external script/JS files for additional media URLs."""
    # Scan player.js and similar files that often contain video URLs
    text_sources = []
    for s in parser.external_scripts:
        if any(k in s.lower() for k in (
                'player', 'video', 'embed', 'stream', 'play')):
            text_sources.append(s)
    for s in parser.external_styles:
        text_sources.append(s)

    # Collect stream domain from player scripts
    stream_domain = None
    for src in text_sources[:10]:  # limit to 10 files
        text = fetch_text(src)
        if not text:
            continue

        # Find stream domain (e.g. StreamDomain = 'https://...')
        m = re.search(r'StreamDomain\s*=\s*["\'](https?://[^"\']+)["\']', text, re.I)
        if m:
            stream_domain = m.group(1).rstrip('/')

        # Find video URLs embedded in JS/CSS
        for m in re.finditer(
                r'https?://[^\s"\'<>\\]+\.(?:mp4|m3u8|webm|ogg|ogv|mov|m4v|mkv|avi)(?:[^\s"\'<>\\]*)',
                text, re.IGNORECASE):
            parser._check_extension(m.group(0))

        # Find video URLs in quotes (may not have extension)
        for m in re.finditer(
                r'["\'](https?://[^"\']+)["\']', text):
            candidate = m.group(1)
            lowered = candidate.lower()
            if (any(host in lowered for host in VIDEO_HOST_DOMAINS)
                    and not any(b in lowered for b in IFRAME_BLOCKLIST)):
                parser._add_video(candidate)

        # Find audio URLs
        for m in re.finditer(
                r'https?://[^\s"\'<>\\]+\.(?:mp3|wav|m4a|aac|flac|opus|weba|oga)(?:[^\s"\'<>\\]*)',
                text, re.IGNORECASE):
            parser._add_audio(m.group(0))

        # Find image URLs from CSS url(...)
        for m in re.finditer(r'url\(\s*(["\']?)(.*?)\1\s*\)', text):
            parser._add_image(m.group(2))

    # Find IndStreamPlayerConfigs in page HTML and build video URL
    if stream_domain:
        for m in re.finditer(
                r'IndStreamPlayerConfigs\s*=\s*\{[^}]+\}', html):
            config = m.group(0)
            src_m = re.search(r'src\s*:\s*["\']([^"\']+)["\']', config)
            if src_m:
                video_url = f'{stream_domain}/play/{src_m.group(1)}'
                parser._add_video(video_url)

    return parser


def resolve_direct_links(url):
    """Use yt-dlp to resolve direct playable/downloadable media URLs."""
    if not YTDLP_AVAILABLE:
        return None

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'format': 'best',
        'noplaylist': True,
        'socket_timeout': 20,
        # Impersonate a real browser to bypass Cloudflare anti-bot challenges
        'extractor_args': {'generic': {'impersonate': ['chrome']}},
        'impersonate': 'chrome',
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None

            result = {
                'title': info.get('title') or '',
                'thumbnail': info.get('thumbnail') or '',
                'duration': info.get('duration') or 0,
                'formats': [],
            }

            # Collect best video formats
            formats = info.get('formats') or []
            seen = set()
            for f in formats:
                url = f.get('url') or ''
                ext = f.get('ext') or ''
                height = f.get('height') or 0
                vcodec = f.get('vcodec') or 'none'
                acodec = f.get('acodec') or 'none'
                if not url or url in seen:
                    continue
                seen.add(url)
                if vcodec != 'none':
                    result['formats'].append({
                        'type': 'video',
                        'url': url,
                        'ext': ext,
                        'height': height,
                        'has_audio': acodec != 'none',
                    })
                elif acodec != 'none':
                    result['formats'].append({
                        'type': 'audio',
                        'url': url,
                        'ext': ext,
                        'height': 0,
                        'has_audio': True,
                    })

            # Sort video by quality, audio separately
            result['formats'].sort(key=lambda x: (x['type'] != 'video', -x['height']))
            return result
    except Exception:
        return None


def extract_artlist_audio(html, base_url):
    """Extract artlist.io audio file URLs from base64-encoded cms-public-artifacts paths."""
    found = []
    # Pattern: https://cms-public-artifacts.artlist.io/<base64-encoded-path>
    for m in re.finditer(
            r'https?://cms-public-artifacts\.artlist\.io/([A-Za-z0-9+/=]+)',
            html):
        b64 = m.group(1)
        try:
            # Decode base64 to get the actual file path
            decoded = base64.b64decode(b64).decode('utf-8', errors='ignore')
            # If decoded path points to an audio file, build full URL
            if any(ext in decoded.lower() for ext in ('.aac', '.mp3', '.wav', '.m4a', '.flac', '.ogg')):
                full_url = 'https://cms-public-artifacts.artlist.io/' + decoded
                if full_url not in found:
                    found.append(full_url)
        except Exception:
            continue
    return found


def scrape(url):
    """Scrape a URL and return media URLs."""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    html = fetch_page(url)
    parser = MediaParser(url)
    parser.feed(html)
    deep_scan(parser, html)

    # Extract audio/video URLs from JSON-LD (schema.org) embedded in the page
    jsonld_audio, jsonld_video = extract_jsonld_media(html, url)
    for a in jsonld_audio:
        if a not in parser.audios:
            parser.audios.append(a)
    for v in jsonld_video:
        if v not in parser.videos:
            parser.videos.append(v)

    # Scan inline scripts for additional media URLs
    script_media = extract_media_from_scripts(html, url)
    for a in script_media['audio']:
        if a not in parser.audios:
            parser.audios.append(a)
    for v in script_media['video']:
        if v not in parser.videos:
            parser.videos.append(v)

    # Special handling for artlist.io - decode base64 audio URLs
    if 'artlist.io' in url:
        artlist_audio = extract_artlist_audio(html, url)
        for a in artlist_audio:
            if a not in parser.audios:
                parser.audios.append(a)

    # Try to resolve direct playable/downloadable links with yt-dlp
    direct = resolve_direct_links(url)

    return {
        'url': url,
        'title': extract_title(html),
        'videos': parser.videos,
        'audios': parser.audios,
        'images': parser.images,
        'direct': direct,
        'ytdlp_available': YTDLP_AVAILABLE,
    }


class ScraperHandler(BaseHTTPRequestHandler):
    server_version = 'MediaScraper/1.0'

    def log_message(self, fmt, *args):
        print(f'[server] {self.address_string()} - {fmt % args}')

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in ('/', '/index.html'):
            self._serve_file('index.html', 'text/html; charset=utf-8')
        elif parsed.path == '/api/scrape':
            self._handle_scrape(parsed)
        else:
            self.send_error(404, 'Not Found')

    def _serve_file(self, filename, content_type):
        path = os.path.join(BASE_DIR, filename)
        try:
            with open(path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, f'{filename} not found')

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def _handle_scrape(self, parsed):
        query = urllib.parse.parse_qs(parsed.query)
        url = query.get('url', [''])[0].strip()

        if not url:
            self._send_json(
                {'error': 'URL is required. Example: /api/scrape?url=https://example.com'},
                400)
            return

        try:
            print(f'[scrape] Fetching: {url}')
            result = scrape(url)
            print(f'[scrape] Found: {len(result["videos"])} videos, '
                  f'{len(result["audios"])} audios, {len(result["images"])} images')
            self._send_json(result)
        except Exception as e:
            print(f'[scrape] Error: {e}')
            self._send_json({'error': str(e)}, 500)


def main():
    server = HTTPServer(('127.0.0.1', PORT), ScraperHandler)
    print('=' * 52)
    print('   Media Scraper Tool')
    print('=' * 52)
    print(f'   Open your browser:  http://localhost:{PORT}')
    print('   Press Ctrl+C to stop the server.')
    print('=' * 52)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n   Server stopped. Goodbye!')
        server.server_close()


if __name__ == '__main__':
    main()