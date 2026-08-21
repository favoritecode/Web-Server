# FavoriteWeb Server restore on a new PC

This repository is the source backup for running FavoriteWeb on another Windows PC.
Prefer `git clone` for a new server PC. The backup zip in `backups/` is an
emergency source snapshot; it does not include `.git`, runtime files, secrets,
cookies, or installed virtual environments.

## 1) Install required software

- Git
- Python 3.12+ / 3.14
- Node.js
- FFmpeg available in `PATH`
- Cloudflared, if this PC will be exposed through a Cloudflare Tunnel
- MediaMTX, if live/offline stream routes are needed

## 2) Clone and install

```powershell
git clone https://github.com/favoritecode/Web-Server.git E:\web
Set-Location E:\web
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --upgrade yt-dlp
```

If restoring from the backup zip instead of cloning, extract it to `E:\web`.
After zip restore, Git auto-update will be skipped until the folder is converted
back into a real Git clone.

## 3) Add local-only secrets

Create `E:\web\favoriteweb_local_secrets.py` on the new PC. Do not commit it.

Required values depend on which features you use, for example:

```python
CLOUDFLARE_API_TOKEN = "..."
GOOGLE_CLIENT_ID = "..."
GOOGLE_CLIENT_SECRET = "..."
```

If YouTube needs account cookies, put `cookies.txt` in `E:\web\cookies.txt`. Do not commit it.

For Cloudflare tunnel auto-start, place `cloudflared.exe` at:

```text
E:\web\cloudflared.exe
```

For live/offline streaming auto-start, place MediaMTX at:

```text
E:\web\mediamtx\mediamtx.exe
```

## 4) Start the server

```powershell
Set-Location E:\web
Start-Process -FilePath "E:\web\.venv\Scripts\python.exe" -ArgumentList "E:\web\app.py" -WorkingDirectory "E:\web" -WindowStyle Hidden
curl.exe -I http://127.0.0.1:8010/__server_health
```

Expected health response:

```text
HTTP/1.1 204 NO CONTENT
X-Favoriteweb-Backend: ok
```

## 5) Optional: install auto-start

Run the included startup installer from PowerShell:

```powershell
Set-Location E:\web
.\install_favoriteweb_startup.ps1
```

This creates:

```text
C:\Users\<you>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\FavoriteWeb AutoStart.lnk
```

On shutdown/restart, FavoriteWeb will auto-start after this Windows user logs in.
It starts:

- Flask app on port `8010`
- Cloudflare tunnel for this PC, if configured
- MediaMTX, if available
- offline slate stream

Verify auto-start is installed:

```powershell
$Startup = [Environment]::GetFolderPath("Startup")
Test-Path (Join-Path $Startup "FavoriteWeb AutoStart.lnk")
```

Expected:

```text
True
```

## 6) Deploy server.favoriteweb.net failover Worker

After Cloudflare login/token is configured:

```powershell
Set-Location E:\web
wrangler.cmd deploy --config server-wrangler.toml
```

The Worker priority is:

1. `khan.favoriteweb.net`
2. `host.favoriteweb.net`
3. Render backup for supported routes

For ytplayer media, the Worker quickly falls back to the next backend if the current PC is slow or returns protected/expired media errors.
