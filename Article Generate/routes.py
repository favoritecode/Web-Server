from flask import jsonify, request, send_from_directory, session
from pathlib import Path
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
import urllib.parse

BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompts" / "bangla-education-article.txt"
MAX_TITLE_LENGTH = 180
MAX_CONTEXT_LENGTH = 2200
DEFAULT_CLOUDFLARE_AI_MODEL = "@cf/meta/llama-3.2-3b-instruct"
CLOUDFLARE_AI_ENDPOINT = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
LAST_CLOUDFLARE_ERROR = ""
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_NVIDIA_MODEL = "meta/llama-3.1-70b-instruct"
DEFAULT_NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_CATEGORY = "general"
DEFAULT_TARGET_AUDIENCE = "general readers and viewers"
DEFAULT_TONE = "clear, useful, trustworthy, and engaging"
DEFAULT_WORD_COUNT = '250 \u09a5\u09c7\u0995\u09c7 350 \u09ac\u09be\u0982\u09b2\u09be \u09b6\u09ac\u09cd\u09a6'
DEFAULT_PRODUCT_CONTEXT = "No fixed brand or product context. Understand the user title and write for the likely audience. If the title mentions a brand, product, service, tutorial, review, news, offer, lifestyle, education, technology, health, entertainment, or business topic, follow that topic only."
BANNED_PHRASES = [
    "পরিষ্কার ধারণা থাকলে সিদ্ধান্ত নেওয়া",
    "পরিষ্কার ধারণা থাকলে সিদ্ধান্ত নেয়া",
    "পরিকল্পনা করা এবং বাস্তবে ভালো ফল",
    "অপ্রয়োজনীয় বিভ্রান্তি কমে যায়",
    "নিজের প্রয়োজন, সময়, budget",
    "trusted source",
    "better engagement",
    "long-term result",
    "সহজ comparison",
    "ছোট checklist",
]
UNSAFE_CLAIMS = ["নিশ্চিত A+", "১০০% ফল", "100% ফল", "সব সমস্যা শেষ", "কোচিং সম্পূর্ণ অপ্রয়োজনীয়", "কোচিং সম্পূর্ণ অপ্রয়োজনীয়"]
ALLOWED_ENGLISH_WORDS = {"qr", "scan", "pause", "replay", "video", "technique", "easy", "education", "h1", "seo", "url"}

DEFAULT_SYSTEM_PROMPT = """You are a Bangladesh-focused Bengali content writer for general SEO, social posts, and YouTube-friendly descriptions.

You are not tied to any fixed brand, company, product, or education topic. First understand the user's title, then infer the likely audience, search intent, and content format.

Rules:
- Output only the final post body.
- Use the exact title once as an H1 heading.
- Write 250 to 350 Bangla words; never exceed 500 words.
- Use 3 to 5 focused paragraphs.
- Do not include tags or hashtags inside the post body.
- Do not use keyword stuffing, comma-separated keyword lists, unsupported guarantees, or unnecessary English words.
- If the title asks for shortcuts, tips, tools, list, tutorial, how-to, or useful tricks, give concrete examples and actionable points.
- For Windows shortcut titles, mention relevant examples such as Win + E, Win + D, Win + V, Win + Shift + S, Alt + Tab, Ctrl + Shift + Esc, and Win + L when useful.
- Keep the writing useful for website posts, Facebook captions, and YouTube descriptions.
"""



def _secret_value(name, default=""):
    value = os.environ.get(name)
    if value:
        return value
    try:
        import favoriteweb_local_secrets as local_secrets
    except Exception:
        return default
    return getattr(local_secrets, name, default)


def _read_text(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return default


def system_prompt():
    return _read_text(PROMPT_PATH, DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT


def cloudflare_system_prompt():
    return (
        "You are a professional Bengali content writer for Bangladesh. "
        "You are not tied to any fixed brand, company, product, or education topic. "
        "Understand the given title first, infer the likely audience and search intent, then write a useful SEO and YouTube-friendly Bengali post. "
        "Return only the final post body. Use the exact title only once as H1. Do not put tags or hashtags inside the body. "
        "If the title asks for shortcuts, tips, tools, how-to, list, tutorial, or tricks, include concrete examples and practical steps. "
        "For Windows shortcut titles, include real shortcuts such as Win + E, Win + D, Win + V, Win + Shift + S, Alt + Tab, Ctrl + Shift + Esc, and Win + L where relevant. "
        "Do not use keyword stuffing, generic filler, repeated title, unsupported guarantees, or unnecessary English words. "
        "Avoid these phrases: trusted source, better engagement, long-term result, budget, checklist, comparison. "
        "Write 250 to 350 Bengali words, maximum 500 words, in 3 to 5 focused paragraphs."
    )


def _clean_text(value, max_len=500):
    value = unicodedata.normalize("NFC", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()[:max_len]


def _clean_title(title):
    return _clean_text(title, MAX_TITLE_LENGTH)


def _has_bengali_script(text):
    return bool(re.search(r"[\u0980-\u09ff]", text or ""))


def _word_count(text):
    return len(re.findall(r"[\w\u0980-\u09ff]+", text or ""))


def _sentence_list(text):
    return [s.strip() for s in re.split(r"(?<=[।.!?])\s+", text or "") if s.strip()]


def _normalize_for_count(text):
    text = re.sub(r"[#*_`>\-]+", " ", text or "")
    text = re.sub(r"[^\w\u0980-\u09ff\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _title_repetition_count(title, article):
    title_norm = _normalize_for_count(title)
    article_norm = _normalize_for_count(article)
    return article_norm.count(title_norm) if title_norm else 0


def _meaningful_title_words(title):
    stop = {"এই", "ওই", "আর", "কিসের", "থাকলে", "হলে", "জন্য", "সাথে", "the", "and", "for", "with", "of"}
    words = re.findall(r"[\w\u0980-\u09ff]+", _normalize_for_count(title))
    return [w for w in words if len(w) > 2 and w not in stop]


def _english_words(text):
    return [w.lower() for w in re.findall(r"\b[A-Za-z][A-Za-z-]*\b", text or "")]


def _contains_any(text, variants):
    text = (text or "").lower()
    return any(v.lower() in text for v in variants)



def validate_article(article, title, min_words=200, max_words=500):
    article = article or ""
    reasons = []
    banned = [phrase for phrase in BANNED_PHRASES if phrase.lower() in article.lower()]
    unsafe = [phrase for phrase in UNSAFE_CLAIMS if phrase.lower() in article.lower()]
    reasons.extend([f"Banned phrase found: {phrase}" for phrase in banned])
    reasons.extend([f"Unsafe claim found: {phrase}" for phrase in unsafe])

    wc = _word_count(article)
    if wc < min_words:
        reasons.append(f"Post is too short: {wc} words")
    if max_words and wc > max_words:
        reasons.append(f"Post is too long: {wc} words")

    if title and not article.lstrip().startswith(f"# {title}"):
        reasons.append("Missing exact title H1 heading")

    title_count = _title_repetition_count(title, article)
    if title_count > 3:
        reasons.append(f"Title repeated too many times: {title_count}")

    sentences = _sentence_list(article)
    seen = set()
    duplicates = set()
    for sentence in sentences:
        key = _normalize_for_count(sentence)
        if len(key) < 24:
            continue
        if key in seen:
            duplicates.add(sentence)
        seen.add(key)
    if duplicates:
        reasons.append("Duplicate sentence found")

    english = [w for w in _english_words(article) if w not in ALLOWED_ENGLISH_WORDS]
    if _has_bengali_script(article) and english:
        ratio = len(english) / max(wc, 1)
        if len(english) > 80 or ratio > 0.35:
            reasons.append("Too many unnecessary English words in Bangla article")

    norm = _normalize_for_count(article)
    stuffing_exempt = {"ভিডিও", "শিক্ষক", "শিক্ষার্থী", "বই", "QR", "কোড", "সমাধান", "ইজি", "সিরিজ"}
    for word in _meaningful_title_words(title):
        if word in stuffing_exempt:
            continue
        count = len(re.findall(rf"\b{re.escape(word)}\b", norm))
        if count > 16:
            reasons.append(f"Possible keyword stuffing: {word}")
            break

    generic_markers = ["যেকোনো বিষয়ে", "সঠিক পরিকল্পনা", "স্মার্ট পদ্ধতি", "ভালো ফলাফল অর্জন"]
    if sum(1 for marker in generic_markers if marker in article) >= 2:
        reasons.append("Article still sounds generic")

    return {
        "isValid": not reasons,
        "reasons": reasons,
        "wordCount": wc,
        "titleRepetitionCount": title_count,
        "bannedPhrasesFound": banned,
    }


def _slugify(title):
    mapping = {
        "বই": "boi", "বইয়ের": "boiyer", "বইয়ের": "boiyer", "ভেতর": "vitor", "শিক্ষক": "shikkhok", "থাকলে": "thakle", "আর": "ar",
        "লেখাপড়া": "lekhapora", "লেখাপড়ায়": "lekhaporay", "লেখাপড়ায়": "lekhaporay", "পড়াশোনা": "porashona", "পড়াশোনা": "porashona",
        "প্রতিবন্ধকতা": "protibondhokota", "কিসের": "kiser", "QR": "qr", "কোড": "code", "স্ক্যান": "scan", "সমাধান": "somadhan",
        "ইজি": "easy", "সিরিজ": "series", "অভিভাবক": "ovivabok", "কোচিং": "coaching", "খরচ": "khoroch", "অঙ্ক": "onk",
    }
    words = re.findall(r"[A-Za-z0-9]+|[\u0980-\u09ff]+", title or "")
    slug_words = []
    for word in words:
        slug_words.append(mapping.get(word, word.lower() if re.match(r"^[A-Za-z0-9]+$", word) else "post"))
    slug = "-".join(slug_words)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:90] or "article"


def _metadata(title, article):
    clean_title = re.sub(r"^#\s*", "", title).strip()
    meta_title = clean_title[:68]
    first_para = " ".join([p.strip("# \n\r\t") for p in article.split("\n\n") if p.strip() and not p.lstrip().startswith("#")][:2])
    meta_description = re.sub(r"\s+", " ", first_para).strip()
    if len(meta_description) > 158:
        meta_description = meta_description[:157].rsplit(" ", 1)[0] + "।"
    return {"metaTitle": meta_title, "metaDescription": meta_description, "slug": _slugify(clean_title)}


def _settings_from_payload(data):
    title = _clean_title(data.get("title"))
    category = _clean_text(data.get("category") or DEFAULT_CATEGORY, 80)
    target = _clean_text(data.get("targetAudience") or DEFAULT_TARGET_AUDIENCE, 120)
    tone = _clean_text(data.get("tone") or DEFAULT_TONE, 160)
    word_count = _clean_text(data.get("wordCount") or DEFAULT_WORD_COUNT, 60)
    context = _clean_text(data.get("productContext") or DEFAULT_PRODUCT_CONTEXT, MAX_CONTEXT_LENGTH)
    return {"title": title, "category": category, "targetAudience": target, "tone": tone, "wordCount": word_count, "productContext": context}


def _build_compact_user_prompt(settings, validation_reasons=None):
    prompt = (
        f"Title: {settings['title']}\n"
        f"Category: {settings['category']}\n"
        f"Target audience: {settings['targetAudience']}\n"
        f"Tone: {settings['tone']}\n"
        "Length: 250 to 350 Bengali words, maximum 500 words, in 3 to 5 focused paragraphs.\n\n"
        f"Additional context:\n{settings['productContext']}\n\n"
        "Write a short SEO and YouTube-friendly Bengali post. Use the exact title only once as H1. "
        "First understand the title's real topic, audience, and search intent. "
        "If the title asks for shortcuts, tips, tools, list, tutorial, or how-to, give concrete examples and practical points; for Windows shortcuts include useful key combinations when relevant. "
        "Make every paragraph directly relevant to the title, category, audience, and context. "
        "Avoid generic SEO filler, repeated title, keyword stuffing, unsupported guarantees, and unnecessary English words. "
        "Return only the final post body. Do not include tags or hashtags in the body."
    )
    if validation_reasons:
        prompt += "\n\nPrevious draft failed validation: " + "; ".join(validation_reasons)
        prompt += " Rewrite the short post with more specific, title-relevant detail. Write 250 to 350 Bengali words, under 500 words."
    return prompt


def _build_user_prompt(settings, validation_reasons=None):
    prompt = (
        f"Title: {settings['title']}\n"
        f"Category: {settings['category']}\n"
        f"Target audience: {settings['targetAudience']}\n"
        f"Tone: {settings['tone']}\n"
        f"Desired length: {settings['wordCount']}\n"
        "Hard length requirement: write 250 to 350 Bengali words, maximum 500 words. Use 3 to 5 focused paragraphs.\n\n"
        f"Additional context:\n{settings['productContext']}\n\n"
        "Write a short SEO and YouTube-friendly Bengali post from this title. Understand the real meaning, likely reader problem, and search intent before writing. "
        "Use the exact title only once as the H1 heading; do not repeat the full title in body paragraphs. "
        "For shortcut, tips, tools, listicle, tutorial, or how-to titles, write concrete examples and useful steps instead of generic motivation. "
        "For Windows 11 shortcut titles, mention real shortcut examples like Win + E, Win + D, Win + V, Win + Shift + S, Alt + Tab, Ctrl + Shift + Esc, and Win + L when relevant. "
        "Write 250 to 350 words in Bengali script, never more than 500 words. Keep it useful, direct, and ready to copy. "
        "Do not use generic SEO filler, keyword stuffing, repeated title, unnecessary English words, tags, or hashtags inside the body."
    )
    if validation_reasons:
        prompt += "\n\nThe previous draft failed validation for these reasons: " + "; ".join(validation_reasons)
        prompt += " Rewrite the full short post. Remove generic filler, repetition and keyword stuffing. Keep every paragraph directly relevant to the title and given context. Write 250 to 350 words, under 500 words."
    return prompt


def _extract_output_text(data):
    output_text = data.get("output_text") or ""
    if output_text:
        return output_text.strip()
    parts = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                parts.append(content.get("text") or "")
    return "\n".join(parts).strip()


def _extract_chat_text(data):
    try:
        choice = (data.get("choices") or [])[0]
        message = choice.get("message") or {}
        return (message.get("content") or choice.get("text") or "").strip()
    except (AttributeError, IndexError):
        return ""


def _normalize_chat_api_url(api_url):
    api_url = (api_url or "").strip().rstrip("/")
    if not api_url:
        return ""
    if api_url.endswith("/chat/completions"):
        return api_url
    if api_url.endswith("/v1"):
        return api_url + "/chat/completions"
    return api_url


def _call_chat_completions(api_url, api_key, model, prompt, extra_headers=None):
    if not api_url or not api_key or not model:
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": cloudflare_system_prompt()},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.55,
        "top_p": 0.9,
        "max_tokens": 1300,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(api_url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=75) as resp:
            return _extract_chat_text(json.loads(resp.read().decode("utf-8", errors="replace")))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _extract_cloudflare_text(data):
    if not isinstance(data, dict):
        return ""
    result = data.get("result")
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        for key in ("response", "text", "output_text", "answer"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        chat_text = _extract_chat_text(result)
        if chat_text:
            return chat_text
        output_text = _extract_output_text(result)
        if output_text:
            return output_text
    for key in ("response", "text", "output_text", "answer"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _extract_chat_text(data) or _extract_output_text(data)


def _run_cloudflare_payload(api_url, api_token, payload):
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    global LAST_CLOUDFLARE_ERROR
    try:
        with urllib.request.urlopen(req, timeout=75) as resp:
            return _extract_cloudflare_text(json.loads(resp.read().decode("utf-8", errors="replace")))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        lower_body = body.lower()
        if exc.code == 429 or "daily free allocation" in lower_body or "4006" in lower_body:
            LAST_CLOUDFLARE_ERROR = "Cloudflare Workers AI free quota is exhausted. Please wait for reset or enable Workers Paid plan."
        elif exc.code in {401, 403}:
            LAST_CLOUDFLARE_ERROR = "Cloudflare Workers AI token is invalid or missing Workers AI permission."
        else:
            LAST_CLOUDFLARE_ERROR = f"Cloudflare Workers AI request failed with HTTP {exc.code}."
        return None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        if not LAST_CLOUDFLARE_ERROR:
            LAST_CLOUDFLARE_ERROR = f"Cloudflare Workers AI request failed: {type(exc).__name__}."
        return None


def _call_cloudflare_ai(prompt):
    global LAST_CLOUDFLARE_ERROR
    LAST_CLOUDFLARE_ERROR = ""
    account_id = (_secret_value("CLOUDFLARE_ACCOUNT_ID") or _secret_value("CF_ACCOUNT_ID") or "").strip()
    api_token = (_secret_value("CLOUDFLARE_API_TOKEN") or _secret_value("CF_API_TOKEN") or "").strip()
    model = (_secret_value("CLOUDFLARE_AI_MODEL", DEFAULT_CLOUDFLARE_AI_MODEL) or DEFAULT_CLOUDFLARE_AI_MODEL).strip()
    if not account_id or not api_token or not model:
        return None
    api_url = CLOUDFLARE_AI_ENDPOINT.format(
        account_id=urllib.parse.quote(account_id, safe=""),
        model=model,
    )
    messages_payload = {
        "messages": [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.55,
        "top_p": 0.9,
        "max_tokens": 1300,
        "max_completion_tokens": 1300,
    }
    text = _run_cloudflare_payload(api_url, api_token, messages_payload)
    if text:
        return text
    fallback_payload = {
        "prompt": f"{cloudflare_system_prompt()}\n\n{prompt}",
        "temperature": 0.55,
        "top_p": 0.9,
        "max_tokens": 1300,
        "max_completion_tokens": 1300,
    }
    return _run_cloudflare_payload(api_url, api_token, fallback_payload)


def _extract_gemini_text(data):
    try:
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
    except (AttributeError, IndexError):
        return ""


def _call_gemini(prompt):
    api_key = (_secret_value("GEMINI_API_KEY") or _secret_value("GOOGLE_AI_API_KEY") or "").strip()
    if not api_key:
        return None
    model = (_secret_value("GEMINI_MODEL", DEFAULT_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL).strip()
    api_url = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}".format(
        urllib.parse.quote(model, safe=""),
        urllib.parse.quote(api_key, safe=""),
    )
    payload = {
        "systemInstruction": {"parts": [{"text": cloudflare_system_prompt()}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.65, "topP": 0.9, "maxOutputTokens": 1300},
    }
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return _extract_gemini_text(json.loads(resp.read().decode("utf-8", errors="replace")))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _call_nvidia(prompt):
    api_key = (_secret_value("NVIDIA_API_KEY") or _secret_value("NVIDIA_NIM_API_KEY") or "").strip()
    if not api_key:
        return None
    api_url = _normalize_chat_api_url(_secret_value("NVIDIA_API_URL", DEFAULT_NVIDIA_API_URL) or DEFAULT_NVIDIA_API_URL)
    model = (_secret_value("NVIDIA_MODEL", DEFAULT_NVIDIA_MODEL) or DEFAULT_NVIDIA_MODEL).strip()
    return _call_chat_completions(api_url, api_key, model, prompt)


def _call_openai(prompt):
    api_key = _secret_value("OPENAI_API_KEY")
    if not api_key:
        return None
    model = _secret_value("OPENAI_TEXT_MODEL", "gpt-5.6")
    payload = {"model": model, "reasoning": {"effort": "low"}, "instructions": system_prompt(), "input": prompt}
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=65) as resp:
            return _extract_output_text(json.loads(resp.read().decode("utf-8", errors="replace")))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _looks_like_windows_shortcut_title(title):
    text = _normalize_for_count(title)
    shortcut_terms = set(['shortcut', 'shortcuts', 'hotkey', 'hotkeys', 'keyboard', 'useful', 'usefull', 'tips', 'tricks', '\u09b6\u09b0\u09cd\u099f\u0995\u09be\u099f', '\u0995\u09bf\u09ac\u09cb\u09b0\u09cd\u09a1', '\u099c\u09bf\u09a8\u09bf\u09df\u09be\u09b8'])
    has_windows = "windows" in text or "win 11" in text or "windows 11" in text
    has_shortcut = any(term in text for term in shortcut_terms)
    return has_windows and has_shortcut


def _windows_shortcut_fallback_article(settings):
    title = settings["title"].strip()
    return (
        f"# {title}\n\n"
        + 'Windows 11 \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09a4\u09c7 \u0997\u09bf\u09df\u09c7 \u0985\u09a8\u09c7\u0995\u09c7\u0987 \u09ae\u09be\u0989\u09b8 \u09a6\u09bf\u09df\u09c7 \u09ac\u09be\u09b0\u09ac\u09be\u09b0 \u098f\u0995\u0987 \u0995\u09be\u099c \u0995\u09b0\u09c7\u09a8\u0964 \u0985\u09a5\u099a \u0995\u09df\u09c7\u0995\u099f\u09bf \u09a6\u09b0\u0995\u09be\u09b0\u09bf \u0995\u09bf\u09ac\u09cb\u09b0\u09cd\u09a1 \u09b6\u09b0\u09cd\u099f\u0995\u09be\u099f \u099c\u09be\u09a8\u09b2\u09c7 \u09ab\u09be\u0987\u09b2 \u0996\u09cb\u09b2\u09be, \u0989\u0987\u09a8\u09cd\u09a1\u09cb \u09ac\u09a6\u09b2\u09be\u09a8\u09cb, \u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09b6\u099f \u09a8\u09c7\u0993\u09df\u09be \u09ac\u09be \u0995\u09aa\u09bf \u0995\u09b0\u09be \u0995\u09be\u099c \u0985\u09a8\u09c7\u0995 \u09a6\u09cd\u09b0\u09c1\u09a4 \u0995\u09b0\u09be \u09af\u09be\u09df\u0964 \u09af\u09be\u09b0\u09be \u09aa\u09dc\u09be\u09b6\u09cb\u09a8\u09be, \u0985\u09ab\u09bf\u09b8, \u09a1\u09bf\u099c\u09be\u0987\u09a8, \u09ad\u09bf\u09a1\u09bf\u0993 \u098f\u09a1\u09bf\u099f\u09bf\u0982 \u09ac\u09be \u0985\u09a8\u09b2\u09be\u0987\u09a8 \u0995\u09be\u099c \u0995\u09b0\u09c7\u09a8, \u09a4\u09be\u09a6\u09c7\u09b0 \u099c\u09a8\u09cd\u09af \u098f\u09b8\u09ac \u09b6\u09b0\u09cd\u099f\u0995\u09be\u099f \u09aa\u09cd\u09b0\u09a4\u09bf\u09a6\u09bf\u09a8\u09c7\u09b0 \u09b8\u09ae\u09df \u09ac\u09be\u0981\u099a\u09be\u09a4\u09c7 \u09b8\u09be\u09b9\u09be\u09af\u09cd\u09af \u0995\u09b0\u09c7\u0964'
        + "\n\n"
        + '\u09b8\u09ac\u099a\u09c7\u09df\u09c7 \u09a6\u09b0\u0995\u09be\u09b0\u09bf \u09b6\u09b0\u09cd\u099f\u0995\u09be\u099f\u09c7\u09b0 \u09ae\u09a7\u09cd\u09af\u09c7 Win + E \u099a\u09be\u09aa\u09b2\u09c7 File Explorer \u0996\u09c1\u09b2\u09c7 \u09af\u09be\u09df, Win + D \u099a\u09be\u09aa\u09b2\u09c7 \u098f\u0995 \u0995\u09cd\u09b2\u09bf\u0995\u09c7 \u09a1\u09c7\u09b8\u09cd\u0995\u099f\u09aa \u09a6\u09c7\u0996\u09be \u09af\u09be\u09df, \u0986\u09b0 Alt + Tab \u09a6\u09bf\u09df\u09c7 \u0996\u09cb\u09b2\u09be \u0985\u09cd\u09af\u09be\u09aa\u09c7\u09b0 \u09ae\u09a7\u09cd\u09af\u09c7 \u09a6\u09cd\u09b0\u09c1\u09a4 \u09af\u09be\u0993\u09df\u09be \u09af\u09be\u09df\u0964 \u0985\u09a8\u09c7\u0995 \u09b8\u09ae\u09df \u0995\u09cb\u09a8\u09cb \u09b2\u09c7\u0996\u09be \u09ac\u09be \u099b\u09ac\u09bf \u09ac\u09be\u09b0\u09ac\u09be\u09b0 \u0995\u09aa\u09bf \u0995\u09b0\u09a4\u09c7 \u09b9\u09df; \u09a4\u0996\u09a8 Win + V \u09a6\u09bf\u09df\u09c7 clipboard history \u099a\u09be\u09b2\u09c1 \u0995\u09b0\u09b2\u09c7 \u0986\u0997\u09c7\u09b0 \u0995\u09aa\u09bf \u0995\u09b0\u09be \u099c\u09bf\u09a8\u09bf\u09b8\u0993 \u09b8\u09b9\u099c\u09c7 \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09be \u09af\u09be\u09df\u0964'
        + "\n\n"
        + '\u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09b6\u099f\u09c7\u09b0 \u099c\u09a8\u09cd\u09af Win + Shift + S \u0996\u09c1\u09ac \u0995\u09be\u099c\u09c7 \u09b2\u09be\u0997\u09c7, \u0995\u09be\u09b0\u09a3 \u098f\u09a4\u09c7 \u09a8\u09bf\u09b0\u09cd\u09a6\u09bf\u09b7\u09cd\u099f \u0985\u0982\u09b6 \u0995\u09c7\u099f\u09c7 \u09a8\u09c7\u0993\u09df\u09be \u09af\u09be\u09df\u0964 \u0995\u09ae\u09cd\u09aa\u09bf\u0989\u099f\u09be\u09b0 \u09a7\u09c0\u09b0 \u09b2\u09be\u0997\u09b2\u09c7 Ctrl + Shift + Esc \u099a\u09be\u09aa\u09b2\u09c7\u0987 Task Manager \u0996\u09c1\u09b2\u09c7 \u0995\u09cb\u09a8 \u0985\u09cd\u09af\u09be\u09aa \u09ac\u09c7\u09b6\u09bf \u099a\u09be\u09aa \u09a6\u09bf\u099a\u09cd\u099b\u09c7 \u09a4\u09be \u09a6\u09c7\u0996\u09be \u09af\u09be\u09df\u0964 \u09ac\u09be\u0987\u09b0\u09c7 \u09af\u09be\u0993\u09df\u09be\u09b0 \u0986\u0997\u09c7 Win + L \u099a\u09be\u09aa\u09b2\u09c7 \u0995\u09ae\u09cd\u09aa\u09bf\u0989\u099f\u09be\u09b0 \u09a6\u09cd\u09b0\u09c1\u09a4 \u09b2\u0995 \u09b9\u09df\u09c7 \u09af\u09be\u09df, \u09af\u09be \u09a8\u09bf\u09b0\u09be\u09aa\u09a4\u09cd\u09a4\u09be\u09b0 \u099c\u09a8\u09cd\u09af\u0993 \u09ad\u09be\u09b2\u09cb\u0964'
        + "\n\n"
        + '\u09b6\u09b0\u09cd\u099f\u0995\u09be\u099f \u09ae\u09c1\u0996\u09b8\u09cd\u09a5 \u0995\u09b0\u09be\u09b0 \u09b8\u09ac\u099a\u09c7\u09df\u09c7 \u09b8\u09b9\u099c \u09aa\u09a6\u09cd\u09a7\u09a4\u09bf \u09b9\u09b2\u09cb \u098f\u0995\u09b8\u09be\u09a5\u09c7 \u09b8\u09ac \u09b6\u09c7\u0996\u09be\u09b0 \u099a\u09c7\u09b7\u09cd\u099f\u09be \u09a8\u09be \u0995\u09b0\u09c7 \u09aa\u09cd\u09b0\u09a4\u09bf\u09a6\u09bf\u09a8 \u09a6\u09c1\u0987-\u09a4\u09bf\u09a8\u099f\u09bf \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09be\u0964 \u0995\u09df\u09c7\u0995\u09a6\u09bf\u09a8 \u09a8\u09bf\u09df\u09ae\u09bf\u09a4 \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09b2\u09c7 \u098f\u0997\u09c1\u09b2\u09cb \u0985\u09ad\u09cd\u09af\u09be\u09b8 \u09b9\u09df\u09c7 \u09af\u09be\u09df\u0964 \u09a4\u0996\u09a8 Windows 11 \u09b6\u09c1\u09a7\u09c1 \u099a\u09be\u09b2\u09be\u09a8\u09cb \u09a8\u09df, \u0986\u09b0\u0993 \u09a6\u09cd\u09b0\u09c1\u09a4 \u0993 \u09b8\u09cd\u09ae\u09be\u09b0\u09cd\u099f\u09ad\u09be\u09ac\u09c7 \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09be \u09b8\u09ae\u09cd\u09ad\u09ac \u09b9\u09df\u0964'

    )


def _education_fallback_article(settings):
    title = settings["title"].strip()
    category = settings.get("category") or DEFAULT_CATEGORY
    audience = settings.get("targetAudience") or DEFAULT_TARGET_AUDIENCE
    if _looks_like_windows_shortcut_title(title):
        return _windows_shortcut_fallback_article(settings)
    return (
        f"# {title}\n\n"
        + '\u098f\u0987 \u09ac\u09bf\u09b7\u09df\u099f\u09bf \u09a8\u09bf\u09df\u09c7 \u09ad\u09be\u09b2\u09cb \u0995\u09a8\u099f\u09c7\u09a8\u09cd\u099f \u09b2\u09bf\u0996\u09a4\u09c7 \u09b9\u09b2\u09c7 \u09aa\u09cd\u09b0\u09a5\u09ae\u09c7 \u09b6\u09bf\u09b0\u09cb\u09a8\u09be\u09ae\u09c7\u09b0 \u0986\u09b8\u09b2 \u0989\u09a6\u09cd\u09a6\u09c7\u09b6\u09cd\u09af \u09ac\u09c1\u099d\u09a4\u09c7 \u09b9\u09df\u0964 \u09aa\u09be\u09a0\u0995 \u0995\u09c0 \u099c\u09be\u09a8\u09a4\u09c7 \u099a\u09be\u0987\u099b\u09c7, \u0995\u09cb\u09a8 \u09b8\u09ae\u09b8\u09cd\u09af\u09be\u09b0 \u0989\u09a4\u09cd\u09a4\u09b0 \u0996\u09c1\u0981\u099c\u099b\u09c7 \u098f\u09ac\u0982 \u09b2\u09c7\u0996\u09be\u099f\u09bf \u09aa\u09dc\u09be\u09b0 \u09aa\u09b0 \u0995\u09c0 \u0995\u09be\u099c\u09c7 \u09b2\u09be\u0997\u09be\u09a4\u09c7 \u09aa\u09be\u09b0\u09ac\u09c7, \u098f\u09b8\u09ac \u09aa\u09b0\u09bf\u09b7\u09cd\u0995\u09be\u09b0 \u09a5\u09be\u0995\u09b2\u09c7 \u09b2\u09c7\u0996\u09be \u09b8\u09cd\u09ac\u09be\u09ad\u09be\u09ac\u09bf\u0995 \u0993 \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0\u09af\u09cb\u0997\u09cd\u09af \u09b9\u09df\u0964'
        + "\n\n"
        + '\u09ad\u09be\u09b2\u09cb \u09aa\u09cb\u09b8\u09cd\u099f \u09b6\u09c1\u09a7\u09c1 \u09ac\u09dc \u09ac\u09dc \u0995\u09a5\u09be \u09ac\u09b2\u09c7 \u09a8\u09be; \u098f\u099f\u09bf \u09a8\u09bf\u09b0\u09cd\u09a6\u09bf\u09b7\u09cd\u099f \u0989\u09a6\u09be\u09b9\u09b0\u09a3, \u09ac\u09be\u09b8\u09cd\u09a4\u09ac \u09b8\u09c1\u09ac\u09bf\u09a7\u09be \u098f\u09ac\u0982 \u09b8\u09b9\u099c \u09ac\u09cd\u09af\u09be\u0996\u09cd\u09af\u09be \u09a6\u09c7\u09df\u0964 \u09ac\u09bf\u09b7\u09df\u099f\u09bf \u09af\u09a6\u09bf \u09aa\u09cd\u09b0\u09af\u09c1\u0995\u09cd\u09a4\u09bf, \u09b6\u09bf\u0995\u09cd\u09b7\u09be, \u09ac\u09cd\u09af\u09ac\u09b8\u09be, \u09b8\u09cd\u09ac\u09be\u09b8\u09cd\u09a5\u09cd\u09af, \u09ad\u09cd\u09b0\u09ae\u09a3, \u09b0\u09be\u09a8\u09cd\u09a8\u09be \u09ac\u09be \u09b8\u09cb\u09b6\u09cd\u09af\u09be\u09b2 \u09ae\u09bf\u09a1\u09bf\u09df\u09be \u09b8\u09ae\u09cd\u09aa\u09b0\u09cd\u0995\u09bf\u09a4 \u09b9\u09df, \u09a4\u09be\u09b9\u09b2\u09c7 \u09b8\u09c7\u0987 \u09ac\u09bf\u09b7\u09df\u09c7\u09b0 \u09aa\u09cd\u09b0\u09df\u09cb\u099c\u09a8\u09c0\u09df \u09a4\u09a5\u09cd\u09af\u0987 \u09b8\u09be\u09ae\u09a8\u09c7 \u0986\u09a8\u09a4\u09c7 \u09b9\u09ac\u09c7\u0964'
        + "\n\n"
        + '\u09aa\u09be\u09a0\u0995\u09c7\u09b0 \u09b8\u09ae\u09df \u0995\u09ae, \u09a4\u09be\u0987 \u09ad\u09c2\u09ae\u09bf\u0995\u09be \u099b\u09cb\u099f \u09b0\u09c7\u0996\u09c7 \u09ae\u09c2\u09b2 \u0995\u09a5\u09be\u09df \u09af\u09c7\u09a4\u09c7 \u09b9\u09ac\u09c7\u0964 \u0995\u09cb\u09a5\u09be\u09df \u0995\u09c0\u09ad\u09be\u09ac\u09c7 \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09be \u09af\u09be\u09df, \u0995\u09c0 \u09b8\u09c1\u09ac\u09bf\u09a7\u09be \u09aa\u09be\u0993\u09df\u09be \u09af\u09be\u09df \u098f\u09ac\u0982 \u0995\u09cb\u09a8 \u099c\u09be\u09df\u0997\u09be\u09df \u09b8\u09a4\u09b0\u09cd\u0995 \u09a5\u09be\u0995\u09be \u09a6\u09b0\u0995\u09be\u09b0, \u098f\u09b8\u09ac \u09b8\u09b9\u099c \u09ad\u09be\u09b7\u09be\u09df \u09ac\u09b2\u09b2\u09c7 \u0995\u09a8\u099f\u09c7\u09a8\u09cd\u099f \u09ac\u09c7\u09b6\u09bf \u09ac\u09bf\u09b6\u09cd\u09ac\u09be\u09b8\u09af\u09cb\u0997\u09cd\u09af \u09b9\u09df\u0964'
        + "\n\n"
        + '\u09b8\u09ac\u09b6\u09c7\u09b7\u09c7, SEO-friendly \u09b2\u09c7\u0996\u09be \u09ae\u09be\u09a8\u09c7 \u098f\u0995\u0987 \u09b6\u09ac\u09cd\u09a6 \u09ac\u09be\u09b0\u09ac\u09be\u09b0 \u09ac\u09b8\u09be\u09a8\u09cb \u09a8\u09df\u0964 \u09b6\u09bf\u09b0\u09cb\u09a8\u09be\u09ae\u09c7\u09b0 \u09b8\u0999\u09cd\u0997\u09c7 \u09b8\u09ae\u09cd\u09aa\u09b0\u09cd\u0995\u09bf\u09a4 \u09aa\u09cd\u09b0\u09b6\u09cd\u09a8\u09c7\u09b0 \u0989\u09a4\u09cd\u09a4\u09b0 \u09a6\u09c7\u0993\u09df\u09be, \u09b8\u09cd\u09ac\u09be\u09ad\u09be\u09ac\u09bf\u0995 \u09ad\u09be\u09b7\u09be\u09df \u0997\u09c1\u09b0\u09c1\u09a4\u09cd\u09ac\u09aa\u09c2\u09b0\u09cd\u09a3 \u09b6\u09ac\u09cd\u09a6 \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09be \u098f\u09ac\u0982 \u09aa\u09be\u09a0\u0995\u09c7\u09b0 \u099c\u09a8\u09cd\u09af \u09aa\u09b0\u09bf\u09b7\u09cd\u0995\u09be\u09b0 \u09ae\u09c2\u09b2\u09cd\u09af \u09a4\u09c8\u09b0\u09bf \u0995\u09b0\u09be\u0987 \u09ad\u09be\u09b2\u09cb \u0995\u09a8\u099f\u09c7\u09a8\u09cd\u099f\u09c7\u09b0 \u0986\u09b8\u09b2 \u09b6\u0995\u09cd\u09a4\u09bf\u0964'
        + "\n\n"
        + '\u09b2\u09c7\u0996\u09be\u09b0 \u09ae\u09a7\u09cd\u09af\u09c7 \u0985\u09af\u09a5\u09be \u09ac\u09dc \u09a6\u09be\u09ac\u09bf \u09a8\u09be \u0995\u09b0\u09c7 \u09ac\u09be\u09b8\u09cd\u09a4\u09ac \u09a4\u09a5\u09cd\u09af \u09b0\u09be\u0996\u09be \u099c\u09b0\u09c1\u09b0\u09bf\u0964 \u09aa\u09be\u09a0\u0995 \u09af\u09c7\u09a8 \u09ac\u09c1\u099d\u09a4\u09c7 \u09aa\u09be\u09b0\u09c7 \u09ac\u09bf\u09b7\u09df\u099f\u09bf \u0995\u09c7\u09a8 \u09a6\u09b0\u0995\u09be\u09b0, \u0995\u09c0\u09ad\u09be\u09ac\u09c7 \u09b6\u09c1\u09b0\u09c1 \u0995\u09b0\u09be \u09af\u09be\u09df \u098f\u09ac\u0982 \u0995\u09cb\u09a8 \u09ad\u09c1\u09b2\u0997\u09c1\u09b2\u09cb \u098f\u09dc\u09bf\u09df\u09c7 \u099a\u09b2\u09be \u09ad\u09be\u09b2\u09cb\u0964 \u098f\u09a4\u09c7 \u09aa\u09cb\u09b8\u09cd\u099f\u099f\u09bf \u09b6\u09c1\u09a7\u09c1 \u09aa\u09dc\u09be\u09b0 \u09ae\u09a4\u09cb \u09a8\u09df, \u0995\u09be\u099c\u09c7 \u09b2\u09be\u0997\u09be\u09a8\u09cb\u09b0 \u09ae\u09a4\u09cb\u0993 \u09b9\u09df\u0964'
        + "\n\n"
        + '\u09aa\u09cd\u09b0\u09df\u09cb\u099c\u09a8\u09c7 \u099b\u09cb\u099f \u0989\u09a6\u09be\u09b9\u09b0\u09a3, \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09be\u09b0 \u09a7\u09be\u09aa \u098f\u09ac\u0982 \u09b8\u09a4\u09b0\u09cd\u0995\u09a4\u09be\u09b0 \u0995\u09a5\u09be \u09af\u09cb\u0997 \u0995\u09b0\u09b2\u09c7 \u0995\u09a8\u099f\u09c7\u09a8\u09cd\u099f \u0986\u09b0\u0993 \u09b6\u0995\u09cd\u09a4\u09bf\u09b6\u09be\u09b2\u09c0 \u09b9\u09df\u0964 \u098f\u0995\u0987 \u0995\u09a5\u09be \u0998\u09c1\u09b0\u09bf\u09df\u09c7 \u09a8\u09be \u09b2\u09bf\u0996\u09c7 \u09aa\u09cd\u09b0\u09a4\u09bf\u099f\u09bf \u0985\u09a8\u09c1\u099a\u09cd\u099b\u09c7\u09a6\u09c7 \u09a8\u09a4\u09c1\u09a8 \u09a4\u09a5\u09cd\u09af \u09a6\u09bf\u09b2\u09c7 \u09aa\u09be\u09a0\u0995\u09c7\u09b0 \u0986\u0997\u09cd\u09b0\u09b9 \u09a5\u09be\u0995\u09c7 \u098f\u09ac\u0982 \u09b8\u09be\u09b0\u09cd\u099a\u09c7\u09b0 \u099c\u09a8\u09cd\u09af\u0993 \u09b2\u09c7\u0996\u09be \u09b8\u09cd\u09ac\u09be\u09ad\u09be\u09ac\u09bf\u0995\u09ad\u09be\u09ac\u09c7 \u09ad\u09be\u09b2\u09cb \u09b9\u09df\u0964'

    )


def _personalize_fallback_article(article, title):
    parts = [part.strip() for part in (article or "").split("\n\n") if part.strip()]
    if len(parts) < 6:
        return article
    heading, paragraphs = parts[0], parts[1:]
    seed = sum(ord(ch) for ch in _normalize_for_count(title))
    focus_count = min(4, len(paragraphs))
    focus_index = seed % focus_count
    focus = paragraphs.pop(focus_index)
    if paragraphs:
        shift = seed % len(paragraphs)
        paragraphs = paragraphs[shift:] + paragraphs[:shift]
    return "\n\n".join([heading, focus] + paragraphs)


def _ensure_title_heading(article, title):
    article = (article or "").strip()
    title = (title or "").strip()
    if not article or not title:
        return article
    lines = [line.strip() for line in article.splitlines()]
    while lines and _normalize_for_count(lines[0]) in {"heading", "title", "headline"}:
        lines.pop(0)
    while lines and not lines[0]:
        lines.pop(0)
    if lines and lines[0].startswith("#"):
        lines[0] = f"# {title}"
    elif lines and _normalize_for_count(lines[0]) == _normalize_for_count(title):
        lines[0] = f"# {title}"
    else:
        lines.insert(0, f"# {title}")
    cleaned = [lines[0]]
    title_norm = _normalize_for_count(title)
    for line in lines[1:]:
        plain_line = re.sub(r"</?h[1-6][^>]*>", "", line, flags=re.I).strip()
        if _normalize_for_count(plain_line.lstrip("# ")) == title_norm:
            continue
        cleaned.append(line)
    result = "\n".join(cleaned).strip()
    result = re.sub(r"</?h[1-6][^>]*>", "", result, flags=re.I)
    return result.strip()


def _reduce_title_repetition(article, title, max_repeats=3):
    if not article or not title:
        return article
    count = 0

    def replace_match(match):
        nonlocal count
        count += 1
        if count <= max_repeats:
            return match.group(0)
        return "\u098f\u0987 \u09b8\u09b9\u09be\u09df\u0995 \u09ac\u09cd\u09af\u09ac\u09b8\u09cd\u09a5\u09be"

    return re.sub(re.escape(title), replace_match, article)


def _dedupe_sentences(article):
    if not article:
        return article
    seen = set()
    cleaned = []
    for part in re.split(r"(?<=[?.!?])\s+", article):
        sentence = part.strip()
        if not sentence:
            continue
        key = _normalize_for_count(sentence)
        if key and key in seen:
            continue
        seen.add(key)
        cleaned.append(sentence)
    return "\n\n".join(cleaned)


def _shorten_to_word_limit(article, max_words=420, min_words=260):
    if not article:
        return article
    parts = [p.strip() for p in article.split("\n\n") if p.strip()]
    if not parts:
        return article
    heading = parts[0] if parts[0].lstrip().startswith("#") else ""
    body_parts = parts[1:] if heading else parts
    kept = []
    count = _word_count(heading)
    for part in body_parts:
        part_count = _word_count(part)
        if kept and count + part_count > max_words:
            break
        if not kept and count + part_count > max_words:
            remaining = max(max_words - count, 80)
            words = re.findall(r"\S+", part)[:remaining]
            kept.append(" ".join(words).strip())
            count = max_words
            break
        kept.append(part)
        count += part_count
        if count >= min_words:
            break
    if not kept and body_parts:
        words = re.findall(r"\S+", body_parts[0])[:max_words]
        kept = [" ".join(words).strip()]
    return "\n\n".join([p for p in [heading] + kept if p]).strip()


def _provider_expansion(settings):
    fallback = _education_fallback_article(settings)
    paragraphs = [p.strip() for p in fallback.split("\n\n") if p.strip() and not p.lstrip().startswith("#")]
    return "\n\n" + "\n\n".join(paragraphs[:2])


def _repair_provider_article(article, settings):
    repaired = _ensure_title_heading(article or "", settings["title"])
    repaired = _reduce_title_repetition(repaired, settings["title"])
    repaired = _dedupe_sentences(repaired)
    repaired = _shorten_to_word_limit(repaired, 440, 300)
    validation = validate_article(repaired, settings["title"])
    if validation["wordCount"] < 200:
        repaired = (repaired.rstrip() + _provider_expansion(settings)).strip()
        repaired = _dedupe_sentences(repaired)
        repaired = _shorten_to_word_limit(repaired, 440, 300)
        validation = validate_article(repaired, settings["title"])
    return repaired, validation


def _generate_with_provider(settings, provider_name, caller):
    validation = None
    for attempt in range(3):
        prompt_builder = _build_compact_user_prompt if provider_name in {"gemini", "nvidia-nim"} else _build_user_prompt
        draft = caller(prompt_builder(settings, validation["reasons"] if validation else None))
        if not draft:
            break
        repaired, repaired_validation = _repair_provider_article(draft, settings)
        if repaired_validation["isValid"]:
            return repaired, provider_name, repaired_validation
        validation = repaired_validation
    return None


def _generate_article(settings):
    if _secret_value("GEMINI_API_KEY") or _secret_value("GOOGLE_AI_API_KEY"):
        result = _generate_with_provider(settings, "gemini", _call_gemini)
        if result:
            return result
    if _secret_value("NVIDIA_API_KEY") or _secret_value("NVIDIA_NIM_API_KEY"):
        result = _generate_with_provider(settings, "nvidia-nim", _call_nvidia)
        if result:
            return result
    if _secret_value("OPENAI_API_KEY"):
        result = _generate_with_provider(settings, "openai", _call_openai)
        if result:
            return result
    if (_secret_value("CLOUDFLARE_ACCOUNT_ID") or _secret_value("CF_ACCOUNT_ID")) and (_secret_value("CLOUDFLARE_API_TOKEN") or _secret_value("CF_API_TOKEN")):
        result = _generate_with_provider(settings, "cloudflare-ai", _call_cloudflare_ai)
        if result:
            return result
        if LAST_CLOUDFLARE_ERROR and not (_secret_value("GEMINI_API_KEY") or _secret_value("GOOGLE_AI_API_KEY") or _secret_value("NVIDIA_API_KEY") or _secret_value("NVIDIA_NIM_API_KEY") or _secret_value("OPENAI_API_KEY")):
            return "", "cloudflare-error", {"isValid": False, "reasons": [LAST_CLOUDFLARE_ERROR], "wordCount": 0, "titleRepetitionCount": 0, "bannedPhrasesFound": []}
    draft = _education_fallback_article(settings)
    draft = _ensure_title_heading(draft, settings["title"])
    draft = _shorten_to_word_limit(draft, 420, 280)
    validation = validate_article(draft, settings["title"])
    if not validation["isValid"] and any("Title repeated too many times" in reason for reason in validation["reasons"]):
        draft = _reduce_title_repetition(draft, settings["title"])
        draft = _ensure_title_heading(draft, settings["title"])
        draft = _shorten_to_word_limit(draft, 420, 280)
        validation = validate_article(draft, settings["title"])
    return draft, "local-generic", validation


def _tag_stop_words():
    return set(['a', 'an', 'the', 'and', 'or', 'for', 'to', 'of', 'in', 'on', 'with', 'by', 'from', 'how', 'what', 'why', 'when', 'where', 'is', 'are', 'be', 'best', 'top', 'this', 'that', 'these', 'those', 'most', 'very', 'usefull', 'useful', '\u0986\u09aa\u09a8\u09bf', '\u098f\u0997\u09c1\u09b2\u09cb', '\u099c\u09be\u09a8\u09b2\u09c7', '\u099c\u09a8\u09cd\u09af', '\u098f\u09b0', '\u098f\u0987'])


def _keyword_candidates(title, article):
    combined = f"{title} {article}"
    norm = _normalize_for_count(combined)
    stop = _tag_stop_words()
    title_words = set(_meaningful_title_words(title))
    scores = {}
    for word in re.findall(r"[A-Za-z0-9]+|[\u0980-\u09ff]+", norm):
        if len(word) < 3 or word in stop or word == "????":
            continue
        if word.isdigit():
            continue
        scores[word] = scores.get(word, 0) + (5 if word in title_words else 1)
    return scores


def _clean_tag_phrase(phrase):
    phrase = re.sub(r"[^A-Za-z0-9\u0980-\u09ff+#.\s-]+", " ", str(phrase or ""))
    phrase = re.sub(r"\s+", " ", phrase).strip(" -_")
    if not phrase or "????" in phrase:
        return ""
    words = re.findall(r"[A-Za-z0-9]+|[\u0980-\u09ff]+", phrase.lower())
    if not words or len(words) > 7:
        return ""
    stop = _tag_stop_words()
    meaningful = [word for word in words if word not in stop and len(word) >= 3]
    if not meaningful:
        return ""
    return phrase[:80]


def _add_tag(tags, phrase):
    phrase = _clean_tag_phrase(phrase)
    if not phrase:
        return
    existing = {tag.lower() for tag in tags}
    if phrase.lower() not in existing:
        tags.append(phrase)


def _title_keyword_phrases(title):
    stop = _tag_stop_words() - {"best", "top"}
    words = [word.lower() if re.match(r"^[A-Za-z0-9]+$", word) else word for word in re.findall(r"[A-Za-z0-9]+|[\u0980-\u09ff]+", title or "")]
    phrases = [title]
    clean_words = [word for word in words if word not in stop and len(word) >= 2]
    if len(clean_words) >= 2:
        phrases.append(" ".join(clean_words))
    for size in range(min(4, len(words)), 1, -1):
        for index in range(0, len(words) - size + 1):
            chunk = words[index:index + size]
            if any(word in stop for word in chunk):
                continue
            phrases.append(" ".join(chunk))
    return phrases


def _topic_keyword_phrases(title, article):
    text = f"{title or ''} {article or ''}".lower()
    profiles = [
        (['windows', 'win 11', 'windows 11', 'shortcut', 'shortcuts', 'hotkey', 'keyboard', 'useful', 'usefull', '\u09b6\u09b0\u09cd\u099f\u0995\u09be\u099f', '\u0995\u09bf\u09ac\u09cb\u09b0\u09cd\u09a1'], ['Windows 11 shortcuts', 'Windows 11 keyboard shortcuts', 'most useful Windows 11 shortcuts', 'Windows 11 shortcut keys', 'keyboard shortcuts for Windows 11', 'Windows shortcut keys', 'Windows 11 hotkeys', 'Windows key shortcuts', 'Windows 11 tips and tricks', 'Windows 11 productivity shortcuts', 'Windows 11 shortcut keys Bangla', '\u0989\u0987\u09a8\u09cd\u09a1\u09cb\u099c \u09e7\u09e7 \u09b6\u09b0\u09cd\u099f\u0995\u09be\u099f', '\u0995\u09bf\u09ac\u09cb\u09b0\u09cd\u09a1 \u09b6\u09b0\u09cd\u099f\u0995\u09be\u099f']),
        (['skin', 'skincare', 'oily', 'acne', 'face wash', 'sunscreen'], ['best skincare routine', 'skincare routine for oily skin', 'oily skin care tips', 'acne prone skin care', 'face wash for oily skin', 'moisturizer for oily skin', 'sunscreen for oily skin', 'skin care routine Bangla']),
        (['business', 'online business', 'startup', 'marketing'], ['online business ideas', 'small business growth tips', 'digital marketing strategy', 'business growth tips', 'online business guide', 'startup marketing tips']),
        (['smartphone', 'phone', 'mobile', 'android', 'iphone', 'laptop', 'gadgets'], ['best smartphone', 'smartphone buying guide', 'budget smartphone', 'phone review', 'android phone tips', 'laptop buying guide', 'best laptop', 'tech review Bangla']),
        (['youtube', 'video', 'creator', 'content creator', 'description'], ['YouTube SEO', 'YouTube video description', 'YouTube content ideas', 'video SEO tips', 'content creator tools', 'YouTube growth tips', 'YouTube description template']),
        (['facebook', 'page', 'social media', 'instagram', 'tiktok'], ['Facebook page growth', 'social media marketing', 'Facebook content ideas', 'page engagement tips', 'social media content strategy', 'Instagram content tips']),
        (['ai', 'chatgpt', 'artificial intelligence', 'tools'], ['AI tools', 'best AI tools', 'AI tools for content creators', 'ChatGPT alternatives', 'AI content writing tools', 'free AI tools', 'AI productivity tools']),
        (['breakfast', 'food', 'recipe', 'healthy', 'diet', 'workout', 'fitness', 'health'], ['healthy breakfast ideas', 'easy breakfast recipes', 'healthy food tips', 'diet tips', 'home workout plan', 'fitness tips for beginners', 'health tips Bangla']),
        (['travel', 'cox', 'bazar', 'tour', 'hotel', 'guide'], ['travel guide', 'Coxs Bazar travel guide', 'tour plan', 'hotel booking tips', 'budget travel tips', 'Bangladesh travel guide']),
    ]
    phrases = []
    for triggers, keywords in profiles:
        if any(trigger.lower() in text for trigger in triggers):
            phrases.extend(keywords)
    return phrases

def _generic_seo_modifiers(title):
    base = _clean_tag_phrase(title)
    if not base:
        return []
    modifiers = ["tips", "guide", "Bangla", "review", "ideas", "tutorial"]
    lower_base = base.lower()
    phrases = []
    for modifier in modifiers:
        if lower_base.endswith(" " + modifier.lower()):
            continue
        phrases.append(f"{base} {modifier}")
    return phrases


def _keyword_tags(title, article):
    tags = []
    for phrase in _topic_keyword_phrases(title, article):
        _add_tag(tags, phrase)
    for phrase in _title_keyword_phrases(title):
        _add_tag(tags, phrase)
    for phrase in _generic_seo_modifiers(title):
        _add_tag(tags, phrase)

    # Add standalone title words only for very short/one-word titles.
    if len(tags) < 6:
        for word in _meaningful_title_words(title):
            _add_tag(tags, word)

    limited = []
    total_words = 0
    for tag in tags:
        tag_words = max(_word_count(tag), 1)
        if limited and total_words + tag_words > 200:
            break
        limited.append(tag)
        total_words += tag_words
    return limited or ["SEO friendly content", "YouTube description", "Bangla content"]


def _hashtags(title, article, tags=None):
    tags = tags or _keyword_tags(title, article)
    output = []
    for tag in tags:
        clean = re.sub(r"[^A-Za-z0-9\u0980-\u09ff]+", "_", tag).strip("_")
        if len(clean) < 3:
            continue
        item = "#" + clean[:36]
        if item not in output:
            output.append(item)
        if len(output) >= 8:
            break
    return output or ['#\u09ac\u09be\u0982\u09b2\u09be_\u09b6\u09bf\u0995\u09cd\u09b7\u09be']


def _caption_from_article(article, meta_description):
    first_para = " ".join([p.strip("# \n\r\t") for p in (article or "").split("\n\n") if p.strip() and not p.lstrip().startswith("#")][:1])
    caption = re.sub(r"\s+", " ", first_para or meta_description or "").strip()
    if len(caption) > 180:
        caption = caption[:179].rsplit(" ", 1)[0] + "\u0964"
    return caption


def generate_article_package(settings):
    article, engine, validation = _generate_article(settings)
    if engine == "cloudflare-error":
        return {"error": validation["reasons"][0], "validation": validation}
    if not validation["isValid"]:
        return {"error": "ভালো মানের article তৈরি করা যায়নি। Title বা context একটু নির্দিষ্ট করে আবার চেষ্টা করুন।", "validation": validation}
    meta = _metadata(settings["title"], article)
    tags = _keyword_tags(settings["title"], article)
    hashtags = _hashtags(settings["title"], article, tags)
    return {
        "engine": engine,
        "title": settings["title"],
        "post": article,
        "article": article,
        "wordCount": validation["wordCount"],
        "validation": validation,
        "metaTitle": meta["metaTitle"],
        "metaDescription": meta["metaDescription"],
        "slug": meta["slug"],
        "seo_title": meta["metaTitle"],
        "meta_description": meta["metaDescription"],
        "tags": tags,
        "hashtags": hashtags,
        "caption": _caption_from_article(article, meta["metaDescription"]),
    }


def init_routes(app):
    @app.route("/article-generate")
    def article_generate_page():
        return send_from_directory(BASE_DIR, "index.html")

    @app.route("/article-generate/generate", methods=["POST"])
    def article_generate_api():
        if "user" not in session:
            return jsonify({"error": "login required"}), 401
        data = request.get_json(silent=True) or {}
        settings = _settings_from_payload(data)
        if len(settings["title"]) < 3:
            return jsonify({"error": "Title লিখে Generate করুন।"}), 400
        package = generate_article_package(settings)
        if package.get("error"):
            return jsonify(package), 422
        return jsonify({"status": "ok", "result": package})
