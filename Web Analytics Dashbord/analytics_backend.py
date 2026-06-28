import datetime
import html
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlparse

import requests
from flask import jsonify, request, send_from_directory

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 FavoriteWebAnalyzer/1.0"
MAX_BYTES = 900_000


def init_routes(app, base_dir):
    analytics_dir = base_dir / "Web Analytics Dashbord"

    @app.route("/analytics")
    @app.route("/analytics/")
    def analytics_home():
        return send_from_directory(analytics_dir, "index.html")

    @app.route("/analytics/<path:filename>")
    def analytics_asset(filename):
        return send_from_directory(analytics_dir, filename)

    @app.route("/api/analytics/scan", methods=["POST"])
    def analytics_scan():
        payload = request.get_json(silent=True) or {}
        domain = (payload.get("domain") or "").strip()
        limit = max(1, min(int(payload.get("limit") or 15), 30))
        try:
            result = scan_website(domain, limit)
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Scan failed: {exc}"}), 502

    @app.route("/api/analytics/article", methods=["POST"])
    def analytics_article():
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
        keyword = (payload.get("keyword") or "").strip()
        content = payload.get("content") or ""
        try:
            result = analyze_article_input(url, keyword, content)
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Article analysis failed: {exc}"}), 502


def scan_website(raw_domain, limit):
    url = normalize_url(raw_domain)
    host = urlparse(url).hostname or ""
    availability = check_domain_availability(host)


    if availability["dns"] == "resolves":
        ensure_public_host(host)

    try:
        home = fetch_url_with_fallback(url)
    except ValueError as exc:
        return unavailable_domain_result(host, url, availability, str(exc))

    final_url = home["url"]
    base_host = urlparse(final_url).hostname or host
    if base_host != host:
        availability = check_domain_availability(base_host)

    robots = probe_text(urljoin(final_url, "/robots.txt"))
    sitemap_url = discover_sitemap(final_url, robots)
    sitemap_urls = load_sitemap_urls(sitemap_url, final_url) if sitemap_url else []
    discovered = sitemap_urls or discover_links(final_url, home["text"], base_host)
    urls = unique_urls([final_url] + discovered)[:limit]

    pages = []
    for page_url in urls:
        try:
            page = fetch_url(page_url)
            pages.append(analyze_page(page_url, page["text"], page["elapsed_ms"]))
        except Exception:
            continue

    if not pages:
        pages = [analyze_page(final_url, home["text"], home["elapsed_ms"])]

    technology = detect_technology(home["text"], home["headers"])
    hosting = detect_hosting(base_host, home["headers"])
    scores = aggregate_scores(pages, home["elapsed_ms"], home["text"], home["headers"], robots, sitemap_url, hosting)
    good, issues, actions = summarize_site(pages, technology, robots, sitemap_url, scores)

    return {
        "domain": base_host,
        "normalized_url": final_url,
        "scanned_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "hosting": hosting,
        "technology": technology,
        "discovery": {
            "robots": "Found" if robots else "Not found",
            "sitemap": sitemap_url or "Not found",
        },
        "availability": availability,
        "scores": scores,
        "good": good,
        "issues": issues,
        "actions": actions,
        "pages": pages,
    }


def analyze_article_input(url, keyword, content):
    page_url = url or "Direct pasted article"
    html_text = content
    elapsed = 0
    headers = {}
    host = "Direct paste"

    if url:
        normalized = normalize_url(url)
        host = urlparse(normalized).hostname or ""
        ensure_public_host(host)
        fetched = fetch_url_with_fallback(normalized)
        html_text = fetched["text"] if not content.strip() else content
        elapsed = fetched["elapsed_ms"]
        headers = fetched["headers"]
        page_url = fetched["url"]

    page = analyze_page(page_url, html_text, elapsed, keyword=keyword)
    scores = {
        "seo": page["score"],
        "speed": max(35, min(100, 95 - int(elapsed / 90))),
        "technical": 76 if url else 58,
        "content": page["content_score"],
        "spam": estimate_spam_score([page], html_text, headers, "", "", {"ssl": "Checked" if url else "Not checked"}),
    }
    return {
        "domain": host,
        "url": page_url,
        "normalized_url": page_url,
        "scanned_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "hosting": {"server": headers.get("server", "Not checked"), "ip": "Not checked", "ssl": "Checked" if url.startswith("https") else "Not checked"},
        "technology": {"cms": "Article only", "stack": tech["stack"], "theme": tech["theme"], "items": tech["items"]},
        "discovery": {"robots": "Not checked", "sitemap": "Not checked"},
        "availability": {"status": "Not checked", "message": "Article-only mode does not check domain availability.", "dns": "Not checked", "rdap": "Not checked"},
        "scores": scores,
        "good": page["good"],
        "issues": page["issues"],
        "actions": page["actions"],
        "pages": [page],
    }


def normalize_url(value):
    if not value:
        raise ValueError("Please enter a domain or URL.")
    value = value.strip()
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    parsed = urlparse(value)
    if not parsed.hostname:
        raise ValueError("Invalid domain or URL.")
    return value


def ensure_public_host(host):
    blocked = {"localhost", "127.0.0.1", "0.0.0.0"}
    if host.lower() in blocked:
        raise ValueError("Local/private addresses are blocked for public safety.")
    try:
        for _, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError("Private or reserved network targets are blocked.")
    except socket.gaierror:
        raise ValueError("Domain could not be resolved.")


def request_headers():
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
        "Cache-Control": "no-cache",
    }


def check_domain_availability(host):
    result = {
        "status": "Unknown",
        "message": "Domain availability could not be confirmed.",
        "dns": "Not checked",
        "rdap": "Not checked",
    }
    try:
        socket.getaddrinfo(host, None)
        result["dns"] = "resolves"
    except socket.gaierror:
        result["dns"] = "no_dns"
    except Exception:
        result["dns"] = "unknown"

    try:
        response = requests.get(
            f"https://rdap.org/domain/{host}",
            timeout=8,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rdap+json, application/json;q=0.9, */*;q=0.8"},
        )
        if response.status_code == 404:
            result["rdap"] = "not_found"
        elif response.ok:
            result["rdap"] = "registered"
        else:
            result["rdap"] = f"status_{response.status_code}"
    except Exception:
        result["rdap"] = "unknown"

    if result["rdap"] == "not_found" and result["dns"] == "no_dns":
        result["status"] = "Possibly available"
        result["message"] = "No DNS and no RDAP registration were found. Check a registrar before purchase."
    elif result["rdap"] == "registered":
        result["status"] = "Registered"
        result["message"] = "Domain appears registered. If no website loads, it may be parked, offline, or not configured."
    elif result["dns"] == "no_dns":
        result["status"] = "Maybe available"
        result["message"] = "No DNS was found, but RDAP did not confirm availability. Check a registrar."
    elif result["dns"] == "resolves":
        result["status"] = "Registered / DNS active"
        result["message"] = "Domain has DNS records. Website may still be offline or blocking scanners."
    return result


def unavailable_domain_result(host, url, availability, error_message):
    is_available = availability.get("status") in {"Possibly available", "Maybe available"}
    spam = 0 if is_available else 35
    return {
        "domain": host,
        "normalized_url": url,
        "scanned_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "hosting": {"server": "No website detected", "ip": "No DNS" if availability.get("dns") == "no_dns" else "Unknown", "ssl": "Not checked"},
        "technology": {"cms": "No website detected", "stack": "Unknown", "theme": "Unknown", "items": []},
        "discovery": {"robots": "Not found", "sitemap": "Not found"},
        "availability": availability,
        "scores": {"seo": 0, "speed": 0, "technical": 0, "content": 0, "spam": spam},
        "good": [availability.get("message", "Domain availability checked")],
        "issues": ["No active website could be fetched", error_message],
        "actions": ["If you own this domain, configure DNS/hosting and add an SSL certificate.", "If you want to buy it, confirm availability at a domain registrar before purchase."],
        "pages": [],
    }


def candidate_urls(url):
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        return [url]

    host_variants = [host]
    if host.startswith("www."):
        host_variants.append(host[4:])
    else:
        host_variants.append(f"www.{host}")

    urls = []
    for candidate_host in host_variants:
        netloc = candidate_host
        if parsed.port:
            netloc = f"{candidate_host}:{parsed.port}"
        for scheme in [parsed.scheme or "https", "http"]:
            candidate = parsed._replace(scheme=scheme, netloc=netloc).geturl()
            if candidate not in urls:
                urls.append(candidate)
    return urls


def fetch_url_with_fallback(url):
    last_error = None
    for candidate in candidate_urls(url):
        candidate_host = urlparse(candidate).hostname or ""
        try:
            ensure_public_host(candidate_host)
            return fetch_url(candidate)
        except ValueError as exc:
            last_error = exc
            if "Private or reserved" in str(exc) or "Local/private" in str(exc):
                raise
        except requests.RequestException as exc:
            last_error = exc
            continue
    detail = f" Last error: {last_error}" if last_error else ""
    raise ValueError(f"Could not fetch website after trying non-www/www and HTTP/HTTPS variants.{detail}")


def fetch_url(url):
    started = time.perf_counter()
    response = requests.get(url, timeout=15, allow_redirects=True, headers=request_headers())
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "xml" not in content_type and response.text.strip().startswith("<") is False:
        raise ValueError("Target URL did not return an HTML page.")
    text = response.text[:MAX_BYTES]
    return {"url": response.url, "text": text, "headers": {k.lower(): v for k, v in response.headers.items()}, "elapsed_ms": elapsed_ms}


def probe_text(url):
    try:
        response = requests.get(url, timeout=7, headers=request_headers())
        if response.status_code < 400:
            return response.text[:250_000]
    except Exception:
        return ""
    return ""


def discover_sitemap(final_url, robots):
    match = re.search(r"(?im)^sitemap:\s*(\S+)", robots or "")
    if match:
        return match.group(1).strip()
    candidate = urljoin(final_url, "/sitemap.xml")
    if probe_text(candidate):
        return candidate
    return ""


def load_sitemap_urls(sitemap_url, final_url):
    text = probe_text(sitemap_url)
    urls = re.findall(r"<loc>\s*([^<]+)\s*</loc>", text, re.I)
    base_host = urlparse(final_url).hostname
    return [html.unescape(u.strip()) for u in urls if urlparse(html.unescape(u.strip())).hostname == base_host]


def discover_links(final_url, text, base_host):
    links = re.findall(r"<a[^>]+href=[\"']([^\"'#]+)[\"']", text, re.I)
    resolved = []
    for link in links:
        absolute = urljoin(final_url, html.unescape(link.strip()))
        parsed = urlparse(absolute)
        if parsed.scheme in {"http", "https"} and parsed.hostname == base_host:
            resolved.append(absolute.split("#")[0])
    article_like = [u for u in resolved if re.search(r"/(20\d{2}|blog|post|article|news|[a-z0-9-]{18,})", u, re.I)]
    return article_like or resolved


def unique_urls(urls):
    seen = set()
    clean = []
    for url in urls:
        url = url.rstrip("/")
        if url not in seen:
            seen.add(url)
            clean.append(url)
    return clean


def analyze_page(url, text, load_ms, keyword=""):
    title = first_match(r"<title[^>]*>(.*?)</title>", text)
    description = meta_content(text, "description")
    canonical = first_match(r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']+)", text)
    h1_count = len(re.findall(r"<h1\b", text, re.I))
    h2_count = len(re.findall(r"<h2\b", text, re.I))
    images = re.findall(r"<img\b[^>]*>", text, re.I)
    missing_alt = len([img for img in images if not re.search(r"\balt=[\"'][^\"']+[\"']", img, re.I)])
    schema = bool(re.search(r"application/ld\+json|itemscope|schema.org", text, re.I))
    og = bool(re.search(r"property=[\"']og:", text, re.I))
    plain = visible_text(text)
    words = len(re.findall(r"\b\w+\b", plain))
    links = len(re.findall(r"<a\b", text, re.I))

    good, issues, actions = [], [], []
    score = 40
    content_score = 35

    if 30 <= len(title) <= 65:
        score += 14; good.append("Title length is search-friendly")
    elif title:
        issues.append("Title length is not ideal"); actions.append("Keep title between 30 and 65 characters")
    else:
        issues.append("Missing title tag"); actions.append("Add a unique SEO title")

    if 70 <= len(description) <= 160:
        score += 14; good.append("Meta description is present")
    else:
        issues.append("Meta description missing or wrong length"); actions.append("Write a 70-160 character meta description")

    if h1_count == 1:
        score += 10; good.append("Exactly one H1 found")
    else:
        issues.append(f"H1 count is {h1_count}"); actions.append("Use one clear H1 per page")

    if h2_count >= 2:
        score += 7; good.append("Page has section headings")
    else:
        actions.append("Add H2/H3 sections for better content structure")

    if canonical:
        score += 7; good.append("Canonical URL found")
    else:
        issues.append("Canonical tag missing"); actions.append("Add canonical URL to prevent duplicate SEO signals")

    if schema:
        score += 7; good.append("Structured data detected")
    else:
        actions.append("Add Article, FAQ, Product or Organization schema where relevant")

    if og:
        score += 5; good.append("Open Graph social tags detected")
    else:
        actions.append("Add Open Graph tags for better social sharing")

    if images and missing_alt:
        issues.append(f"{missing_alt} image(s) missing alt text"); actions.append("Add descriptive alt text to every useful image")
    elif images:
        score += 5; good.append("Images include alt text")

    if words >= 700:
        content_score += 35; good.append("Strong content depth")
    elif words >= 300:
        content_score += 22; good.append("Useful content length")
    else:
        issues.append("Content looks thin"); actions.append("Expand content with examples, FAQs, comparisons and original insight")

    if links >= 3:
        content_score += 10; good.append("Internal/external links detected")
    else:
        actions.append("Add relevant internal links and trusted external references")

    if keyword:
        body = f"{title} {description} {plain}".lower()
        if keyword.lower() in body:
            score += 8; good.append("Focus keyword appears in the article")
        else:
            issues.append("Focus keyword not found"); actions.append("Use the focus keyword naturally in title, intro and headings")

    if load_ms <= 1500:
        good.append("Initial HTML response is fast")
    elif load_ms > 3500:
        issues.append("Slow initial HTML response"); actions.append("Improve hosting, caching or heavy server processing")

    score = max(1, min(100, score))
    content_score = max(1, min(100, content_score))
    return {
        "url": url,
        "title": clean(title) or url,
        "description": clean(description),
        "score": score,
        "content_score": content_score,
        "words": words,
        "h1_count": h1_count,
        "h2_count": h2_count,
        "images_missing_alt": missing_alt,
        "load_ms": load_ms,
        "good": good[:8],
        "issues": issues[:8],
        "actions": unique_text(actions)[:10],
    }


def aggregate_scores(pages, home_ms, html_text="", headers=None, robots="", sitemap_url="", hosting=None):
    headers = headers or {}
    hosting = hosting or {}
    seo = int(sum(p["score"] for p in pages) / len(pages))
    content = int(sum(p["content_score"] for p in pages) / len(pages))
    speed = max(25, min(100, 98 - int(home_ms / 75)))
    technical = seo
    if any("Canonical tag missing" in p["issues"] for p in pages):
        technical -= 8
    if any("H1 count" in issue for p in pages for issue in p["issues"]):
        technical -= 7
    return {
        "seo": seo,
        "speed": speed,
        "technical": max(1, min(100, technical)),
        "content": content,
        "spam": estimate_spam_score(pages, html_text, headers, robots, sitemap_url, hosting),
    }


def estimate_spam_score(pages, html_text="", headers=None, robots="", sitemap_url="", hosting=None):
    headers = headers or {}
    hosting = hosting or {}
    lower = (html_text or "").lower()
    score = 5
    if not robots:
        score += 8
    if not sitemap_url:
        score += 6
    if not any("Meta description is present" in p.get("good", []) for p in pages):
        score += 8
    if any(p.get("words", 0) < 120 for p in pages):
        score += 10
    if any(p.get("score", 0) < 45 for p in pages):
        score += 10
    if lower.count("adsbygoogle") > 3:
        score += 8
    if re.search(r"\b(casino|betting|loan|payday|viagra|adult|crypto bonus|free money)\b", lower, re.I):
        score += 14
    if hosting.get("ssl") == "HTTPS not confirmed":
        score += 4
    if any("Slow initial HTML response" in p.get("issues", []) for p in pages):
        score += 6
    outbound_links = len(re.findall(r"<a[^>]+href=[\"']https?://", html_text or "", re.I))
    words = sum(p.get("words", 0) for p in pages) or 1
    if outbound_links > 25 and words < 800:
        score += 12
    return max(0, min(100, int(score)))


def summarize_site(pages, technology, robots, sitemap_url, scores):
    good = []
    issues = []
    actions = []
    if sitemap_url:
        good.append("Sitemap discovered")
    else:
        issues.append("Sitemap not found"); actions.append("Create and submit sitemap.xml in Google Search Console")
    if robots:
        good.append("robots.txt found")
    else:
        issues.append("robots.txt not found"); actions.append("Add robots.txt with sitemap reference")
    if technology["cms"] != "Unknown":
        good.append(f"CMS/platform detected: {technology['cms']}")
    if scores["speed"] >= 80:
        good.append("Fast initial response")
    else:
        issues.append("Speed score needs improvement"); actions.append("Enable caching, compress assets and reduce render-blocking scripts")
    if scores.get("spam", 0) <= 20:
        good.append("Low spam-risk signals")
    elif scores.get("spam", 0) >= 60:
        issues.append("High spam-risk signals detected"); actions.append("Reduce thin content, risky keywords, excessive outbound links and ad clutter")
    for page in pages:
        issues.extend(page["issues"][:2])
        actions.extend(page["actions"][:2])
    return unique_text(good)[:8], unique_text(issues)[:10], unique_text(actions)[:12]


def detect_technology(text, headers):
    lower = text.lower()
    items = []
    cms = "Unknown"
    stack = "Unknown"
    theme = "Unknown"

    has_wordpress = bool(re.search(r"wp-content/(themes|plugins|uploads)|wp-includes|wp-json|<meta[^>]+content=[\"']WordPress", text, re.I))
    if has_wordpress:
        cms = "WordPress"; items.append("WordPress")
        theme_match = re.search(r"wp-content/themes/([^/'\"?]+)", text, re.I)
        if theme_match:
            theme = theme_match.group(1)
            items.append(f"WordPress theme: {theme}")
    if "blogger.com" in lower or "blogspot" in lower:
        cms = "Blogger"; items.append("Blogger")
        template = first_match(r"<meta[^>]+name=[\"']template[\"'][^>]+content=[\"']([^\"']+)", text)
        if template:
            theme = template
            items.append(f"Blogger template: {theme}")
    if "shopify" in lower:
        cms = "Shopify"; items.append("Shopify")
        shopify_theme = first_match(r"Shopify\.theme\s*=\s*\{[^}]*name[\"']?\s*:\s*[\"']([^\"']+)", text)
        if shopify_theme:
            theme = shopify_theme
            items.append(f"Shopify theme: {theme}")
    if "wixstatic" in lower:
        cms = "Wix"; items.append("Wix")
    if "cdn.shopify" in lower: items.append("Shopify CDN")
    if "googletagmanager" in lower: items.append("Google Tag Manager")
    if "google-analytics" in lower or "gtag/js" in lower: items.append("Google Analytics")
    if "adsbygoogle" in lower: items.append("Google AdSense")

    powered_by = headers.get("x-powered-by", "")
    server = headers.get("server", "")
    header_blob = f"{powered_by} {server}".lower()
    if "next.js" in lower or "__next" in lower:
        stack = "Next.js / React"; items.append("Next.js")
    elif re.search(r"data-reactroot|__react|_reactRootContainer|react(?:\.production)?\.min\.js|react-dom", text, re.I):
        stack = "React JS"; items.append("React JS")
    if "express" in header_blob or "node" in header_blob or "node.js" in lower or "nodejs" in lower:
        stack = "Node.js" if stack == "Unknown" else f"{stack} + Node.js"
        items.append("Node.js")
    if "x-powered-by" in headers and "php" in powered_by.lower():
        stack = "PHP" if stack == "Unknown" else f"{stack} + PHP"
        items.append("PHP")
    if "laravel" in lower or "laravel_session" in lower or "x-powered-by" in headers and "laravel" in powered_by.lower():
        stack = "Laravel / PHP"
        items.append("Laravel")
    if "php" in lower and stack == "Unknown":
        stack = "PHP"
        items.append("PHP hints")

    if server: items.append(f"Server: {server}")
    if powered_by: items.append(f"Powered by: {powered_by}")
    generator = meta_content(text, "generator")
    if generator:
        items.append(f"Generator: {generator}")
        if theme == "Unknown" and cms == "Blogger":
            theme = generator

    return {"cms": cms, "stack": stack, "theme": theme, "items": unique_text(items)}


def detect_hosting(host, headers):
    ip = "Unknown"
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        pass
    ssl_state = "Not checked"
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                ssl_state = "Valid HTTPS"
    except Exception:
        ssl_state = "HTTPS not confirmed"
    server = headers.get("server", "Unknown")
    cf = headers.get("cf-ray") or headers.get("cf-cache-status")
    if cf and "Cloudflare" not in server:
        server = f"{server} / Cloudflare"
    return {"ip": ip, "server": server, "ssl": ssl_state}


def first_match(pattern, text):
    match = re.search(pattern, text, re.I | re.S)
    return clean(match.group(1)) if match else ""


def meta_content(text, name):
    pattern = rf"<meta[^>]+name=[\"']{re.escape(name)}[\"'][^>]+content=[\"']([^\"']*)[\"']"
    value = first_match(pattern, text)
    if value:
        return value
    pattern = rf"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]+name=[\"']{re.escape(name)}[\"']"
    return first_match(pattern, text)


def visible_text(text):
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return clean(html.unescape(text))


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def unique_text(values):
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out

