from flask import Flask, send_from_directory, redirect, session, request, jsonify, Response
import os, json, re, shutil, yt_dlp, requests

try:
    import favoriteweb_local_secrets as local_secrets
except ImportError:
    local_secrets = None


def secret_value(name, default=""):
    value = os.environ.get(name)
    if value:
        return value
    if local_secrets and hasattr(local_secrets, name):
        return getattr(local_secrets, name)
    return default

from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.secret_key = secret_value("FLASK_SECRET_KEY", "change-me-in-env")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Session cookie settings for cross-domain support
# This allows the Worker to proxy requests without cookie issues
app.config["SESSION_COOKIE_DOMAIN"] = False  # Don't set Domain attribute
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Inject user session into all templates
@app.context_processor
def inject_user():
    user = session.get("user")
    return dict(current_user=user, is_logged_in=user is not None)

app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

# âœ… FIXED PATH (MAIN FIX)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_ROOT = os.path.join(BASE_DIR, "file")

if not os.path.exists(FILE_ROOT):
    os.makedirs(FILE_ROOT)


def current_user_key():
    user = session.get("user") or {}
    raw = user.get("email") or user.get("sub") or user.get("name") or "user"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return safe[:120] or "user"


def current_user_file_root():
    root = os.path.join(FILE_ROOT, "_users", current_user_key())
    os.makedirs(root, exist_ok=True)
    return root


def safe_user_path(rel_path=""):
    root = current_user_file_root()
    rel_path = (rel_path or "").replace("\\", "/").lstrip("/")
    full_path = os.path.abspath(os.path.join(root, rel_path))
    try:
        if os.path.commonpath([os.path.abspath(root), full_path]) != os.path.abspath(root):
            return root, None
    except ValueError:
        return root, None
    return root, full_path


def public_origin():
    public_host = (
        request.headers.get("X-Public-Host")
        or request.headers.get("X-Forwarded-Host")
        or request.host
    )
    public_proto = request.headers.get("X-Public-Proto") or request.headers.get("X-Forwarded-Proto") or "https"
    return f"{public_proto}://{public_host}"

# =====================
# GOOGLE LOGIN
# =====================

from authlib.integrations.flask_client import OAuth

oauth = OAuth(app)

google = oauth.register(
    name="google",
    client_id=secret_value("GOOGLE_CLIENT_ID"),
    client_secret=secret_value("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"}
)

# =====================
# HOME
# =====================


@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(os.path.join(BASE_DIR, "assets"), filename)
@app.route("/shared.css")
def shared_css():
    return send_from_directory(BASE_DIR, "shared.css")

@app.route("/shared.js")
def shared_js():
    return send_from_directory(BASE_DIR, "shared.js")

@app.route("/__server_health")
def server_health():
    return Response("", 204, headers={"X-FavoriteWeb-Backend": "ok"})

@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")

# =====================
# LOGIN
# =====================

@app.route("/login")
def login():
    public_host = (
        request.headers.get("X-Public-Host")
        or request.headers.get("X-Forwarded-Host")
        or request.host
    )
    public_proto = request.headers.get("X-Public-Proto") or "https"
    callback_url = f"{public_proto}://{public_host}/login/callback"
    return google.authorize_redirect(callback_url)

# =====================
# CALLBACK
# =====================

@app.route("/login/callback")
def callback():
    # The Worker proxies the request but keeps the original Host header
    # So request.host should be server.favoriteweb.net
    # The redirect_uri must match what was sent to Google
    token = google.authorize_access_token()
    resp = google.get("https://www.googleapis.com/oauth2/v3/userinfo")
    session["user"] = resp.json()
    session.permanent = True
    return redirect("/upload")

# =====================
# UPLOAD PAGE
# =====================

@app.route("/upload")
def upload_page():
    if "user" not in session:
        return redirect("/login")
    return send_from_directory(BASE_DIR, "upload.html")

@app.route("/dashboard")
def dashboard_page():
    if "user" not in session:
        return redirect("/login")
    return send_from_directory(BASE_DIR, "dashboard.html")

@app.route("/profile")
def profile_page():
    if "user" not in session:
        return redirect("/login")
    return send_from_directory(BASE_DIR, "account.html")

@app.route("/settings")
def settings_page():
    if "user" not in session:
        return redirect("/login")
    return send_from_directory(BASE_DIR, "account.html")

# =====================
# UPLOAD API
# =====================

@app.route("/upload", methods=["POST"])
def upload():

    if "user" not in session:
        return jsonify({"error": "login required"})

    files = request.files.getlist("files")

    for file in files:
        if file.filename == "":
            continue

        root, save_path = safe_user_path(file.filename)
        if not save_path:
            continue
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        file.save(save_path)

    return jsonify({"status": "ok"})

# =====================
# ðŸ”¥ FILE LIST FIX (ONLY THIS CHANGED)
# =====================

import mimetypes

@app.route("/api/files")
def list_files():
    if "user" not in session:
        return jsonify({"error": "login required"}), 401

    path = request.args.get("path", "")
    root, full_path = safe_user_path(path)

    # security
    if not full_path:
        return jsonify({"error": "invalid path"})

    items = []

    if os.path.exists(full_path):
        for name in os.listdir(full_path):

            item_path = os.path.join(full_path, name)
            rel_path = os.path.join(path, name).replace("\\", "/")

            items.append({
                "name": name,
                "path": rel_path,
                "type": "folder" if os.path.isdir(item_path) else "file"
            })

    return jsonify({
        "current": path,
        "items": items
    })



@app.route("/api/files/rename", methods=["POST"])
def rename_file_item():
    if "user" not in session:
        return jsonify({"error": "login required"}), 401
    data = request.get_json(silent=True) or {}
    old_path = (data.get("path") or "").strip().replace("\\", "/").strip("/")
    new_name = (data.get("newName") or "").strip()
    if not old_path or not new_name or "/" in new_name or "\\" in new_name:
        return jsonify({"error": "Invalid name"}), 400
    root, old_full = safe_user_path(old_path)
    parent_rel = "/".join(old_path.split("/")[:-1])
    _, parent_full = safe_user_path(parent_rel)
    new_full = os.path.abspath(os.path.join(parent_full, new_name))
    if not old_full or not old_full.startswith(root) or not new_full.startswith(root):
        return jsonify({"error": "Invalid path"}), 400
    if not os.path.exists(old_full):
        return jsonify({"error": "Not found"}), 404
    if os.path.exists(new_full):
        return jsonify({"error": "Name already exists"}), 409
    os.rename(old_full, new_full)
    return jsonify({"status": "ok"})


@app.route("/api/files/delete", methods=["POST"])
def delete_file_item():
    if "user" not in session:
        return jsonify({"error": "login required"}), 401
    data = request.get_json(silent=True) or {}
    rel_path = (data.get("path") or "").strip().replace("\\", "/").strip("/")
    if not rel_path:
        return jsonify({"error": "Invalid path"}), 400
    root, full_path = safe_user_path(rel_path)
    if not full_path or full_path == root or not full_path.startswith(root):
        return jsonify({"error": "Invalid path"}), 400
    if not os.path.exists(full_path):
        return jsonify({"error": "Not found"}), 404
    if os.path.isdir(full_path):
        shutil.rmtree(full_path)
    else:
        os.remove(full_path)
    return jsonify({"status": "ok"})

@app.route("/open/<path:filename>")
def open_file(filename):
    if "user" not in session:
        return redirect("/login")

    root, file_path = safe_user_path(filename)
    if not file_path or not os.path.exists(file_path):
        return "Not Found", 404

    mime, _ = mimetypes.guess_type(file_path)

    if mime and mime.startswith("video"):
        return redirect(f"/stream/{filename}")

    if mime and (mime.startswith("image") or mime == "application/pdf"):
        return send_from_directory(root, filename)

    return send_from_directory(root, filename, as_attachment=True)

@app.route("/stream/<path:filename>")
def stream_video(filename):
    if "user" not in session:
        return redirect("/login")
    root, file_path = safe_user_path(filename)
    if not file_path or not os.path.exists(file_path):
        return "Not Found", 404
    return send_from_directory(root, filename)
# =====================
# DOWNLOAD
# =====================

@app.route("/file/<path:filename>")
def download(filename):
    if "user" not in session:
        return redirect("/login")
    root, file_path = safe_user_path(filename)
    if not file_path or not os.path.exists(file_path):
        return "Not Found", 404
    return send_from_directory(root, filename)
# =====================
# API: USER INFO
# =====================

@app.route("/api/user")
def api_user():
    user = session.get("user")
    if user:
        return jsonify({
            "logged_in": True,
            "name": user.get("name"),
            "email": user.get("email"),
            "picture": user.get("picture"),
        })
    return jsonify({"logged_in": False})

# =====================
# LOGOUT
# =====================


@app.route("/api/ytplayer/history")
def ytplayer_history():
    if "user" not in session:
        return jsonify({"error": "login required"}), 401

    data_path = os.path.join(BASE_DIR, "ytplayer", "videos.json")
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            videos = json.load(f)
    except Exception:
        videos = {}

    base = public_origin()
    owner = current_user_key()
    streams = []
    for stream_id, record in reversed(list(videos.items())):
        if isinstance(record, dict):
            source = record.get("url") or record.get("source") or ""
            record_owner = record.get("owner")
            title = record.get("title") or source
        else:
            source = str(record or "")
            record_owner = None
            title = source
        if record_owner != owner:
            continue
        streams.append({
            "id": stream_id,
            "source": source,
            "title": title,
            "video": f"{base}/ytplayer/stream/{stream_id}",
            "audio": f"{base}/ytplayer/play/{stream_id}",
        })

    return jsonify({"streams": streams})


@app.route("/api/ytplayer/update", methods=["POST"])
def ytplayer_update():
    if "user" not in session:
        return jsonify({"error": "login required"}), 401
    data = request.get_json(silent=True) or {}
    stream_id = str(data.get("id") or "")
    source = (data.get("source") or "").strip()
    if not stream_id or not source:
        return jsonify({"error": "Invalid stream"}), 400

    data_path = os.path.join(BASE_DIR, "ytplayer", "videos.json")
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            videos = json.load(f)
    except Exception:
        videos = {}

    record = videos.get(stream_id)
    if not isinstance(record, dict) or record.get("owner") != current_user_key():
        return jsonify({"error": "Not found"}), 404
    record["url"] = source
    record["title"] = source
    videos[stream_id] = record
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(videos, f, indent=2)
    return jsonify({"status": "ok"})


@app.route("/api/ytplayer/delete", methods=["POST"])
def ytplayer_delete():
    if "user" not in session:
        return jsonify({"error": "login required"}), 401
    data = request.get_json(silent=True) or {}
    stream_id = str(data.get("id") or "")
    if not stream_id:
        return jsonify({"error": "Invalid stream"}), 400

    data_path = os.path.join(BASE_DIR, "ytplayer", "videos.json")
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            videos = json.load(f)
    except Exception:
        videos = {}

    record = videos.get(stream_id)
    if not isinstance(record, dict) or record.get("owner") != current_user_key():
        return jsonify({"error": "Not found"}), 404
    videos.pop(stream_id, None)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(videos, f, indent=2)
    return jsonify({"status": "ok"})
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


# =====================
# WEBSITE ANALYTICS DASHBOARD
# =====================

import importlib.util
from pathlib import Path

analytics_backend_path = Path(BASE_DIR) / "Web Analytics Dashbord" / "analytics_backend.py"
if analytics_backend_path.exists():
    analytics_spec = importlib.util.spec_from_file_location("favoriteweb_analytics", analytics_backend_path)
    analytics_module = importlib.util.module_from_spec(analytics_spec)
    analytics_spec.loader.exec_module(analytics_module)
    analytics_module.init_routes(app, Path(BASE_DIR))
# =========================
# ðŸ”¥ ALL OLD ROUTES BACK (IMPORTANT)
# =========================

from ocr.routes import init_routes
init_routes(app)

from shofikul.routes import init_routes as shofikul_routes
shofikul_routes(app)

from download.route import download as download_blueprint
app.register_blueprint(download_blueprint)

from ytplayer.routes import init_routes as yt_routes
yt_routes(app)

# =====================
# RUN
# =====================

if __name__ == "__main__":
    # ðŸ”¥ FIX: Disable Werkzeug's Host header validation (for Cloudflare tunnel)
    # When running behind cloudflared, the Host header is the external domain
    # (e.g. khan.favoriteweb.net) which Werkzeug rejects as "not localhost".
    # Waitress does NOT have this validation, so it works perfectly.
    # This environment variable is the official Werkzeug way to bypass the check.
    os.environ["WERKZEUG_HOST_CHECK"] = "0"
    
    # Try Waitress first (production server, no Host validation)
    try:
        from waitress import serve
        print("[SERVER] Starting Waitress on 0.0.0.0:8000")
        serve(app, host="0.0.0.0", port=8000)
    except ImportError:
        # Fallback to Werkzeug dev server
        # Patch out the host check at multiple levels to be safe
        try:
            import werkzeug._internal
            werkzeug._internal._host_check = lambda host: True
        except AttributeError:
            pass
        
        try:
            import werkzeug.serving
            werkzeug.serving._invalid_host = lambda host: False
        except AttributeError:
            pass
        
        import werkzeug.serving as serving
        _orig_make_environ = serving.WSGIRequestHandler.make_environ
        
        def _patched_make_environ(self):
            env = _orig_make_environ(self)
            # Ensure SERVER_NAME is populated from Host header
            host = self.headers.get('Host', 'localhost')
            if ':' in host:
                host = host.split(':')[0]
            env['SERVER_NAME'] = host
            return env
        
        serving.WSGIRequestHandler.make_environ = _patched_make_environ
        
        print("[WARN] Waitress not found, using Werkzeug dev server")
        app.run(host="0.0.0.0", port=8000, debug=False, use_reloader=False)



