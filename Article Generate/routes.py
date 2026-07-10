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
    topic_words = tokens[:5]
    focus = ", ".join(topic_words) if topic_words else title
    display_topic = title.rstrip(".?!")

    hashtags = []
    for token in tokens[:12]:
        tag = "#" + re.sub(r"[^\w\u0980-\u09ff]", "", token.title())
        if len(tag) > 1 and tag not in hashtags:
            hashtags.append(tag)
    for tag in ("#FavoriteWeb", "#UsefulTips", "#SmartGuide", "#TrendingNow", "#DailyUpdate"):
        if len(hashtags) >= 12:
            break
        if tag not in hashtags:
            hashtags.append(tag)

    tags = tokens[:12] or [display_topic]
    benefit_line = f"{display_topic} niye clear idea thakle decision newa, planning kora, and practical result pawa onek easier hoy."
    value_line = f"Ei guide-e {focus} related important points simple vabe explain kora holo, jate reader quickly bujhte pare kon jaygay focus kora dorkar."
    practical_line = f"Real use-er somoy {display_topic} ke sudhu theory hisebe na dekhe, nijer need, budget, time, and expected result-er sathe match kore dekhte hobe."
    trust_line = "Valo result pete hole trusted source follow kora, unnecessary shortcut avoid kora, and step-by-step improvement track kora best approach."
    action_line = f"Apni jodi {display_topic} niye kaj korte chan, tahole prothome goal clear korun, tarpor small plan kore regular update nin."

    post = (
        f"{display_topic}\n\n"
        f"{benefit_line} {value_line}\n\n"
        f"Prothom kotha holo, topic ta jotoi simple mone hok, right information chara onek somoy wrong decision hoye jay. "
        f"Tai {display_topic} niye kaj shuru korar age basic idea, useful tips, and common mistake-gulo jana important. "
        f"Eta reader-ke time save korte help kore and final result-ke aro clean, professional, and effective kore.\n\n"
        f"{practical_line} Jekhane proyojon sekhane example, checklist, ba comparison use korle content-er value aro bere jay. "
        f"Beshi complicated language use na kore short paragraph, clear heading, and direct explanation dile reader easily follow korte pare.\n\n"
        f"{trust_line} Ekbar-e perfect result expect na kore regular testing and improvement korle better outcome ashe. "
        f"Kon jinis kaj korche, kon jinis change kora dorkar, and kon part reader-er jonno most useful seta note rakha bhalo.\n\n"
        f"{action_line} Eivabe smart vabe agale {display_topic} theke better value, better engagement, and long-term trust build kora possible."
    )

    seo_title = display_topic[:65]
    meta_description = f"{display_topic} niye practical guide, useful tips, common mistakes, and smart recommendations in one simple post."
    caption = (
        f"{display_topic}\n\n"
        f"{benefit_line} Short, clear, and practical vabe topic ta bujhte ei post ta follow korun.\n\n"
        + " ".join(hashtags[:10])
    )
    return {
        "engine": "local-fallback",
        "title": display_topic,
        "post": post,
        "tags": tags,
        "hashtags": hashtags[:12],
        "seo_title": seo_title,
        "meta_description": meta_description,
        "caption": caption,
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
