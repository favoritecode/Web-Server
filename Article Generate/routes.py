from flask import jsonify, request, send_from_directory, session
from pathlib import Path
import json
import os
import re
import urllib.error
import urllib.request

BASE_DIR = Path(__file__).resolve().parent
MAX_TITLE_LENGTH = 180


def _secret_value(name, default=""):
    value = os.environ.get(name)
    if value:
        return value
    try:
        import favoriteweb_local_secrets as local_secrets
    except Exception:
        return default
    return getattr(local_secrets, name, default)


def _clean_title(title):
    return re.sub(r"\s+", " ", (title or "").strip())[:MAX_TITLE_LENGTH]


def _has_bengali_script(text):
    return bool(re.search(r"[\u0980-\u09ff]", text or ""))


BANGLISH_WORDS = {
    "ami": "\u0986\u09ae\u09bf", "amra": "\u0986\u09ae\u09b0\u09be", "apni": "\u0986\u09aa\u09a8\u09bf", "apnar": "\u0986\u09aa\u09a8\u09be\u09b0", "amar": "\u0986\u09ae\u09be\u09b0",
    "ei": "\u098f\u0987", "eita": "\u098f\u099f\u09be", "eta": "\u098f\u099f\u09be", "oita": "\u0993\u099f\u09be", "seita": "\u09b8\u09c7\u099f\u09be",
    "valo": "\u09ad\u09be\u09b2\u09cb", "bhalo": "\u09ad\u09be\u09b2\u09cb", "kharap": "\u0996\u09be\u09b0\u09be\u09aa", "notun": "\u09a8\u09a4\u09c1\u09a8", "puraton": "\u09aa\u09c1\u09b0\u09cb\u09a8\u09cb",
    "ki": "\u0995\u09bf", "keno": "\u0995\u09c7\u09a8", "kivabe": "\u0995\u09bf\u09ad\u09be\u09ac\u09c7", "kibhabe": "\u0995\u09bf\u09ad\u09be\u09ac\u09c7", "kokhon": "\u0995\u0996\u09a8",
    "kothay": "\u0995\u09cb\u09a5\u09be\u09af\u09bc", "konti": "\u0995\u09cb\u09a8\u099f\u09bf", "kon": "\u0995\u09cb\u09a8", "kara": "\u0995\u09be\u09b0\u09be",
    "jonno": "\u099c\u09a8\u09cd\u09af", "jonyo": "\u099c\u09a8\u09cd\u09af", "niye": "\u09a8\u09bf\u09af\u09bc\u09c7", "theke": "\u09a5\u09c7\u0995\u09c7", "sathe": "\u09b8\u09be\u09a5\u09c7",
    "moddhe": "\u09ae\u09a7\u09cd\u09af\u09c7", "vitore": "\u09ad\u09bf\u09a4\u09b0\u09c7", "baire": "\u09ac\u09be\u0987\u09b0\u09c7", "upore": "\u0989\u09aa\u09b0\u09c7", "niche": "\u09a8\u09bf\u099a\u09c7",
    "dorkar": "\u09a6\u09b0\u0995\u09be\u09b0", "lagbe": "\u09b2\u09be\u0997\u09ac\u09c7", "hobe": "\u09b9\u09ac\u09c7", "hoy": "\u09b9\u09af\u09bc", "hocche": "\u09b9\u099a\u09cd\u099b\u09c7",
    "korbo": "\u0995\u09b0\u09ac\u09cb", "kora": "\u0995\u09b0\u09be", "korte": "\u0995\u09b0\u09a4\u09c7", "koro": "\u0995\u09b0\u09cb", "korun": "\u0995\u09b0\u09c1\u09a8",
    "dekhun": "\u09a6\u09c7\u0996\u09c1\u09a8", "dekha": "\u09a6\u09c7\u0996\u09be", "bujhte": "\u09ac\u09c1\u099d\u09a4\u09c7", "bujhun": "\u09ac\u09c1\u099d\u09c1\u09a8", "pete": "\u09aa\u09c7\u09a4\u09c7",
    "pawa": "\u09aa\u09be\u0993\u09af\u09bc\u09be", "paowa": "\u09aa\u09be\u0993\u09af\u09bc\u09be", "shuru": "\u09b6\u09c1\u09b0\u09c1", "seshe": "\u09b6\u09c7\u09b7\u09c7", "age": "\u0986\u0997\u09c7",
    "por": "\u09aa\u09b0", "somoy": "\u09b8\u09ae\u09af\u09bc", "somossa": "\u09b8\u09ae\u09b8\u09cd\u09af\u09be",
    "kore": "\u0995\u09b0\u09c7", "korle": "\u0995\u09b0\u09b2\u09c7", "korar": "\u0995\u09b0\u09be\u09b0", "hole": "\u09b9\u09b2\u09c7", "thakle": "\u09a5\u09be\u0995\u09b2\u09c7",
    "ache": "\u0986\u099b\u09c7", "nai": "\u09a8\u09be\u0987", "nei": "\u09a8\u09c7\u0987", "sobai": "\u09b8\u09ac\u09be\u0987", "sob": "\u09b8\u09ac", "aro": "\u0986\u09b0\u0993", "onek": "\u0985\u09a8\u09c7\u0995",
}

BANGLISH_HINTS = set(BANGLISH_WORDS) | {"jabe", "jete", "jai", "kom", "beshi", "shob", "ta", "tar"}


def _looks_bangla(title):
    if _has_bengali_script(title):
        return True
    words = re.findall(r"[A-Za-z]+", (title or "").lower())
    if not words:
        return False
    matches = sum(1 for word in words if word in BANGLISH_HINTS)
    return matches >= 1 and matches / max(len(words), 1) >= 0.18


def _banglish_to_bengali_title(title):
    def replace_word(match):
        word = match.group(0)
        mapped = BANGLISH_WORDS.get(word.lower())
        return mapped if mapped else word
    return re.sub(r"[A-Za-z]+", replace_word, title or "")


def _keyword_tokens(title):
    words = re.findall(r"[\w\u0980-\u09ff]+", title.lower())
    stop = {
        "and", "or", "the", "for", "with", "from", "this", "that", "your", "you",
        "how", "why", "what", "best", "new", "a", "an", "to", "of", "in", "on",
        "r", "er", "ar", "ki", "kivabe", "jonno", "theke", "eta", "eita", "sob",
    }
    seen = set()
    tokens = []
    for word in words:
        if len(word) < 3 or word in stop or word in seen:
            continue
        seen.add(word)
        tokens.append(word)
    return tokens[:12]


def _make_hashtags(tokens, bangla=False):
    tags = []
    for token in tokens[:12]:
        clean = re.sub(r"[^\w\u0980-\u09ff]", "", token)
        if not clean:
            continue
        tag = "#" + clean
        if tag not in tags:
            tags.append(tag)
    defaults = ("#FavoriteWeb", "#\u09ac\u09be\u0982\u09b2\u09be_\u09aa\u09cb\u09b8\u09cd\u099f", "#UsefulTips", "#SmartGuide", "#TrendingNow") if bangla else ("#FavoriteWeb", "#UsefulTips", "#SmartGuide", "#TrendingNow", "#DailyUpdate")
    for tag in defaults:
        if len(tags) >= 12:
            break
        if tag not in tags:
            tags.append(tag)
    return tags[:12]


def _fallback_result(title):
    tokens = _keyword_tokens(title)
    display_topic = title.rstrip(".?!")
    is_bangla = _looks_bangla(display_topic)

    if is_bangla:
        display_topic = _banglish_to_bengali_title(display_topic)
        tags = [_banglish_to_bengali_title(token) for token in (tokens[:12] or [display_topic])]
        hashtags = _make_hashtags(tags, bangla=True)
        focus = ", ".join(tags[:5]) if tags else display_topic
        benefit_line = f"{display_topic} \u09a8\u09bf\u09af\u09bc\u09c7 \u09aa\u09b0\u09bf\u09b7\u09cd\u0995\u09be\u09b0 \u09a7\u09be\u09b0\u09a3\u09be \u09a5\u09be\u0995\u09b2\u09c7 \u09b8\u09bf\u09a6\u09cd\u09a7\u09be\u09a8\u09cd\u09a4 \u09a8\u09c7\u0993\u09af\u09bc\u09be, \u09aa\u09b0\u09bf\u0995\u09b2\u09cd\u09aa\u09a8\u09be \u0995\u09b0\u09be \u098f\u09ac\u0982 \u09ac\u09be\u09b8\u09cd\u09a4\u09ac\u09c7 \u09ad\u09be\u09b2\u09cb \u09ab\u09b2 \u09aa\u09be\u0993\u09af\u09bc\u09be \u0985\u09a8\u09c7\u0995 \u09b8\u09b9\u099c \u09b9\u09af\u09bc\u0964"
        value_line = f"\u098f\u0987 \u09aa\u09cb\u09b8\u09cd\u099f\u09c7 {focus} \u09b8\u09ae\u09cd\u09aa\u09b0\u09cd\u0995\u09bf\u09a4 \u0997\u09c1\u09b0\u09c1\u09a4\u09cd\u09ac\u09aa\u09c2\u09b0\u09cd\u09a3 \u09ac\u09bf\u09b7\u09af\u09bc\u0997\u09c1\u09b2\u09cb \u09b8\u09b9\u099c \u09ad\u09be\u09b7\u09be\u09af\u09bc \u09b8\u09be\u099c\u09be\u09a8\u09cb \u09b9\u09af\u09bc\u09c7\u099b\u09c7, \u09af\u09be\u09a4\u09c7 \u09aa\u09be\u09a0\u0995 \u09a6\u09cd\u09b0\u09c1\u09a4 \u09ac\u09c1\u099d\u09a4\u09c7 \u09aa\u09be\u09b0\u09c7\u09a8 \u0995\u09cb\u09a8 \u09a6\u09bf\u0995\u0997\u09c1\u09b2\u09cb\u09a4\u09c7 \u09ac\u09c7\u09b6\u09bf \u09ae\u09a8\u09cb\u09af\u09cb\u0997 \u09a6\u09c7\u0993\u09af\u09bc\u09be \u09a6\u09b0\u0995\u09be\u09b0\u0964"
        post = (
            f"{display_topic}\n\n"
            f"{benefit_line} {value_line}\n\n"
            f"\u09aa\u09cd\u09b0\u09a5\u09ae\u09c7\u0987 \u09ac\u09b2\u09be \u09af\u09be\u09af\u09bc, {display_topic} \u09ac\u09bf\u09b7\u09af\u09bc\u099f\u09bf \u09a0\u09bf\u0995\u09ad\u09be\u09ac\u09c7 \u09ac\u09c1\u099d\u09a4\u09c7 \u09aa\u09be\u09b0\u09b2\u09c7 \u0985\u09aa\u09cd\u09b0\u09af\u09bc\u09cb\u099c\u09a8\u09c0\u09af\u09bc \u09ac\u09bf\u09ad\u09cd\u09b0\u09be\u09a8\u09cd\u09a4\u09bf \u0995\u09ae\u09c7 \u09af\u09be\u09af\u09bc\u0964 "
            f"\u0985\u09a8\u09c7\u0995 \u09b8\u09ae\u09af\u09bc \u0986\u09ae\u09b0\u09be \u09b6\u09c1\u09a7\u09c1 \u09b6\u09bf\u09b0\u09cb\u09a8\u09be\u09ae \u09a6\u09c7\u0996\u09c7 \u09b8\u09bf\u09a6\u09cd\u09a7\u09be\u09a8\u09cd\u09a4 \u09a8\u09c7\u0987, \u0995\u09bf\u09a8\u09cd\u09a4\u09c1 \u09ad\u09be\u09b2\u09cb \u09ab\u09b2 \u09aa\u09c7\u09a4\u09c7 \u09b9\u09b2\u09c7 \u09ac\u09bf\u09b7\u09af\u09bc\u099f\u09bf\u09b0 \u09ae\u09c2\u09b2 \u0995\u09be\u09b0\u09a3, \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0\u09bf\u0995 \u09a6\u09bf\u0995 \u098f\u09ac\u0982 \u09b8\u09be\u09a7\u09be\u09b0\u09a3 \u09ad\u09c1\u09b2\u0997\u09c1\u09b2\u09cb \u099c\u09be\u09a8\u09be \u099c\u09b0\u09c1\u09b0\u09bf\u0964\n\n"
            f"\u09ac\u09be\u09b8\u09cd\u09a4\u09ac\u09c7 {display_topic} \u09a8\u09bf\u09af\u09bc\u09c7 \u0995\u09be\u099c \u0995\u09b0\u09be\u09b0 \u09b8\u09ae\u09af\u09bc \u09a8\u09bf\u099c\u09c7\u09b0 \u09aa\u09cd\u09b0\u09af\u09bc\u09cb\u099c\u09a8, \u09b8\u09ae\u09af\u09bc, budget \u098f\u09ac\u0982 \u09aa\u09cd\u09b0\u09a4\u09cd\u09af\u09be\u09b6\u09bf\u09a4 \u09ab\u09b2\u09be\u09ab\u09b2 \u09ae\u09bf\u09b2\u09bf\u09af\u09bc\u09c7 \u09a6\u09c7\u0996\u09be \u0989\u099a\u09bf\u09a4\u0964 "
            f"\u09af\u09c7\u0996\u09be\u09a8\u09c7 \u09a6\u09b0\u0995\u09be\u09b0 \u09b8\u09c7\u0996\u09be\u09a8\u09c7 \u0989\u09a6\u09be\u09b9\u09b0\u09a3, \u099b\u09cb\u099f checklist, \u0985\u09a5\u09ac\u09be \u09b8\u09b9\u099c comparison \u09ac\u09cd\u09af\u09ac\u09b9\u09be\u09b0 \u0995\u09b0\u09b2\u09c7 \u09ac\u09bf\u09b7\u09af\u09bc\u099f\u09bf \u0986\u09b0\u0993 \u09b8\u09b9\u099c\u09c7 \u09ac\u09cb\u099d\u09be \u09af\u09be\u09af\u09bc\u0964\n\n"
            f"\u09ad\u09be\u09b2\u09cb \u09ab\u09b2 \u09aa\u09c7\u09a4\u09c7 trusted source \u0985\u09a8\u09c1\u09b8\u09b0\u09a3 \u0995\u09b0\u09be, \u0985\u09aa\u09cd\u09b0\u09af\u09bc\u09cb\u099c\u09a8\u09c0\u09af\u09bc shortcut \u098f\u09a1\u09bc\u09be\u09a8\u09cb \u098f\u09ac\u0982 step-by-step \u0989\u09a8\u09cd\u09a8\u09a4\u09bf \u09a6\u09c7\u0996\u09be \u09b8\u09ac\u099a\u09c7\u09af\u09bc\u09c7 \u0995\u09be\u09b0\u09cd\u09af\u0995\u09b0 \u09aa\u09a6\u09cd\u09a7\u09a4\u09bf\u0964 "
            f"\u098f\u09ad\u09be\u09ac\u09c7 \u098f\u0997\u09cb\u09b2\u09c7 better engagement, \u09ad\u09be\u09b2\u09cb \u09ac\u09bf\u09b6\u09cd\u09ac\u09be\u09b8\u09af\u09cb\u0997\u09cd\u09af\u09a4\u09be \u098f\u09ac\u0982 long-term result \u09aa\u09be\u0993\u09af\u09bc\u09be \u09b8\u09ae\u09cd\u09ad\u09ac\u0964"
        )
        seo_title = display_topic[:65]
        meta_description = f"{display_topic} \u09a8\u09bf\u09af\u09bc\u09c7 \u09b8\u09b9\u099c \u09ac\u09be\u0982\u09b2\u09be guide, practical tips, common mistakes \u098f\u09ac\u0982 smart recommendations\u0964"
        caption = f"{display_topic}\n\n{benefit_line} \u09b8\u09b9\u099c\u09ad\u09be\u09ac\u09c7 \u09ac\u09bf\u09b7\u09af\u09bc\u099f\u09bf \u09ac\u09c1\u099d\u09a4\u09c7 \u098f\u0987 \u09aa\u09cb\u09b8\u09cd\u099f\u099f\u09bf follow \u0995\u09b0\u09c1\u09a8\u0964\n\n" + " ".join(hashtags[:10])
        return {"engine": "local-fallback", "title": display_topic, "post": post, "tags": tags, "hashtags": hashtags, "seo_title": seo_title, "meta_description": meta_description, "caption": caption}

    topic_words = tokens[:5]
    focus = ", ".join(topic_words) if topic_words else display_topic
    hashtags = _make_hashtags(tokens, bangla=False)
    tags = tokens[:12] or [display_topic]
    benefit_line = f"A clear understanding of {display_topic} makes planning, decision-making, and real-world results much easier."
    value_line = f"This post explains the most useful points around {focus} in a simple, practical way."
    post = (
        f"{display_topic}\n\n"
        f"{benefit_line} {value_line}\n\n"
        f"The first thing to remember is that {display_topic} works best when the reader gets clear, useful information without unnecessary complexity. "
        f"Before taking action, it helps to understand the main benefits, common mistakes, and practical steps that can improve the final result.\n\n"
        f"In real use, {display_topic} should be matched with your goal, time, budget, and expected outcome. "
        f"Short paragraphs, direct explanations, examples, and simple comparisons can make the content more helpful and easier to follow.\n\n"
        f"For better results, follow trusted sources, avoid shortcuts that create confusion, and improve step by step. "
        f"Track what is working, what needs to change, and which part gives the most value to the audience.\n\n"
        f"If you want to work with {display_topic}, start with a clear goal, make a small plan, and keep improving it regularly. "
        f"That approach can build better engagement, stronger trust, and more useful long-term results."
    )
    seo_title = display_topic[:65]
    meta_description = f"A practical guide to {display_topic} with useful tips, common mistakes, and smart recommendations."
    caption = f"{display_topic}\n\n{benefit_line} Follow this post for a clear and practical overview.\n\n" + " ".join(hashtags[:10])
    return {"engine": "local-fallback", "title": display_topic, "post": post, "tags": tags, "hashtags": hashtags, "seo_title": seo_title, "meta_description": meta_description, "caption": caption}


def _extract_json(text):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _openai_result(title):
    api_key = _secret_value("OPENAI_API_KEY")
    if not api_key:
        return None

    model = _secret_value("OPENAI_TEXT_MODEL", "gpt-5.6")
    instructions = (
        "You are FavoriteWeb's professional social and blog post generator. "
        "Return only valid JSON with keys: title, post, tags, hashtags, seo_title, "
        "meta_description, caption. Write naturally in the same language as the user's title. "
        "Make the post useful, non-spammy, and ready to copy. If the title is Bangla or Banglish, "
        "write Bangla words in Bengali script, but keep English brand names and technical terms in English letters. "
        "If the title is pure English, write in English. hashtags must include #."
    )
    payload = {
        "model": model,
        "reasoning": {"effort": "low"},
        "instructions": instructions,
        "input": (
            f"Generate one high-quality post package from this title: {title}\n"
            "Post length: 180-320 words. Tags: 8-12. Hashtags: 10-15."
        ),
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=55) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None

    output_text = data.get("output_text") or ""
    if not output_text:
        parts = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    parts.append(content.get("text") or "")
        output_text = "\n".join(parts)
    parsed = _extract_json(output_text)
    if not isinstance(parsed, dict):
        return None
    result = _fallback_result(title)
    for key in ("title", "post", "seo_title", "meta_description", "caption"):
        if parsed.get(key):
            result[key] = str(parsed[key]).strip()
    for key in ("tags", "hashtags"):
        if isinstance(parsed.get(key), list):
            result[key] = [str(item).strip() for item in parsed[key] if str(item).strip()][:15]
    result["engine"] = "openai"
    return result


def init_routes(app):
    @app.route("/article-generate")
    def article_generate_page():
        return send_from_directory(BASE_DIR, "index.html")

    @app.route("/article-generate/generate", methods=["POST"])
    def article_generate_api():
        if "user" not in session:
            return jsonify({"error": "login required"}), 401
        data = request.get_json(silent=True) or {}
        title = _clean_title(data.get("title"))
        if len(title) < 3:
            return jsonify({"error": "title required"}), 400
        result = _openai_result(title) or _fallback_result(title)
        return jsonify({"status": "ok", "result": result})