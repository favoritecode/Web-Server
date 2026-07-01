from flask import Flask, send_from_directory, redirect, session, request, jsonify, Response
import os, json, re, shutil, time, yt_dlp, requests

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

# Fixed path configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_ROOT = os.path.join(BASE_DIR, "file")

if not os.path.exists(FILE_ROOT):
    os.makedirs(FILE_ROOT)

DEFAULT_ADMIN_EMAIL = "info.favoriteweb@gmail.com"
DEFAULT_USER_QUOTA_BYTES = 2 * 1024 * 1024 * 1024
USER_DB_PATH = os.path.join(BASE_DIR, "users.json")


def normalize_email(email=""):
    return (email or "").strip().lower()


def user_key_from_email(email):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", normalize_email(email)).strip("._")
    return safe[:120] or "user"


def load_user_db():
    try:
        with open(USER_DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"users": {}}
    if not isinstance(data, dict):
        data = {"users": {}}
    data.setdefault("users", {})
    return data


def save_user_db(data):
    with open(USER_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def dir_size(path):
    total = 0
    if not os.path.exists(path):
        return 0
    for root_dir, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root_dir, name))
            except OSError:
                pass
    return total


def user_record_from_session(create=True):
    user = session.get("user") or {}
    email = normalize_email(user.get("email"))
    if not email:
        return None
    data = load_user_db()
    users = data.setdefault("users", {})
    record = users.get(email)
    now = int(time.time())
    if not record and create:
        record = {
            "email": email,
            "name": user.get("name") or email,
            "picture": user.get("picture") or "",
            "role": "admin" if email == DEFAULT_ADMIN_EMAIL else "user",
            "status": "active",
            "quota_bytes": DEFAULT_USER_QUOTA_BYTES,
            "created_at": now,
        }
        users[email] = record
    if record:
        record["name"] = user.get("name") or record.get("name") or email
        record["picture"] = user.get("picture") or record.get("picture") or ""
        record["last_seen"] = now
        if email == DEFAULT_ADMIN_EMAIL:
            record["role"] = "admin"
            record["status"] = "active"
        record.setdefault("quota_bytes", DEFAULT_USER_QUOTA_BYTES)
        record.setdefault("status", "active")
        record.setdefault("role", "user")
        if create:
            save_user_db(data)
    return record


def is_current_admin():
    record = user_record_from_session(create=True)
    return bool(record and record.get("role") == "admin" and record.get("status") == "active")


def current_user_quota():
    record = user_record_from_session(create=True) or {}
    return int(record.get("quota_bytes") or DEFAULT_USER_QUOTA_BYTES)


def current_user_storage_used():
    return dir_size(current_user_file_root())


def active_user_required_json():
    if "user" not in session:
        return jsonify({"error": "login required"}), 401
    record = user_record_from_session(create=True)
    if record and record.get("status") == "suspended":
        return jsonify({"error": "account suspended"}), 403
    return None


def active_user_required_redirect():
    if "user" not in session:
        return redirect("/login")
    record = user_record_from_session(create=True)
    if record and record.get("status") == "suspended":
        return redirect("/logout")
    return None


def admin_required_json():
    blocked = active_user_required_json()
    if blocked:
        return blocked
    if not is_current_admin():
        return jsonify({"error": "admin required"}), 403
    return None


def admin_required_redirect():
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    if not is_current_admin():
        return redirect("/dashboard")
    return None


def ensure_default_admin():
    data = load_user_db()
    users = data.setdefault("users", {})
    record = users.get(DEFAULT_ADMIN_EMAIL) or {
        "email": DEFAULT_ADMIN_EMAIL,
        "name": "FavoriteWeb Admin",
        "picture": "",
        "created_at": int(time.time()),
    }
    record["role"] = "admin"
    record["status"] = "active"
    record.setdefault("quota_bytes", DEFAULT_USER_QUOTA_BYTES)
    users[DEFAULT_ADMIN_EMAIL] = record
    save_user_db(data)


ensure_default_admin()


def current_user_key():
    user = session.get("user") or {}
    raw = user.get("email") or user.get("sub") or user.get("name") or "user"
    return user_key_from_email(raw)


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



def safe_drive_path(rel_path=""):
    rel_path = (rel_path or "").replace("\\", "/").strip("/")
    if rel_path == "Users" or rel_path.startswith("Users/"):
        rel_path = "_users" + rel_path[5:]
    full_path = os.path.abspath(os.path.join(FILE_ROOT, rel_path))
    try:
        if os.path.commonpath([os.path.abspath(FILE_ROOT), full_path]) != os.path.abspath(FILE_ROOT):
            return None
    except ValueError:
        return None
    return full_path


def drive_display_path(rel_path=""):
    rel_path = (rel_path or "").replace("\\", "/").strip("/")
    if rel_path == "_users" or rel_path.startswith("_users/"):
        return "Users" + rel_path[6:]
    return rel_path
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
    user_record_from_session(create=True)
    session.permanent = True
    return redirect("/drive")

# =====================
# UPLOAD PAGE
# =====================

@app.route("/upload")
def upload_page():
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    return redirect("/drive")

@app.route("/drive")
def drive_page():
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    return send_from_directory(BASE_DIR, "upload.html")

@app.route("/dashboard")
def dashboard_page():
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    return send_from_directory(BASE_DIR, "dashboard.html")

@app.route("/profile")
def profile_page():
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    return send_from_directory(BASE_DIR, "account.html")

@app.route("/settings")
def settings_page():
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    return send_from_directory(BASE_DIR, "account.html")

@app.route("/admin")
def admin_page():
    blocked = admin_required_redirect()
    if blocked:
        return blocked
    return send_from_directory(BASE_DIR, "admin.html")

# =====================
# UPLOAD API
# =====================

@app.route("/upload", methods=["POST"])
def upload():

    blocked = active_user_required_json()
    if blocked:
        return blocked

    incoming = int(request.content_length or 0)
    used = current_user_storage_used()
    quota = current_user_quota()
    if quota and incoming and used + incoming > quota:
        return jsonify({"error": "quota exceeded", "used_bytes": used, "quota_bytes": quota}), 413

    files = request.files.getlist("files")

    for file in files:
        if file.filename == "":
            continue

        root, save_path = safe_user_path(file.filename)
        if not save_path:
            continue
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        file.save(save_path)
    final_used = current_user_storage_used()
    if quota and final_used > quota:
        return jsonify({"error": "quota exceeded", "used_bytes": final_used, "quota_bytes": quota}), 413
    return jsonify({"status": "ok", "used_bytes": final_used, "quota_bytes": quota})

# =====================
# File list APIs
# =====================

import mimetypes

@app.route("/api/files")
def list_files():
    blocked = active_user_required_json()
    if blocked:
        return blocked

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
    blocked = active_user_required_json()
    if blocked:
        return blocked
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



@app.route("/api/files/move", methods=["POST"])
def move_file_item():
    blocked = active_user_required_json()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    rel_path = (data.get("path") or "").strip().replace("\\", "/").strip("/")
    dest_path = (data.get("destination") or "").strip().replace("\\", "/").strip("/")
    if not rel_path:
        return jsonify({"error": "Invalid path"}), 400
    root, source_full = safe_user_path(rel_path)
    _, dest_full = safe_user_path(dest_path)
    if not source_full or not dest_full or not source_full.startswith(root) or not dest_full.startswith(root):
        return jsonify({"error": "Invalid path"}), 400
    if source_full == root or not os.path.exists(source_full):
        return jsonify({"error": "Not found"}), 404
    if not os.path.isdir(dest_full):
        return jsonify({"error": "Destination folder not found"}), 404
    target_full = os.path.abspath(os.path.join(dest_full, os.path.basename(source_full)))
    if not target_full.startswith(root) or target_full == source_full or target_full.startswith(source_full + os.sep):
        return jsonify({"error": "Invalid destination"}), 400
    if os.path.exists(target_full):
        return jsonify({"error": "Destination already has this name"}), 409
    shutil.move(source_full, target_full)
    return jsonify({"status": "ok"})

@app.route("/api/files/delete", methods=["POST"])
def delete_file_item():
    blocked = active_user_required_json()
    if blocked:
        return blocked
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


@app.route("/api/drive/files")
def list_drive_files():
    blocked = active_user_required_json()
    if blocked:
        return blocked

    raw_path = (request.args.get("path", "") or "").replace("\\", "/").strip("/")
    full_path = safe_drive_path(raw_path)
    if not full_path:
        return jsonify({"error": "invalid path"}), 400

    items = []
    if os.path.exists(full_path):
        for name in os.listdir(full_path):
            if not raw_path and name == "_users":
                item_name = "Users"
                rel_path = "Users"
                item_path = os.path.join(full_path, name)
            else:
                item_name = name
                rel_path = "/".join(part for part in [raw_path, name] if part)
                item_path = os.path.join(full_path, name)
            items.append({
                "name": item_name,
                "path": drive_display_path(rel_path),
                "type": "folder" if os.path.isdir(item_path) else "file"
            })

    return jsonify({"current": drive_display_path(raw_path), "items": items})



@app.route("/api/admin/drive/delete", methods=["POST"])
def admin_drive_delete():
    blocked = admin_required_json()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    rel_path = (data.get("path") or "").strip().replace("\\", "/").strip("/")
    if not rel_path:
        return jsonify({"error": "Invalid path"}), 400
    full_path = safe_drive_path(rel_path)
    if not full_path or full_path == os.path.abspath(FILE_ROOT):
        return jsonify({"error": "Invalid path"}), 400
    if not os.path.exists(full_path):
        return jsonify({"error": "Not found"}), 404
    if os.path.isdir(full_path):
        shutil.rmtree(full_path)
    else:
        os.remove(full_path)
    return jsonify({"status": "ok"})

@app.route("/drive/open/<path:filename>")
def drive_open_file(filename):
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    file_path = safe_drive_path(filename)
    if not file_path or not os.path.exists(file_path) or os.path.isdir(file_path):
        return "Not Found", 404
    real_root = os.path.dirname(file_path)
    real_name = os.path.basename(file_path)
    mime, _ = mimetypes.guess_type(file_path)
    return send_from_directory(real_root, real_name, as_attachment=not (mime and (mime.startswith("image") or mime == "application/pdf")))

@app.route("/open/<path:filename>")
def open_file(filename):
    blocked = active_user_required_redirect()
    if blocked:
        return blocked

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
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    root, file_path = safe_user_path(filename)
    if not file_path or not os.path.exists(file_path):
        return "Not Found", 404
    return send_from_directory(root, filename)
# =====================
# DOWNLOAD
# =====================

@app.route("/file/<path:filename>")
def download(filename):
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
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
        record = user_record_from_session(create=True) or {}
        used = current_user_storage_used()
        quota = int(record.get("quota_bytes") or DEFAULT_USER_QUOTA_BYTES)
        return jsonify({
            "logged_in": True,
            "name": user.get("name"),
            "email": user.get("email"),
            "picture": user.get("picture"),
            "role": record.get("role", "user"),
            "status": record.get("status", "active"),
            "is_admin": record.get("role") == "admin",
            "used_bytes": used,
            "quota_bytes": quota,
        })
    return jsonify({"logged_in": False})

# =====================
# LOGOUT
# =====================


@app.route("/api/ytplayer/history")
def ytplayer_history():
    blocked = active_user_required_json()
    if blocked:
        return blocked

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
    blocked = active_user_required_json()
    if blocked:
        return blocked
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
    blocked = active_user_required_json()
    if blocked:
        return blocked
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

@app.route("/api/admin/users")
def admin_users():
    blocked = admin_required_json()
    if blocked:
        return blocked
    data = load_user_db()
    users = []
    for email, record in sorted(data.get("users", {}).items()):
        key = user_key_from_email(email)
        root = os.path.join(FILE_ROOT, "_users", key)
        quota = int(record.get("quota_bytes") or DEFAULT_USER_QUOTA_BYTES)
        users.append({
            "email": email,
            "name": record.get("name") or email,
            "picture": record.get("picture") or "",
            "role": record.get("role") or "user",
            "status": record.get("status") or "active",
            "quota_bytes": quota,
            "used_bytes": dir_size(root),
            "created_at": record.get("created_at"),
            "last_seen": record.get("last_seen"),
            "is_default_admin": email == DEFAULT_ADMIN_EMAIL,
        })
    return jsonify({"users": users, "default_quota_bytes": DEFAULT_USER_QUOTA_BYTES})


@app.route("/api/admin/users/update", methods=["POST"])
def admin_update_user():
    blocked = admin_required_json()
    if blocked:
        return blocked
    data_in = request.get_json(silent=True) or {}
    email = normalize_email(data_in.get("email"))
    if not email:
        return jsonify({"error": "email required"}), 400
    data = load_user_db()
    users = data.setdefault("users", {})
    record = users.get(email)
    if not record:
        return jsonify({"error": "user not found"}), 404
    if email != DEFAULT_ADMIN_EMAIL:
        role = data_in.get("role")
        status = data_in.get("status")
        if role in ("user", "admin"):
            record["role"] = role
        if status in ("active", "suspended"):
            record["status"] = status
    else:
        record["role"] = "admin"
        record["status"] = "active"
    if "quota_bytes" in data_in:
        try:
            quota = int(data_in.get("quota_bytes"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid quota"}), 400
        if quota < 0:
            return jsonify({"error": "invalid quota"}), 400
        record["quota_bytes"] = quota
    users[email] = record
    save_user_db(data)
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
# All old routes
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
    # Disable Werkzeug host validation for Cloudflare tunnel
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




