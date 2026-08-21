# FavoriteWeb Server restore on a new PC

This repository is the source backup for running FavoriteWeb on another Windows PC.

## 1) Install required software

- Git
- Python 3.12+ / 3.14
- Node.js
- FFmpeg available in `PATH`
- Cloudflared, if this PC will be exposed through a Cloudflare Tunnel

## 2) Clone and install

```powershell
git clone https://github.com/favoritecode/Web-Server.git E:\web
Set-Location E:\web
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --upgrade yt-dlp
```

## 3) Add local-only secrets

Create `E:\web\favoriteweb_local_secrets.py` on the new PC. Do not commit it.

Required values depend on which features you use, for example:

```python
CLOUDFLARE_API_TOKEN = "..."
GOOGLE_CLIENT_ID = "..."
GOOGLE_CLIENT_SECRET = "..."
```

If YouTube needs account cookies, put `cookies.txt` in `E:\web\cookies.txt`. Do not commit it.

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

Run the included startup installer from an elevated PowerShell:

```powershell
Set-Location E:\web
.\install_favoriteweb_startup.ps1
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

