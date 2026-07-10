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


def _fallback_result(title):
    tokens = _keyword_tokens(title)
    focus = ", ".join(tokens[:4]) or title
    hashtags = ["#" + re.sub(r"[^\w\u0980-\u09ff]", "", token.title()) for token in tokens[:10]]
    while len(hashtags) < 8:
        hashtags.append(["#FavoriteWeb", "#UsefulTips", "#Trending", "#Guide"][len(hashtags) % 4])
    tags = tokens[:10] or [title]
    intro = (
        f"{title} niye ei post-e simple, practical ebong user-friendly guide share kora holo. "
        f"Jara {focus} niye clear idea pete chan, tader jonno ei content ta helpful hobe."
    )
    body = [
        intro,
        f"Prothome main topic ta short kore bujhi: {title} er value holo eta user-er real problem solve korte pare.",
        "Key points:",
        f"1. Topic-er main benefit clear kore bolo, jate reader prothom line thekei interest pay.",
        f"2. Practical example add koro, karon example content-ke trustworthy kore.",
        f"3. Simple language use koro, unnecessary long paragraph avoid koro.",
        f"4. Last-e clear call-to-action dao, jemon comment, share, download, contact, ba visit.",
        "Conclusion: Content ta regular update korle SEO value, social reach, and reader trust dhire dhire barbe.",
    ]
    return {
        "engine": "local-fallback",
        "title": title,
        "post": "\n\n".join(body),
        "tags": tags,
        "hashtags": hashtags[:12],
        "seo_title": title[:65],
        "meta_description": f"{title} niye practical guide, tips, key points, and useful recommendations.",
        "caption": f"{title}\n\n{intro}\n\n{' '.join(hashtags[:8])}",
    }


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
        "Make the post useful, non-spammy, and ready to copy. hashtags must include #."
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
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
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
