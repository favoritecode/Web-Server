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
DEFAULT_CATEGORY = "শিক্ষা"
DEFAULT_TARGET_AUDIENCE = "শিক্ষার্থী ও অভিভাবক"
DEFAULT_TONE = "সহজ, প্রাঞ্জল, বিশ্বাসযোগ্য ও হালকা প্রচারণামূলক"
DEFAULT_WORD_COUNT = '150 থেকে 250 বাংলা শব্দ'
DEFAULT_PRODUCT_CONTEXT = (
    "ইজি সিরিজ / Technique Easy Education বইয়ের বিভিন্ন অধ্যায়, প্রশ্ন ও সমাধানের পাশে QR কোড থাকে। "
    "QR কোড মোবাইল দিয়ে scan করলে সংশ্লিষ্ট ভিডিও শিক্ষক পাওয়া যায়। ভিডিওতে কঠিন বিষয় ও সমাধান ধাপে ধাপে বুঝিয়ে দেওয়া হয়। "
    "শিক্ষার্থী pause, replay এবং বারবার দেখে নিজের সুবিধামতো শিখতে পারে। এটি স্কুলের শিক্ষককে প্রতিস্থাপন করে না; "
    "বাড়িতে পুনরাবৃত্তি, অনুশীলন এবং স্বশিক্ষায় সহায়তা করে।"
)
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

DEFAULT_SYSTEM_PROMPT = """তুমি বাংলাদেশের শিক্ষার্থী ও অভিভাবকদের জন্য স্বাভাবিক, তথ্যবহুল এবং সহজ বাংলা শিক্ষাবিষয়ক article writer।

তুমি generic SEO filler writer নও।

প্রথমে title-এর মূল বক্তব্য বোঝো। তারপর category, target audience এবং product context অনুযায়ী article লেখো।

Product context:
ইজি সিরিজ বইয়ের বিভিন্ন অধ্যায়, প্রশ্ন ও সমাধানের পাশে QR কোড থাকে। QR কোড scan করলে সংশ্লিষ্ট ভিডিও শিক্ষক পাওয়া যায়। ভিডিওতে কঠিন বিষয় ও সমাধান ধাপে ধাপে বুঝিয়ে দেওয়া হয়। শিক্ষার্থী pause, replay এবং বারবার দেখে নিজের সুবিধামতো শিখতে পারে। এটি স্কুলের শিক্ষককে প্রতিস্থাপন করে না; বাড়িতে পুনরাবৃত্তি, অনুশীলন এবং স্বশিক্ষায় সহায়তা করে।

কঠোর নিয়ম:
1. Title-এর প্রকৃত অর্থের বাইরে যাবে না।
2. Title-এর শব্দ আলাদা করে কমা দিয়ে keyword list বানাবে না।
3. Title একই article-এ অপ্রয়োজনে বারবার repeat করবে না।
4. প্রতিটি paragraph-এ নতুন ও নির্দিষ্ট তথ্য থাকবে।
5. generic paragraph লিখবে না।
6. অপ্রয়োজনীয় English শব্দ ব্যবহার করবে না।
7. “budget”, “checklist”, “comparison”, “trusted source”, “better engagement”, “long-term result” ব্যবহার করবে না।
8. “পরিষ্কার ধারণা থাকলে সিদ্ধান্ত নেওয়া”, “পরিকল্পনা করা এবং বাস্তবে ভালো ফল”, “অপ্রয়োজনীয় বিভ্রান্তি কমে যায়” ধরনের filler sentence ব্যবহার করবে না।
9. একই বক্তব্য ভিন্ন ভাষায় বারবার লিখবে না।
10. ভিত্তিহীন দাবি করবে না।
11. “নিশ্চিত A+”, “১০০% ফল”, “সব সমস্যা শেষ”, “কোচিং সম্পূর্ণ অপ্রয়োজনীয়” লিখবে না।
12. প্রয়োজন হলে “কমতে পারে”, “সহায়ক হতে পারে”, “সহজ হয়” ধরনের বিশ্বাসযোগ্য ভাষা ব্যবহার করবে।
13. ভাষা হবে বাংলাদেশের স্বাভাবিক বাংলা।
14. article-এর মধ্যে বাংলা ও English অস্বাভাবিকভাবে মিশাবে না।
15. পাঠক article পড়ে product কীভাবে কাজ করে, কার জন্য এবং কী সুবিধা দেয় তা বুঝতে পারবে।

Article structure:
- Title হুবহু H1 heading
- আকর্ষণীয় ও বিষয়ভিত্তিক ভূমিকা
- শিক্ষার্থীর বাস্তব সমস্যা
- QR কোড ও ভিডিও শিক্ষক কীভাবে কাজ করে
- কঠিন বিষয় বোঝার সুবিধা
- শিক্ষার্থী ও অভিভাবকের উপকার
- ব্যবহার করার সহজ পদ্ধতি
- বাস্তবসম্মত সতর্কতা বা সীমাবদ্ধতা
- সংক্ষিপ্ত উপসংহার

Article length:
500–700 বাংলা শব্দ, যদি আলাদা wordCount দেওয়া না হয়।

Output rules:
- শুধু final article return করবে
- কোনো analysis, note, explanation বা meta-commentary থাকবে না
- Markdown heading ব্যবহার করা যাবে
- অপ্রয়োজনীয় bullet list ব্যবহার করবে না

Bad example pattern, কখনো লিখবে না:
“বিষয়টি সম্পর্কে পরিষ্কার ধারণা থাকলে সিদ্ধান্ত নেওয়া, পরিকল্পনা করা এবং বাস্তবে ভালো ফল পাওয়া সহজ হয়।”
“নিজের প্রয়োজন, সময়, budget এবং প্রত্যাশিত ফলাফল মিলিয়ে trusted source অনুসরণ করলে better engagement পাওয়া যায়।”

Good example pattern:
Title: “বইয়ের ভেতর শিক্ষক থাকলে, লেখাপড়ায় আর প্রতিবন্ধকতা কিসের?”
Style: “একটি অঙ্কের উত্তর বইয়ে দেওয়া থাকলেও মাঝের ধাপটি অনেক শিক্ষার্থীর কাছে পরিষ্কার হয় না। বইয়ের পাশে থাকা QR কোড scan করলে সংশ্লিষ্ট ভিডিও শিক্ষক ধাপে ধাপে সমাধানটি বুঝিয়ে দিতে পারেন। শিক্ষার্থী প্রয়োজন হলে ভিডিও pause করে একই অংশ বারবার দেখতে পারে।”
Title: “QR কোড স্ক্যান করলেই শিক্ষক হাজির”
Style: “পাতার পাশে থাকা QR কোড scan করলে একই অধ্যায়ের ভিডিও ব্যাখ্যা খুলে যায়। তখন শিক্ষার্থী বইয়ের প্রশ্ন দেখে সঙ্গে সঙ্গে শিক্ষক কীভাবে সমাধান করছেন তা অনুসরণ করতে পারে।”
Title: “বইয়ের সাথে ২৪ ঘণ্টা শিক্ষক ফ্রি”
Style: “রাতে বা ছুটির দিনে কোনো প্রশ্নে আটকে গেলে ভিডিও শিক্ষক সহায়ক হতে পারে। শিক্ষার্থী নিজের সময় অনুযায়ী ভিডিও দেখে আবার বইয়ের অনুশীলনে ফিরতে পারে।”
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
        "You are a professional Bengali education article writer for Bangladesh. "
        "Write natural Bangla in Bengali script for students and parents. "
        "Focus on Easy Series / Technique Easy Education: books have QR codes beside chapters, questions and solutions; scanning opens a related video teacher; students can pause, replay and learn difficult solutions step by step. "
        "The video teacher supports school teachers; it does not guarantee results or replace reading, practice, or teacher guidance. "
        "Return only the final post body. Use the exact title only once as H1. Do not put tags or hashtags inside the body. Do not use keyword stuffing, generic SEO filler, repeated title, unsupported guarantees, or unnecessary English words. "
        "Avoid these phrases: trusted source, better engagement, long-term result, budget, checklist, comparison. "
        "Write a short SEO and YouTube-friendly Bengali post: 150 to 250 Bengali words, maximum 500 words, in 2 to 4 tight paragraphs."
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


def _education_title(title):
    return _contains_any(title, ["বই", "শিক্ষক", "লেখাপড়া", "পড়াশোনা", "পড়াশোনা", "সমাধান", "অঙ্ক", "QR", "কোড", "ইজি", "শিক্ষা", "কোচিং", "স্বশিক্ষা", "অভিভাবক"])


def validate_article(article, title, min_words=60, max_words=500):
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
        if len(english) > 28 or ratio > 0.075:
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

    concept_groups = {
        "qr": ["qr", "কিউআর", "কোড", "স্ক্যান", "scan"],
        "video_teacher": ["ভিডিও শিক্ষক", "ভিডিও", "শিক্ষক"],
        "hard_solution": ["কঠিন", "সমাধান", "ধাপে ধাপে", "ধাপ", "অঙ্ক", "প্রশ্ন"],
        "replay": ["বারবার", "replay", "pause", "থামিয়ে", "আবার দেখা", "পুনরায়"],
        "student": ["শিক্ষার্থী", "ছাত্র", "ছাত্রী"],
        "parent": ["অভিভাবক", "মা-বাবা", "বাসার"],
        "cost": ["খরচ", "কোচিং", "প্রাইভেট", "নির্ভরতা", "কমতে পারে"],
    }
    if _education_title(title):
        matched = [name for name, variants in concept_groups.items() if _contains_any(article, variants)]
        if len(matched) < 5:
            reasons.append("Missing required education/product concepts")
        if not _contains_any(article, ["ইজি সিরিজ", "Technique Easy Education", "QR", "কোড", "ভিডিও শিক্ষক"]):
            reasons.append("Product context is not clear")

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
        "Length: 150 to 250 Bengali words, maximum 500 words, in 2 to 4 tight paragraphs.\n\n"
        f"Product context:\n{settings['productContext']}\n\n"
        "Write a short SEO and YouTube-friendly Bengali post. Use the exact title only once as H1. "
        "Make every paragraph directly relevant to the title and Easy Series QR/video teacher context. "
        "Avoid generic SEO filler, repeated title, keyword stuffing, unsupported guarantees, and unnecessary English words. "
        "Return only the final post body. Do not include tags or hashtags in the body."
    )
    if validation_reasons:
        prompt += "\n\nPrevious draft failed validation: " + "; ".join(validation_reasons)
        prompt += " Rewrite the short post with more specific, title-relevant detail. Keep it under 500 words."
    return prompt


def _build_user_prompt(settings, validation_reasons=None):
    prompt = (
        f"Title: {settings['title']}\n"
        f"Category: {settings['category']}\n"
        f"Target audience: {settings['targetAudience']}\n"
        f"Tone: {settings['tone']}\n"
        f"Desired length: {settings['wordCount']}\n"
        "Hard length requirement: write 150 to 250 Bengali words, maximum 500 words. Use 2 to 4 tight paragraphs.\n\n"
        f"Product context:\n{settings['productContext']}\n\n"
        "Write a short SEO and YouTube-friendly Bengali post from this title. Understand the real meaning before writing. "
        "Use the exact title only once as the H1 heading; do not repeat the full title in body paragraphs. "
        "Write 150 to 250 Bengali words in Bengali script, never more than 500 words. Keep it useful, direct, and ready to copy. "
        "Do not use generic SEO filler, keyword stuffing, repeated title, unnecessary English words, tags, or hashtags inside the body."
    )
    if validation_reasons:
        prompt += "\n\nThe previous draft failed validation for these reasons: " + "; ".join(validation_reasons)
        prompt += " Rewrite the full short post. Remove generic filler, repetition and keyword stuffing. Keep every paragraph directly relevant to the title and product context, under 500 words."
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
        "max_tokens": 900,
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
        "max_tokens": 900,
        "max_completion_tokens": 900,
    }
    text = _run_cloudflare_payload(api_url, api_token, messages_payload)
    if text:
        return text
    fallback_payload = {
        "prompt": f"{cloudflare_system_prompt()}\n\n{prompt}",
        "temperature": 0.55,
        "top_p": 0.9,
        "max_tokens": 900,
        "max_completion_tokens": 900,
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
        "generationConfig": {"temperature": 0.65, "topP": 0.9, "maxOutputTokens": 900},
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


def _education_fallback_article(settings):
    title = settings["title"].strip()
    return (
        f"# {title}\n\n"
        "অনেক শিক্ষার্থী বইয়ে উত্তর দেখেও সমাধানের মাঝের ধাপ বুঝতে পারে না। আবার রাতে, ছুটির দিনে বা পরীক্ষার প্রস্তুতির সময় কোনো প্রশ্নে আটকে গেলে সঙ্গে সঙ্গে শিক্ষককে পাওয়া সবসময় সম্ভব হয় না। এই জায়গাতেই ইজি সিরিজ / Technique Easy Education বইয়ের QR কোডভিত্তিক ভিডিও শিক্ষক শেখার একটি সহায়ক পথ তৈরি করে। বইয়ের পাতার সঙ্গে ভিডিও ব্যাখ্যা যুক্ত থাকায় শিক্ষার্থী শুধু উত্তর দেখে থেমে থাকে না; বরং কীভাবে উত্তরটি তৈরি হলো সেটিও বুঝে নেওয়ার সুযোগ পায়।\n\n"
        "ইজি সিরিজের অধ্যায়, প্রশ্ন বা সমাধানের পাশে থাকা QR কোড মোবাইল দিয়ে scan করলে সংশ্লিষ্ট ভিডিও শিক্ষক খুলে যায়। ভিডিওতে শিক্ষক ধাপে ধাপে কঠিন বিষয়, অঙ্কের সমাধান বা প্রশ্নের ব্যাখ্যা বুঝিয়ে দেন। ফলে বইয়ের লেখা, উদাহরণ এবং ভিডিও ব্যাখ্যা একই সঙ্গে মিলিয়ে পড়া যায়। যে শিক্ষার্থী ক্লাসে একবার শুনে পুরো বিষয় ধরতে পারে না, সে বাড়িতে নিজের গতিতে আবার বিষয়টি দেখে নিতে পারে।\n\n"
        "ভিডিওর বড় সুবিধা হলো শেখার নিয়ন্ত্রণ শিক্ষার্থীর হাতে থাকে। কোনো ধাপ দ্রুত চলে গেলে pause করা যায়, না বোঝা অংশ replay করে বারবার দেখা যায়, আবার বুঝে গেলে পরের অংশে যাওয়া যায়। এতে মুখস্থের চাপ কিছুটা কমে এবং সমাধানের পদ্ধতি বোঝার অভ্যাস তৈরি হয়। বিশেষ করে গণিত, বিজ্ঞান বা ব্যাকরণের মতো বিষয়ে মাঝের ধাপ বোঝা খুব জরুরি; ভিডিও শিক্ষক সেই জায়গায় সহায়ক হতে পারে।\n\n"
        "অভিভাবকদের জন্যও এই ব্যবস্থা ব্যবহারিক। অনেক মা-বাবা সন্তানের সব বিষয় নিজে পড়াতে পারেন না, আবার প্রতিটি অধ্যায়ের জন্য আলাদা সহায়তা জোগাড় করাও সহজ নয়। বইয়ের সঙ্গে ভিডিও ব্যাখ্যা থাকলে শিক্ষার্থী অন্তত আটকে যাওয়া অংশ নিজে দেখে নিতে পারে। এতে কোচিং বা প্রাইভেটের ওপর নির্ভরতা কিছু ক্ষেত্রে কমতে পারে, যদিও প্রয়োজন অনুযায়ী শিক্ষক ও অভিভাবকের দিকনির্দেশনা এখনো গুরুত্বপূর্ণ।\n\n"
        "ব্যবহার পদ্ধতিটিও সহজ। শিক্ষার্থী প্রথমে বইয়ের অধ্যায় বা প্রশ্ন পড়বে, কোথায় সমস্যা হচ্ছে তা চিহ্নিত করবে, তারপর পাশে থাকা QR কোড scan করে ভিডিও দেখবে। ভিডিও দেখার পর আবার বইয়ে ফিরে একই প্রশ্ন নিজে সমাধান করার চেষ্টা করবে। শুধু ভিডিও দেখে গেলে শেখা স্থায়ী হয় না; নিয়মিত অনুশীলন, ভুল সংশোধন এবং বিদ্যালয়ের শিক্ষকের নির্দেশনা মানাও জরুরি।\n\n"
        "শেখার সময় একটি ছোট নিয়ম অনুসরণ করলে সুবিধা বেশি পাওয়া যায়। প্রথমে প্রশ্নটি নিজে করার চেষ্টা করা, তারপর আটকে গেলে ভিডিও দেখা, এরপর ভিডিও বন্ধ রেখে আবার খাতায় সমাধান করা—এই অভ্যাস শিক্ষার্থীকে সক্রিয়ভাবে শেখায়। এতে সে শুধু শিক্ষক কী বললেন তা শুনে যায় না; নিজের ভুল কোথায় হচ্ছে সেটিও ধরতে পারে। একই অধ্যায়ের কয়েকটি প্রশ্ন বারবার অনুশীলন করলে দুর্বল অংশ ধীরে ধীরে পরিষ্কার হয়।\n\n"
        "অভিভাবক চাইলে সন্তানের পড়ার অগ্রগতি দেখতেও এই পদ্ধতি ব্যবহার করতে পারেন। কোন অধ্যায়ের কোন প্রশ্নে সন্তান বারবার ভিডিও দেখছে, কোন অংশে বেশি সময় লাগছে, সেটি বুঝলে বাড়িতে সহায়তা করা সহজ হয়। এতে পড়াশোনা নিয়ে অযথা চাপ না দিয়ে নির্দিষ্ট দুর্বল জায়গায় মনোযোগ দেওয়া যায়।\n\n"
        "তবে মোবাইল ব্যবহার যেন শুধু ভিডিও দেখার মধ্যেই সীমাবদ্ধ না থাকে, সেটিও খেয়াল রাখা দরকার। ভিডিও দেখার পর বইয়ের অনুশীলন, খাতায় সমাধান লেখা এবং ভুলগুলো চিহ্নিত করা শেখাকে বেশি কার্যকর করে। নিয়মিত এভাবে পড়লে শিক্ষার্থী ধীরে ধীরে নিজের ওপর আস্থা পায়।\n\n"
        "তাই ‘বইয়ের ভেতর শিক্ষক’ কথাটির অর্থ কোনো জাদুকরী নিশ্চয়তা নয়। এর অর্থ হলো বইয়ের সঙ্গে এমন একটি ভিডিও সহায়তা যুক্ত থাকা, যা প্রয়োজনের সময় শিক্ষার্থীকে বিষয়টি বুঝতে সাহায্য করতে পারে। সঠিকভাবে ব্যবহার করলে ইজি সিরিজের QR কোড ও ভিডিও শিক্ষক পড়াশোনাকে আরও সহজ, নিয়মিত এবং আত্মবিশ্বাসী করে তুলতে পারে।"
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
    while lines and _normalize_for_count(lines[0]) in {"heading", "title", "headline", "?????", "???????"}:
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


def _shorten_to_word_limit(article, max_words=260):
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
        kept.append(part)
        count += part_count
        if count >= 150:
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
    repaired = _shorten_to_word_limit(repaired, 280)
    validation = validate_article(repaired, settings["title"])
    if validation["wordCount"] < 60:
        repaired = (repaired.rstrip() + _provider_expansion(settings)).strip()
        repaired = _dedupe_sentences(repaired)
        repaired = _shorten_to_word_limit(repaired, 280)
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
    draft = _personalize_fallback_article(_education_fallback_article(settings), settings["title"])
    draft = _ensure_title_heading(draft, settings["title"])
    draft = _shorten_to_word_limit(draft, 260)
    validation = validate_article(draft, settings["title"])
    if not validation["isValid"] and any("Title repeated too many times" in reason for reason in validation["reasons"]):
        draft = _reduce_title_repetition(draft, settings["title"])
        draft = _ensure_title_heading(draft, settings["title"])
        draft = _shorten_to_word_limit(draft, 260)
        validation = validate_article(draft, settings["title"])
    return draft, "local-education", validation


def _keyword_tags(title):
    base = ['\u0987\u099c\u09bf \u09b8\u09bf\u09b0\u09bf\u099c', 'QR \u0995\u09cb\u09a1', '\u09ad\u09bf\u09a1\u09bf\u0993 \u09b6\u09bf\u0995\u09cd\u09b7\u0995', '\u09ac\u09be\u0982\u09b2\u09be \u09b6\u09bf\u0995\u09cd\u09b7\u09be', 'Technique Easy Education']
    extras = []
    for word in _meaningful_title_words(title):
        clean = word.strip()
        if len(clean) < 3:
            continue
        if clean.lower() in {item.lower() for item in base + extras}:
            continue
        extras.append(clean)
        if len(extras) >= 5:
            break
    return (base + extras)[:10]


def _hashtags(title):
    tags = ['#\u0987\u099c\u09bf_\u09b8\u09bf\u09b0\u09bf\u099c', '#QREducation', '#\u09ad\u09bf\u09a1\u09bf\u0993_\u09b6\u09bf\u0995\u09cd\u09b7\u0995', '#\u09ac\u09be\u0982\u09b2\u09be_\u09b6\u09bf\u0995\u09cd\u09b7\u09be']
    if _contains_any(title, ['\u0995\u09cb\u099a\u09bf\u0982', '\u0996\u09b0\u099a']):
        tags.append("#StudySmart")
    elif _contains_any(title, ['\u0985\u0999\u09cd\u0995', '\u09b8\u09ae\u09be\u09a7\u09be\u09a8']):
        tags.append('#\u09a7\u09be\u09aa\u09c7_\u09a7\u09be\u09aa\u09c7_\u09b6\u09c7\u0996\u09be')
    else:
        tags.append("#TechniqueEasyEducation")
    return tags[:5]


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
        "tags": _keyword_tags(settings["title"]),
        "hashtags": _hashtags(settings["title"]),
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
