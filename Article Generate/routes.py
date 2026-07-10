from flask import jsonify, request, send_from_directory, session
from pathlib import Path
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request

BASE_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BASE_DIR / "prompts" / "bangla-education-article.txt"
MAX_TITLE_LENGTH = 180
MAX_CONTEXT_LENGTH = 2200
DEFAULT_CATEGORY = "শিক্ষা"
DEFAULT_TARGET_AUDIENCE = "শিক্ষার্থী ও অভিভাবক"
DEFAULT_TONE = "সহজ, প্রাঞ্জল, বিশ্বাসযোগ্য ও হালকা প্রচারণামূলক"
DEFAULT_WORD_COUNT = "500 থেকে 700 বাংলা শব্দ"
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


def validate_article(article, title, min_words=450):
    article = article or ""
    reasons = []
    banned = [phrase for phrase in BANNED_PHRASES if phrase.lower() in article.lower()]
    unsafe = [phrase for phrase in UNSAFE_CLAIMS if phrase.lower() in article.lower()]
    reasons.extend([f"Banned phrase found: {phrase}" for phrase in banned])
    reasons.extend([f"Unsafe claim found: {phrase}" for phrase in unsafe])

    wc = _word_count(article)
    if wc < min_words:
        reasons.append(f"Article is too short: {wc} words")

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


def _build_user_prompt(settings, validation_reasons=None):
    prompt = (
        f"Title: {settings['title']}\n"
        f"Category: {settings['category']}\n"
        f"Target audience: {settings['targetAudience']}\n"
        f"Tone: {settings['tone']}\n"
        f"Desired length: {settings['wordCount']}\n\n"
        f"Product context:\n{settings['productContext']}\n\n"
        "এই title নিয়ে একটি সম্পূর্ণ article লেখো। Title-এর প্রকৃত অর্থ বুঝে লিখবে। "
        "Generic SEO filler, keyword stuffing, repeated title এবং অপ্রয়োজনীয় English শব্দ ব্যবহার করবে না।"
    )
    if validation_reasons:
        prompt += "\n\nThe previous draft failed validation for these reasons: " + "; ".join(validation_reasons)
        prompt += " Rewrite the full article. Remove all generic filler, repetition and keyword stuffing. Make every paragraph directly relevant to the title and product context."
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


def _call_chat_completions(api_url, api_key, model, prompt, extra_headers=None):
    if not api_url or not api_key or not model:
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.55,
        "top_p": 0.9,
        "max_tokens": 2600,
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


def _call_deepseek(prompt):
    api_key = _secret_value("DEEPSEEK_API_KEY") or _secret_value("DEEPSEEK_WORKER_API_KEY")
    if not api_key:
        return None
    api_url = _secret_value("DEEPSEEK_API_URL") or _secret_value("DEEPSEEK_WORKER_URL") or "https://api.deepseek.com/chat/completions"
    model = _secret_value("DEEPSEEK_MODEL", "deepseek-chat")
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


def _generate_with_provider(settings, provider_name, caller):
    validation = None
    for attempt in range(3):
        draft = caller(_build_user_prompt(settings, validation["reasons"] if validation else None))
        if not draft:
            break
        validation = validate_article(draft, settings["title"])
        if validation["isValid"]:
            return draft, provider_name, validation
    return None


def _generate_article(settings):
    if _secret_value("DEEPSEEK_API_KEY") or _secret_value("DEEPSEEK_WORKER_API_KEY"):
        result = _generate_with_provider(settings, "deepseek", _call_deepseek)
        if result:
            return result
    if _secret_value("OPENAI_API_KEY"):
        result = _generate_with_provider(settings, "openai", _call_openai)
        if result:
            return result
    draft = _education_fallback_article(settings)
    validation = validate_article(draft, settings["title"])
    return draft, "local-education", validation


def generate_article_package(settings):
    article, engine, validation = _generate_article(settings)
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
        "tags": ["ইজি সিরিজ", "QR কোড", "ভিডিও শিক্ষক", "শিক্ষার্থী", "অভিভাবক", "স্বশিক্ষা"],
        "hashtags": ["#ইজি_সিরিজ", "#QREducation", "#ভিডিও_শিক্ষক", "#বাংলা_শিক্ষা", "#TechniqueEasyEducation"],
        "caption": meta["metaDescription"],
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
