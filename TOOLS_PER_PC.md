# FavoriteWeb Tools — PC Dependency List

কোন টুল কোন PC-তে চলবে (PC1 = KHAN, PC2 = HOST) এবং কোন টুল PC বন্ধ থাকলেও চলবে।

## 🟢 ক্লাউড/যেকোনো PC-তে চলবে (PC বন্ধ থাকলেও কাজ করবে)

এই টুলগুলোতে কোনো লোকাল ডিপেন্ডেন্সি নেই — শুধু ইন্টারনেট + Flask সার্ভার লাগে। Render/Cloudflare-এ হোস্ট করা থাকলে PC বন্ধ থাকলেও চলবে।

| টুল | লোকাল ডিপেন্ডেন্সি | PC বন্ধ থাকলে? |
|-----|-------------------|----------------|
| **Website Analyzer** (`/analytics`) | শুধু `requests` (HTTP) | ✅ চলবে |
| **Article Generate** (`/article-generate`) | Cloudflare AI API | ✅ চলবে |
| **Media Scraper** (`/media-scraper`) | শুধু Python stdlib (`urllib`) | ✅ চলবে |

## 🔴 লোকাল PC লাগবে (PC বন্ধ থাকলে কাজ করবে না)

এই টুলগুলোতে লোকাল প্রসেস/ফাইল/মডেল লাগে — তাই যে PC-তে Flask চলছে সেটি চালু থাকতে হবে।

| টুল | লোকাল ডিপেন্ডেন্সি | PC বন্ধ থাকলে? |
|-----|-------------------|----------------|
| **Media Downloader** (`/download`) | `yt_dlp` + `ffmpeg` (subprocess) | ❌ কাজ করবে না |
| **Cloud Drive** (`/drive`) | লোকাল ফাইল সিস্টেম (E:\web\file) | ❌ কাজ করবে না (backup mode-এ read-only) |
| **YT Stream Generator** (`/ytplayer`) | `yt_dlp` | ❌ কাজ করবে না |
| **OCR Tool** (`/ocr`) | `pytesseract` + Tesseract-OCR | ❌ কাজ করবে না |
| **Remove Background** (`/remove-bg`) | `rembg` AI মডেল | ❌ কাজ করবে না |
| **File Converter** (`/file-converter`) | `ffmpeg` (subprocess) | ❌ কাজ করবে না |
| **Media Transcribe** (`/media-transcribe`) | `ffmpeg` + Whisper AI মডেল | ❌ কাজ করবে না |

## 📊 সারসংক্ষেপ

| পরিস্থিতি | কোন টুল চলবে |
|-----------|-------------|
| **PC1 (KHAN) চালু, PC2 (HOST) বন্ধ** | সব টুল (PC1-এর লোকাল ডিপেন্ডেন্সি দিয়ে) |
| **PC2 (HOST) চালু, PC1 (KHAN) বন্ধ** | সব টুল (PC2-এর লোকাল ডিপেন্ডেন্সি দিয়ে) |
| **উভয় PC বন্ধ** | শুধু Website Analyzer, Article Generate, Media Scraper (যদি Render/Cloudflare-এ হোস্ট থাকে) |
| **Render/Cloudflare backup** | শুধু ক্লাউড-ভিত্তিক টুল (উপরের 🟢 তালিকা) |

## ⚠️ গুরুত্বপূর্ণ নোট

- **Cloud Drive** backup mode-এ read-only — আপলোড করতে লোকাল PC চালু থাকতে হবে
- **Media Downloader** ও **YT Stream**-এ `yt_dlp` + `ffmpeg` দুটোই লাগে — দুটোই PC-তে ইনস্টল থাকতে হবে
- **OCR**-এ Tesseract-OCR আলাদা ইনস্টল করা লাগে (Python প্যাকেজ নয়)
- **Media Transcribe**-এ Whisper মডেল প্রথমবার ডাউনলোড হয় — ইন্টারনেট + পর্যাপ্ত RAM/CPU লাগে
- **Remove Background**-এ rembg মডেল প্রথমবার ডাউনলোড হয়

## 🔧 PC-তে লোকাল ডিপেন্ডেন্সি চেক করার নিয়ম

```powershell
# ffmpeg আছে কিনা
ffmpeg -version

# Tesseract আছে কিনা
tesseract --version

# yt-dlp আছে কিনা
yt-dlp --version
```

যদি কোনো টুল কাজ না করে, উপরের কমান্ড দিয়ে লোকাল ডিপেন্ডেন্সি চেক করুন।