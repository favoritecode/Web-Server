from flask import Flask, send_from_directory, redirect, session, request, jsonify, Response, send_file, after_this_request
import os, json, re, shutil, time, tempfile, yt_dlp, requests

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
from itsdangerous import BadSignature, URLSafeSerializer

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


def env_enabled(name):
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def is_backup_runtime():
    explicit = os.environ.get("FAVORITEWEB_BACKUP_MODE")
    if explicit is not None:
        return str(explicit).strip().lower() in {"1", "true", "yes", "on"}
    return any(os.environ.get(name) for name in ("RENDER", "RENDER_SERVICE_ID", "RENDER_EXTERNAL_HOSTNAME"))


def uploads_enabled():
    return not is_backup_runtime()


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


def current_user_role():
    record = user_record_from_session(create=True) or {}
    if record.get("status") != "active":
        return "user"
    role = record.get("role") or "user"
    return role if role in {"user", "moderator", "admin"} else "user"


def is_current_admin():
    return current_user_role() == "admin"


def is_current_moderator():
    return current_user_role() in {"moderator", "admin"}


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

def drive_internal_path(rel_path=""):
    rel_path = (rel_path or "").replace("\\", "/").strip("/")
    if rel_path == "Users" or rel_path.startswith("Users/"):
        return "_users" + rel_path[5:]
    return rel_path


def drive_owner_key(rel_path=""):
    internal = drive_internal_path(rel_path)
    parts = [part for part in internal.split("/") if part]
    if len(parts) >= 2 and parts[0] == "_users":
        return parts[1]
    return ""


def drive_item_permissions(rel_path="", item_type="file"):
    owner_key = drive_owner_key(rel_path)
    role = current_user_role()
    owned = bool(owner_key and owner_key == current_user_key())
    internal = drive_internal_path(rel_path)
    parts = [part for part in internal.split("/") if part]
    is_root = internal in {"", "_users"}
    is_user_root = len(parts) == 2 and parts[0] == "_users"
    is_private = bool(owner_key)
    can_view = (not is_private) or owned or role in {"moderator", "admin"}
    can_download = can_view and not is_root
    can_share = can_download
    can_owner_manage = owned and not is_root and not is_user_root
    can_admin_manage = role == "admin" and can_view and not is_root
    return {
        "owned": owned,
        "owner": owner_key,
        "can_download": can_download,
        "can_share": can_share,
        "can_rename": can_owner_manage or can_admin_manage,
        "can_move": can_owner_manage or can_admin_manage,
        "can_delete": can_owner_manage or can_admin_manage,
    }


def can_view_drive_path(rel_path=""):
    internal = drive_internal_path(rel_path)
    if internal in {"", "_users"}:
        return True
    return bool(drive_item_permissions(rel_path).get("can_download"))


def can_delete_drive_path(rel_path=""):
    perms = drive_item_permissions(rel_path)
    return bool(perms.get("can_delete"))

def share_serializer():
    return URLSafeSerializer(app.secret_key, salt="favoriteweb-drive-share")


def make_share_token(display_path):
    return share_serializer().dumps({"path": drive_display_path(display_path), "ts": int(time.time())})



def send_path_download(file_path, download_name=None):
    if not file_path or not os.path.exists(file_path):
        return "Not Found", 404
    if os.path.isdir(file_path):
        temp_dir = tempfile.mkdtemp(prefix="favoriteweb-folder-")
        zip_base = os.path.join(temp_dir, download_name or os.path.basename(file_path) or "folder")
        archive_path = shutil.make_archive(zip_base, "zip", root_dir=file_path)

        @after_this_request
        def cleanup(response):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return response

        return send_file(archive_path, as_attachment=True, download_name=(download_name or os.path.basename(file_path) or "folder") + ".zip")
    return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path), as_attachment=True)

def shared_file_response(display_path, download=False):
    file_path = safe_drive_path(display_path)
    if not file_path or not os.path.exists(file_path):
        return "Not Found", 404
    if os.path.isdir(file_path):
        rows = []
        for name in sorted(os.listdir(file_path)):
            child_display = drive_display_path("/".join(part for part in [display_path.strip("/"), name] if part))
            child_path = safe_drive_path(child_display)
            child_token = make_share_token(child_display)
            icon = "&#128193;" if child_path and os.path.isdir(child_path) else "&#128196;"
            rows.append(f'<a class="share-item" href="/share/{child_token}"><span>{icon}</span><strong>{html_escape(name)}</strong></a>')
        body = "".join(rows) or '<div class="empty">This folder is empty.</div>'
        title = html_escape(os.path.basename(file_path) or "Shared Folder")
        return Response(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title><style>body{{margin:0;background:#070b16;color:#e5eefb;font-family:Arial,sans-serif}}main{{width:min(960px,calc(100% - 28px));margin:34px auto}}h1{{font-size:26px}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:14px}}.share-item{{min-height:110px;padding:16px;border:1px solid rgba(148,163,184,.16);border-radius:12px;background:rgba(255,255,255,.05);color:inherit;text-decoration:none;display:grid;align-content:center;gap:10px;text-align:center}}.share-item span{{font-size:32px}}.share-item strong{{font-size:13px;overflow-wrap:anywhere}}.empty{{padding:24px;border:1px dashed rgba(148,163,184,.2);border-radius:12px;color:#94a3b8}}</style></head><body><main><h1>{title}</h1><div class="grid">{body}</div></main></body></html>''', mimetype="text/html")
    mime, _ = mimetypes.guess_type(file_path)
    inline = mime and (mime.startswith("image") or mime.startswith("video") or mime.startswith("audio") or mime == "application/pdf" or mime.startswith("text"))
    return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path), as_attachment=download or not inline)


def html_escape(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

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

@app.route("/drive/upload", methods=["POST"])
@app.route("/upload", methods=["POST"])
def upload():

    blocked = active_user_required_json()
    if blocked:
        return blocked

    if not uploads_enabled():
        return jsonify({
            "error": "Backup mode is read-only. Please turn on a local FavoriteWeb PC server to upload files.",
            "backup_mode": True,
        }), 503

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

    role = current_user_role()
    user_key = current_user_key()
    if raw_path.startswith("Users/") and drive_owner_key(raw_path) not in {"", user_key} and role not in {"moderator", "admin"}:
        return jsonify({"error": "Not allowed"}), 403

    items = []
    if os.path.exists(full_path):
        entries = []
        if not raw_path:
            for name in os.listdir(full_path):
                if name == "_users":
                    continue
                rel_path = drive_display_path(name)
                entries.append((name, rel_path, os.path.join(full_path, name)))
            users_root = os.path.join(full_path, "_users")
            if os.path.isdir(users_root):
                if role in {"moderator", "admin"}:
                    for user_dir in os.listdir(users_root):
                        entries.append((user_dir, "Users/" + user_dir, os.path.join(users_root, user_dir)))
                else:
                    own_root = os.path.join(users_root, user_key)
                    if os.path.isdir(own_root):
                        for name in os.listdir(own_root):
                            entries.append((name, "Users/" + user_key + "/" + name, os.path.join(own_root, name)))
        elif raw_path == "Users":
            users_root = os.path.join(FILE_ROOT, "_users")
            if role in {"moderator", "admin"} and os.path.isdir(users_root):
                for user_dir in os.listdir(users_root):
                    entries.append((user_dir, "Users/" + user_dir, os.path.join(users_root, user_dir)))
            else:
                own_root = os.path.join(users_root, user_key)
                if os.path.isdir(own_root):
                    for name in os.listdir(own_root):
                        entries.append((name, "Users/" + user_key + "/" + name, os.path.join(own_root, name)))
        else:
            for name in os.listdir(full_path):
                if not raw_path and name == "_users":
                    continue
                rel_path = "/".join(part for part in [raw_path, name] if part)
                entries.append((name, drive_display_path(rel_path), os.path.join(full_path, name)))
        for item_name, display_path, item_path in entries:
            item_type = "folder" if os.path.isdir(item_path) else "file"
            perms = drive_item_permissions(display_path, item_type)
            if not (perms.get("can_download") or drive_internal_path(display_path) in {"", "_users"}):
                continue
            item = {
                "name": item_name,
                "path": display_path,
                "type": item_type,
            }
            item.update(perms)
            items.append(item)

    display_current = drive_display_path(raw_path)
    if raw_path == "Users" and role not in {"moderator", "admin"}:
        display_current = ""
    return jsonify({"current": display_current, "items": items})



def delete_drive_path(rel_path):
    internal_path = drive_internal_path(rel_path)
    full_path = safe_drive_path(rel_path)
    if not full_path or full_path == os.path.abspath(FILE_ROOT) or internal_path in {"", "_users"}:
        return jsonify({"error": "Invalid path"}), 400
    if not can_delete_drive_path(rel_path):
        return jsonify({"error": "Not allowed"}), 403
    if not os.path.exists(full_path):
        return jsonify({"error": "Not found"}), 404
    if os.path.isdir(full_path):
        shutil.rmtree(full_path)
    else:
        os.remove(full_path)
    return jsonify({"status": "ok"})


def rename_drive_path(rel_path, new_name):
    rel_path = drive_display_path(rel_path)
    new_name = (new_name or "").strip()
    if not rel_path or not new_name or "/" in new_name or "\\" in new_name:
        return jsonify({"error": "Invalid name"}), 400
    if not drive_item_permissions(rel_path).get("can_rename"):
        return jsonify({"error": "Not allowed"}), 403
    old_full = safe_drive_path(rel_path)
    parent_rel = "/".join(rel_path.split("/")[:-1])
    parent_full = safe_drive_path(parent_rel)
    if not old_full or not parent_full or not os.path.exists(old_full):
        return jsonify({"error": "Not found"}), 404
    new_full = os.path.abspath(os.path.join(parent_full, new_name))
    try:
        if os.path.commonpath([os.path.abspath(parent_full), new_full]) != os.path.abspath(parent_full):
            return jsonify({"error": "Invalid path"}), 400
    except ValueError:
        return jsonify({"error": "Invalid path"}), 400
    if os.path.exists(new_full):
        return jsonify({"error": "Name already exists"}), 409
    os.rename(old_full, new_full)
    return jsonify({"status": "ok"})


def move_drive_path(rel_path, dest_path):
    rel_path = drive_display_path(rel_path)
    dest_path = drive_display_path(dest_path)
    if not rel_path:
        return jsonify({"error": "Invalid path"}), 400
    if not drive_item_permissions(rel_path).get("can_move"):
        return jsonify({"error": "Not allowed"}), 403
    source_full = safe_drive_path(rel_path)
    dest_full = safe_drive_path(dest_path)
    if not source_full or not dest_full or not os.path.exists(source_full):
        return jsonify({"error": "Not found"}), 404
    if not os.path.isdir(dest_full) or not drive_item_permissions(dest_path).get("can_download"):
        return jsonify({"error": "Destination folder not found"}), 404
    target_full = os.path.abspath(os.path.join(dest_full, os.path.basename(source_full)))
    try:
        if os.path.commonpath([os.path.abspath(FILE_ROOT), target_full]) != os.path.abspath(FILE_ROOT):
            return jsonify({"error": "Invalid destination"}), 400
    except ValueError:
        return jsonify({"error": "Invalid destination"}), 400
    if target_full == source_full or target_full.startswith(source_full + os.sep):
        return jsonify({"error": "Invalid destination"}), 400
    if os.path.exists(target_full):
        return jsonify({"error": "Destination already has this name"}), 409
    shutil.move(source_full, target_full)
    return jsonify({"status": "ok"})


@app.route("/api/drive/delete", methods=["POST"])
def drive_delete():
    blocked = active_user_required_json()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    rel_path = (data.get("path") or "").strip().replace("\\", "/").strip("/")
    if not rel_path:
        return jsonify({"error": "Invalid path"}), 400
    return delete_drive_path(rel_path)


@app.route("/api/drive/rename", methods=["POST"])
def drive_rename():
    blocked = active_user_required_json()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    rel_path = (data.get("path") or "").strip().replace("\\", "/").strip("/")
    return rename_drive_path(rel_path, data.get("newName") or "")


@app.route("/api/drive/move", methods=["POST"])
def drive_move():
    blocked = active_user_required_json()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    rel_path = (data.get("path") or "").strip().replace("\\", "/").strip("/")
    dest_path = (data.get("destination") or "").strip().replace("\\", "/").strip("/")
    return move_drive_path(rel_path, dest_path)


@app.route("/api/admin/drive/delete", methods=["POST"])
def admin_drive_delete():
    blocked = admin_required_json()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    rel_path = (data.get("path") or "").strip().replace("\\", "/").strip("/")
    if not rel_path:
        return jsonify({"error": "Invalid path"}), 400
    return delete_drive_path(rel_path)


@app.route("/api/drive/share-link", methods=["POST"])
def drive_share_link():
    blocked = active_user_required_json()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    rel_path = (data.get("path") or "").strip().replace("\\", "/").strip("/")
    scope = (data.get("scope") or "drive").strip().lower()
    if not rel_path:
        return jsonify({"error": "Invalid path"}), 400
    if scope == "user":
        root, full_path = safe_user_path(rel_path)
        if not full_path or not os.path.exists(full_path):
            return jsonify({"error": "Not found"}), 404
        display_path = "Users/" + current_user_key() + "/" + rel_path
        allowed = True
    else:
        full_path = safe_drive_path(rel_path)
        if not full_path or not os.path.exists(full_path):
            return jsonify({"error": "Not found"}), 404
        display_path = drive_display_path(rel_path)
        item_type = "folder" if os.path.isdir(full_path) else "file"
        allowed = bool(drive_item_permissions(display_path, item_type).get("can_share"))
    if not allowed:
        return jsonify({"error": "Not allowed"}), 403
    token = make_share_token(display_path)
    return jsonify({"url": public_origin() + "/share/" + token})

@app.route("/share/<token>")
def drive_public_share(token):
    try:
        data = share_serializer().loads(token)
    except BadSignature:
        return "Not Found", 404
    display_path = drive_display_path(data.get("path") or "")
    return shared_file_response(display_path)


@app.route("/download/<path:filename>")
def download_own_file(filename):
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    root, file_path = safe_user_path(filename)
    if not file_path or not os.path.exists(file_path):
        return "Not Found", 404
    return send_path_download(file_path, os.path.basename(file_path) or "download")
@app.route("/drive/open/<path:filename>")
def drive_open_file(filename):
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    if not can_view_drive_path(filename):
        return "Not Found", 404
    file_path = safe_drive_path(filename)
    if not file_path or not os.path.exists(file_path) or os.path.isdir(file_path):
        return "Not Found", 404
    real_root = os.path.dirname(file_path)
    real_name = os.path.basename(file_path)
    mime, _ = mimetypes.guess_type(file_path)
    return send_from_directory(real_root, real_name, as_attachment=not (mime and (mime.startswith("image") or mime.startswith("video") or mime.startswith("audio") or mime == "application/pdf")))


@app.route("/drive/download/<path:filename>")
def drive_download_file(filename):
    blocked = active_user_required_redirect()
    if blocked:
        return blocked
    if not can_view_drive_path(filename):
        return "Not Found", 404
    file_path = safe_drive_path(filename)
    if not file_path or not os.path.exists(file_path):
        return "Not Found", 404
    return send_path_download(file_path, os.path.basename(file_path) or "download")
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

@app.route("/file")
def file_converter_legacy_redirect():
    return redirect("/file-converter")

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
            "is_admin": current_user_role() == "admin",
            "is_moderator": current_user_role() in {"moderator", "admin"},
            "used_bytes": used,
            "quota_bytes": quota,
            "backup_mode": is_backup_runtime(),
            "uploads_enabled": uploads_enabled(),
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
    role = current_user_role()
    can_view_all = role in {"moderator", "admin"}
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
        owned = record_owner == owner
        if not can_view_all and not owned:
            continue
        streams.append({
            "id": stream_id,
            "source": source,
            "title": title,
            "owner": record_owner or "",
            "owned": owned,
            "can_download": owned,
            "can_share": owned or role in {"moderator", "admin"},
            "can_edit": owned or role == "admin",
            "can_delete": owned or role == "admin",
            "video": f"{base}/ytplayer/stream/{stream_id}",
            "audio": f"{base}/ytplayer/play/{stream_id}",
        })

    return jsonify({"streams": streams, "role": role})


@app.route("/api/ytplayer/update", methods=["POST"])
def ytplayer_update():
    blocked = active_user_required_json()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    stream_id = str(data.get("id") or "")
    source = (data.get("source") or "").strip()
    slug = (data.get("slug") or "").strip()
    if not stream_id or not source:
        return jsonify({"error": "Invalid stream"}), 400

    data_path = os.path.join(BASE_DIR, "ytplayer", "videos.json")
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            videos = json.load(f)
    except Exception:
        videos = {}

    record = videos.get(stream_id)
    if not isinstance(record, dict):
        return jsonify({"error": "Not found"}), 404
    if record.get("owner") != current_user_key() and current_user_role() != "admin":
        return jsonify({"error": "Not allowed"}), 403
    new_stream_id = stream_id
    if slug:
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", slug):
            return jsonify({"error": "Slug can use letters, numbers, dash and underscore only"}), 400
        if slug != stream_id and slug in videos:
            return jsonify({"error": "Slug already exists"}), 409
        new_stream_id = slug
    record["url"] = source
    record["title"] = source
    if new_stream_id != stream_id:
        videos.pop(stream_id, None)
    videos[new_stream_id] = record
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
    if not isinstance(record, dict):
        return jsonify({"error": "Not found"}), 404
    if record.get("owner") != current_user_key() and not is_current_admin():
        return jsonify({"error": "Not allowed"}), 403
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
        if role in ("user", "moderator", "admin"):
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

converter_backend_path = Path(BASE_DIR) / "file-converter" / "routes.py"
if converter_backend_path.exists():
    converter_spec = importlib.util.spec_from_file_location("favoriteweb_file_converter", converter_backend_path)
    converter_module = importlib.util.module_from_spec(converter_spec)
    converter_spec.loader.exec_module(converter_module)
    converter_module.init_routes(app)

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
