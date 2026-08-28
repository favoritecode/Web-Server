# FavoriteWeb Server — সম্পূর্ণ A-Z সেটআপ গাইড

> এই গাইড পড়ে যে কেউ GitHub থেকে clone করে যেকোনো Windows PC-তে FavoriteWeb সার্ভার চালু করতে পারবে।

---

## সূচিপত্র

1. [প্রয়োজনীয় সফটওয়্যার](#1-প্রয়োজনীয়-সফটওয়্যার-ইনস্টল)
2. [Repository clone করা](#2-repository-clone-করা)
3. [Python virtual environment তৈরি](#3-python-virtual-environment-তৈরি)
4. [Local secrets ফাইল তৈরি](#4-local-secrets-ফাইল-তৈরি)
5. [Environment variables সেটআপ](#5-environment-variables-সেটআপ)
6. [External tools ইনস্টল](#6-external-tools-ইনস্টল-ঐচ্ছিক)
7. [সার্ভার চালু করা](#7-সার্ভার-চালু-করা)
8. [সার্ভার টেস্ট করা](#8-সার্ভার-টেস্ট-করা)
9. [Auto-start সেটআপ](#9-auto-start-সেটআপ-ঐচ্ছিক)
10. [Cloudflare Tunnel সেটআপ](#10-cloudflare-tunnel-সেটআপ-ঐচ্ছিক)
11. [ফিচার-ভিত্তিক ডিপেন্ডেন্সি তালিকা](#11-ফিচার-ভিত্তিক-ডিপেন্ডেন্সি-তালিকা)
12. [Render.com ব্যাকআপ ডিপ্লয়](#12-rendercom-ব্যাকআপ-ডিপ্লয়-ঐচ্ছিক)
13. [সমস্যা সমাধান](#13-সমস্যা-সমাধান-troubleshooting)

---

## 1. প্রয়োজনীয় সফটওয়্যার ইনস্টল

### আবশ্যক (Mandatory)

| সফটওয়্যার | ভার্সন | ডাউনলোড |
|-----------|--------|---------|
| **Git** | যেকোনো | https://git-scm.com/download/win |
| **Python** | 3.12 বা 3.14 | https://www.python.org/downloads/ |

> **গুরুত্বপূর্ণ:** Python ইনস্টল করার সময় **"Add Python to PATH"** অবশ্যই টিক দিন।

### ঐচ্ছিক (কোন ফিচার ব্যবহার করবেন তার উপর নির্ভর করে)

| সফটওয়্যার | কোন ফিচারে লাগে | ডাউনলোড |
|-----------|-----------------|---------|
| **Node.js** | Cloudflare Worker deploy | https://nodejs.org/ |
| **FFmpeg** | Media Download, File Convert, Transcribe | https://ffmpeg.org/download.html |
| **Tesseract-OCR** | OCR Tool | https://github.com/UB-Mannheim/tesseract/wiki |
| **Cloudflared** | Cloudflare Tunnel (ইন্টারনেটে এক্সপোজ) | https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ |
| **MediaMTX** | Live/Offline streaming | https://github.com/bluenviron/mediamtx/releases |

---

## 2. Repository clone করা

PowerShell খুলুন এবং রান করুন:

```powershell
# E:\web ফোল্ডারে clone (অথবা আপনার পছন্দের পাথ)
git clone https://github.com/favoritecode/Web-Server.git E:\web
```

> **নোট:** যদি অন্য পাথে clone করেন (যেমন `C:\web` বা `D:\favoriteweb`), তাহলে নিচের সব কমান্ডে `E:\web` এর বদলে সেই পাথ ব্যবহার করুন। সার্ভার যেকোনো ফোল্ডার থেকে চলবে।

---

## 3. Python virtual environment তৈরি

```powershell
Set-Location E:\web

# Virtual environment তৈরি
python -m venv .venv

# pip আপডেট
.\.venv\Scripts\python.exe -m pip install --upgrade pip

# সব Python প্যাকেজ ইনস্টল
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# yt-dlp সবসময় লেটেস্ট রাখুন
.\.venv\Scripts\python.exe -m pip install --upgrade yt-dlp
```

### requirements.txt এ কী কী আছে:

| প্যাকেজ | কাজ |
|---------|-----|
| Flask | মূল ওয়েব ফ্রেমওয়ার্ক |
| Werkzeug | WSGI ইউটিলিটি |
| requests | HTTP রিকোয়েস্ট (Analytics, fetching) |
| waitress | প্রোডাকশন WSGI সার্ভার |
| yt-dlp | YouTube/মিডিয়া ডাউনলোড |
| authlib | Google OAuth লগইন |
| Pillow | ইমেজ প্রসেসিং |
| pytesseract | OCR (Tesseract wrapper) |
| pypdf | PDF পড়া |
| pillow-heif | HEIF ইমেজ সাপোর্ট |
| rembg | ব্যাকগ্রাউন্ড রিমুভ (AI) |
| onnxruntime | rembg-এর AI মডেল |
| faster-whisper | স্পিচ-টু-টেক্সট (Transcribe) |

---

## 4. Local secrets ফাইল তৈরি

`E:\web\favoriteweb_local_secrets.py` ফাইল তৈরি করুন।

> **সতর্কতা:** এই ফাইল **কখনো git-এ commit করবেন না** — এটি `.gitignore`-এ আছে।

```python
# E:\web\favoriteweb_local_secrets.py

# Google OAuth (লগইন সিস্টেমের জন্য)
GOOGLE_CLIENT_ID = "আপনার-google-client-id"
GOOGLE_CLIENT_SECRET = "আপনার-google-client-secret"

# Gemini AI (Article Generate-এর জন্য — ঐচ্ছিক)
GEMINI_API_KEY = "আপনার-gemini-api-key"

# Cloudflare AI (Article Generate fallback — ঐচ্ছিক)
CLOUDFLARE_ACCOUNT_ID = "আপনার-cloudflare-account-id"
CLOUDFLARE_API_TOKEN = "আপনার-cloudflare-api-token"
```

### কোন key কোন ফিচারে লাগে:

| Key | ফিচার | আবশ্যক? |
|-----|--------|---------|
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | Google লগইন | হ্যাঁ (লগইন চাইলে) |
| `GEMINI_API_KEY` | AI Article Generate | না (ছাড়াও চলে) |
| `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | AI Article Generate (fallback) | না |
| `NVIDIA_API_KEY` | AI Article Generate (fallback) | না |
| `OPENAI_API_KEY` | AI Article Generate (fallback) | না |

> কোনো AI key না থাকলেও Article Generate চলবে — শুধু local education fallback ব্যবহার করবে।

### cookies.txt (YouTube-এর জন্য)

যদি YouTube ভিডিও ডাউনলোড/স্ট্রিম করতে চান, তাহলে `E:\web\cookies.txt` এ YouTube cookies রাখুন। এটাও git-এ push হবে না।

---

## 5. Environment Variables সেটআপ

সার্ভার দুইভাবে secrets পড়ে:
1. **Environment variables** (যেকোনো OS-এ কাজ করে)
2. **`favoriteweb_local_secrets.py`** (Windows PC-তে সুবিধাজনক)

দুটোর যেকোনো একটা ব্যবহার করলেই হবে। দুটো থাকলে environment variable-কে প্রাধান্য দেয়।

### `.env.example` দেখুন

Repository-তে `.env.example` ফাইলে সব variable-এর নমুনা আছে। রেফারেন্সের জন্য দেখুন — কিন্তু `.env` ফাইল সরাসরি সার্ভার পড়ে না, `favoriteweb_local_secrets.py` ব্যবহার করুন অথবা system environment variable সেট করুন।

### গুরুত্বপূর্ণ environment variables:

```
FLASK_SECRET_KEY=change-me          # সেশন signing key
FAVORITEWEB_APP_PORT=8010           # সার্ভার পোর্ট (ডিফল্ট 8010)
```

---

## 6. External Tools ইনস্টল (ঐচ্ছিক)

### FFmpeg (Media Download, File Convert, Transcribe)

1. https://ffmpeg.org/download.html থেকে ডাউনলোড করুন
2. Extract করুন
3. `ffmpeg.exe` PATH-এ রাখুন অথবা যেকোনো ফোল্ডারে রেখে PATH-এ যোগ করুন

চেক করুন:
```powershell
ffmpeg -version
```

### Tesseract-OCR (OCR Tool)

1. https://github.com/UB-Mannheim/tesseract/wiki থেকে Windows installer ডাউনলোড করুন
2. ইনস্টল করার সময় **Bengali (ben)** এবং **English (eng)** language data সিলেক্ট করুন
3. ইনস্টল পাথ PATH-এ যোগ করুন (সাধারণত `C:\Program Files\Tesseract-OCR`)

চেক করুন:
```powershell
tesseract --version
```

### Cloudflared (Cloudflare Tunnel)

`cloudflared.exe` ডাউনলোড করে `E:\web\cloudflared.exe` তে রাখুন।

### MediaMTX (Live Streaming)

MediaMTX ডাউনলোড করে `E:\web\mediamtx\mediamtx.exe` তে রাখুন।

---

## 7. সার্ভার চালু করা

### সহজ পদ্ধতি (Quick start):

```powershell
Set-Location E:\web
.\.venv\Scripts\python.exe app.py
```

সার্ভার চালু হলে দেখাবে:
```
[SERVER] Starting Waitress on 0.0.0.0:8010
```

### ব্যাকগ্রাউন্ডে চালাতে:

```powershell
Start-Process -FilePath "E:\web\.venv\Scripts\python.exe" `
  -ArgumentList "E:\web\app.py" `
  -WorkingDirectory "E:\web" `
  -WindowStyle Hidden
```

### Custom port দিতে:

```powershell
$env:FAVORITEWEB_APP_PORT = "9000"
.\.venv\Scripts\python.exe app.py
```

---

## 8. সার্ভার টেস্ট করা

### Health check:

```powershell
curl.exe -I http://127.0.0.1:8010/__server_health
```

সঠিক response:
```
HTTP/1.1 204 NO CONTENT
X-Favoriteweb-Backend: ok
```

### ব্রাউজারে দেখুন:

| URL | পেজ |
|-----|-----|
| http://localhost:8010/ | হোমপেজ |
| http://localhost:8010/analytics | Website / Article Analyzer |
| http://localhost:8010/download | Media Downloader |
| http://localhost:8010/ocr | OCR Tool |
| http://localhost:8010/file-converter | File Converter |
| http://localhost:8010/remove-bg | Background Remover |
| http://localhost:8010/article-generate | Article Generator |
| http://localhost:8010/media-transcribe | Media Transcriber |
| http://localhost:8010/media-scraper | Media Scraper |
| http://localhost:8010/ytplayer | YT Stream Player |
| http://localhost:8010/drive | Cloud Drive |

### প্রতিটি ফিচার ম্যানুয়ালি টেস্ট:

```powershell
# Website Analysis টেস্ট
curl.exe -X POST http://localhost:8010/api/analytics/scan `
  -H "Content-Type: application/json" `
  -d '{\"domain\":\"favoriteweb.net\",\"limit\":5}'

# Article Analysis টেস্ট (paste mode)
curl.exe -X POST http://localhost:8010/api/analytics/article `
  -H "Content-Type: application/json" `
  -d '{\"content\":\"<h1>Test Article</h1><p>This is a test article for SEO analysis.</p>\",\"keyword\":\"test\"}'
```

---

## 9. Auto-start সেটআপ (ঐচ্ছিক)

PC রিস্টার্ট হলে স্বয়ংক্রিয়ভাবে সার্ভার চালু হবে:

### ধাপ ১: PC config তৈরি করুন

`E:\web\favoriteweb_pc_config.ps1` ফাইল তৈরি করুন:

```powershell
$FavoriteWebPcConfig = @{
    # আপনার PC-র COMPUTERNAME ব্যবহার করুন
    # PowerShell-এ $env:COMPUTERNAME দিয়ে দেখুন
    "MY-PC-NAME" = @{
        TunnelId        = "PUT_YOUR_TUNNEL_ID_HERE"
        BackendHostname = "host.favoriteweb.net"
    }
}
```

> আপনার PC-র নাম জানতে PowerShell-এ লিখুন: `$env:COMPUTERNAME`

### ধাপ ২: Auto-start ইনস্টল করুন

```powershell
Set-Location E:\web
.\install_favoriteweb_startup.ps1
```

এটি Windows Startup ফোল্ডারে একটি শর্টকাট তৈরি করবে। পরবর্তী লগইনে সার্ভার স্বয়ংক্রিয়ভাবে চালু হবে।

### Auto-start কী কী করে:

1. GitHub থেকে লেটেস্ট কোড টানে (`git fetch` + selective checkout)
2. Python requirements আপডেট করে
3. Flask সার্ভার চালু করে (পোর্ট 8010)
4. Cloudflare Tunnel চালু করে (কনফিগার থাকলে)
5. MediaMTX চালু করে (ফাইল থাকলে)
6. Offline streaming slate চালু করে

### ভেরিফাই করুন:

```powershell
$Startup = [Environment]::GetFolderPath("Startup")
Test-Path (Join-Path $Startup "FavoriteWeb AutoStart.lnk")
# True হলে ইনস্টল সফল
```

---

## 10. Cloudflare Tunnel সেটআপ (ঐচ্ছিক)

> এটি শুধু তখন লাগবে যদি আপনি আপনার PC-র সার্ভারকে ইন্টারনেটে একটি ডোমেইনে (যেমন `server.favoriteweb.net`) এক্সপোজ করতে চান।

### ধাপ ১: Cloudflare login

```powershell
E:\web\cloudflared.exe login
```

### ধাপ ২: Tunnel তৈরি

```powershell
E:\web\cloudflared.exe tunnel create my-server-tunnel
```

### ধাপ ৩: DNS route

```powershell
E:\web\cloudflared.exe tunnel route dns my-server-tunnel your-hostname.yourdomain.com
```

### ধাপ ৪: Config আপডেট

`favoriteweb_pc_config.ps1` ফাইলে TunnelId আপডেট করুন।

### ধাপ ৫: Worker deploy (Optional — failover setup)

```powershell
Set-Location E:\web
npx wrangler deploy --config server-wrangler.toml
```

---

## 11. ফিচার-ভিত্তিক ডিপেন্ডেন্সি তালিকা

### কোনো external tool ছাড়াই চলে (শুধু Python + pip):

| ফিচার | URL | বিবরণ |
|--------|-----|-------|
| **Website Analyzer** | `/analytics` | ওয়েবসাইট SEO/টেক অডিট |
| **Article Analyzer** | `/analytics` → Article tab | আর্টিকেল SEO বিশ্লেষণ |
| **Article Generate** | `/article-generate` | AI আর্টিকেল তৈরি (API key লাগে) |
| **Media Scraper** | `/media-scraper` | ওয়েবপেজ থেকে মিডিয়া লিংক বের করা |
| **Cloud Drive** | `/drive` | ফাইল আপলোড/ডাউনলোড |
| **Homepage/Dashboard** | `/` | মূল হোমপেজ |

### FFmpeg লাগে:

| ফিচার | URL | বিবরণ |
|--------|-----|-------|
| **Media Downloader** | `/download` | YouTube/সোশ্যাল মিডিয়া ডাউনলোড |
| **File Converter** | `/file-converter` | ভিডিও/অডিও ফরম্যাট কনভার্ট |
| **Media Transcribe** | `/media-transcribe` | অডিও/ভিডিও থেকে টেক্সট |
| **YT Player** | `/ytplayer` | YouTube ভিডিও স্ট্রিম |

### আলাদা সফটওয়্যার লাগে:

| ফিচার | URL | কী লাগে |
|--------|-----|---------|
| **OCR Tool** | `/ocr` | Tesseract-OCR ইনস্টল |
| **Background Remover** | `/remove-bg` | rembg AI মডেল (প্রথমবার ডাউনলোড হয়) |
| **Media Transcribe** | `/media-transcribe` | faster-whisper মডেল (প্রথমবার ডাউনলোড হয়) |

---

## 12. Render.com ব্যাকআপ ডিপ্লয় (ঐচ্ছিক)

Repository-তে `render.yaml` আছে। Render.com-এ ডিপ্লয় করতে:

1. https://render.com এ যান
2. "New Web Service" → "From Git Repo" → `favoritecode/Web-Server` সিলেক্ট করুন
3. Environment Variables সেট করুন:
   - `FLASK_SECRET_KEY` (যেকোনো random string)
   - `GOOGLE_CLIENT_ID` (ঐচ্ছিক)
   - `GOOGLE_CLIENT_SECRET` (ঐচ্ছিক)
4. Deploy করুন

> **সতর্কতা:** Render free plan-এ OCR, Background Remove, Transcribe ইত্যাদি heavy ফিচার কাজ নাও করতে পারে (মেমরি/CPU সীমাবদ্ধতা)।

---

## 13. সমস্যা সমাধান (Troubleshooting)

### `python` কমান্ড কাজ করে না

```powershell
# Python PATH-এ আছে কিনা চেক
python --version

# না থাকলে full path ব্যবহার করুন
C:\Python314\python.exe --version
```

### `pip install` ব্যর্থ হচ্ছে

```powershell
# pip আপডেট করুন
.\.venv\Scripts\python.exe -m pip install --upgrade pip

# একটি একটি করে ইনস্টল করুন — কোনটায় error দেখুন
.\.venv\Scripts\python.exe -m pip install Flask requests waitress

# rembg/onnxruntime-এ সমস্যা হলে (GPU নেই):
.\.venv\Scripts\python.exe -m pip install onnxruntime-cpu
```

### সার্ভার চালু হচ্ছে কিন্তু ব্রাউজারে দেখা যাচ্ছে না

```powershell
# পোর্ট ব্লক আছে কিনা চেক
Test-NetConnection -ComputerName 127.0.0.1 -Port 8010

# Windows Firewall-এ allow করুন
New-NetFirewallRule -DisplayName "FavoriteWeb" -Direction Inbound -LocalPort 8010 -Protocol TCP -Action Allow
```

### Website/Article Analysis কাজ করছে না

```powershell
# সরাসরি API টেস্ট করুন
curl.exe -X POST http://localhost:8010/api/analytics/article `
  -H "Content-Type: application/json" `
  -d '{\"content\":\"<h1>Test</h1><p>Hello world</p>\"}'
```

### OCR কাজ করছে না

```powershell
# Tesseract ইনস্টল আছে কিনা
tesseract --version
# বাংলা language pack আছে কিনা
tesseract --list-langs
```

### Media Download কাজ করছে না

```powershell
# yt-dlp আপডেট করুন
.\.venv\Scripts\python.exe -m pip install --upgrade yt-dlp
# ffmpeg আছে কিনা
ffmpeg -version
# cookies দরকার হতে পারে — E:\web\cookies.txt এ YouTube cookies রাখুন
```

### git push পারমিশন নেই

```powershell
# GitHub credentials সেটআপ
git config --global user.name "আপনার নাম"
git config --global user.email "আপনার@email.com"
# HTTPS credential helper
git config --global credential.helper manager
```

---

## প্রজেক্ট ফোল্ডার স্ট্রাকচার

```
E:\web/
├── app.py                          # মূল Flask অ্যাপ্লিকেশন
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variables template
├── .gitignore                      # Git-এ কী push হবে না
├── render.yaml                     # Render.com deployment config
├── Aptfile                         # Linux system packages (Render-এ)
├── favoriteweb_local_secrets.py    # আপনার secret keys (gitignored)
├── favoriteweb_pc_config.ps1       # PC-ভিত্তিক config (gitignored)
├── favoriteweb_autostart.ps1       # Auto-start স্ক্রিপ্ট
├── install_favoriteweb_startup.ps1 # Auto-start installer
├── shared.css / shared.js          # শেয়ার্ড CSS/JS
├── index.html                      # হোমপেজ
├── dashboard.html                  # ড্যাশবোর্ড
├── SETUP_NEW_PC.md                 # এই সেটআপ গাইড
├── TOOLS_PER_PC.md                 # ফিচার ডিপেন্ডেন্সি তালিকা
├── Web Analytics Dashbord/         # Website + Article Analyzer
│   ├── analytics_backend.py        # Python backend
│   ├── app.js                      # Frontend JavaScript
│   ├── index.html                  # HTML page
│   └── styles.css                  # CSS
├── Article Generate/               # AI Article Generator
├── download/                       # Media Downloader
├── ytplayer/                       # YouTube Player
├── ocr/                            # OCR Tool
├── file-converter/                 # File Converter
├── remove-bg/                      # Background Remover
├── media-transcribe/               # Speech-to-Text
├── media-scraper/                  # Media Link Scraper
├── eee/                            # EEE Education content
├── shofikul/                       # Custom routes
└── .venv/                          # Python virtual env (gitignored)
```

---

## কুইক স্টার্ট (TL;DR)

একটি নতুন Windows PC-তে সব কিছু ৫ মিনিটে চালু করতে:

```powershell
# ১. Clone
git clone https://github.com/favoritecode/Web-Server.git E:\web
Set-Location E:\web

# ২. Venv + Install
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# ৩. Secrets (ঐচ্ছিক — ছাড়াও বেশিরভাগ ফিচার চলে)
# favoriteweb_local_secrets.py তৈরি করুন (উপরের section দেখুন)

# ৪. Run
.\.venv\Scripts\python.exe app.py

# ৫. Open: http://localhost:8010
```

> কোনো secret key, cookies, বা external tool ছাড়াও সার্ভার চালু হবে এবং Website Analyzer, Article Analyzer, Media Scraper, Cloud Drive, Homepage চলবে। শুধু নির্দিষ্ট ফিচারে (YouTube download, OCR, AI Generate) আলাদা dependency লাগে।
