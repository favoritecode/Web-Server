# OBS Live Streaming Settings

Public playback URL:

```text
https://server.favoriteweb.net/live.m3u8
```

Extra stream playback URLs:

```text
https://server.favoriteweb.net/live1.m3u8
https://server.favoriteweb.net/live2.m3u8
https://server.favoriteweb.net/live3.m3u8
```

Use the same OBS settings on PC1 `khan` and PC2 `host`.

## Stream

Service: `Custom...`

Server:

```text
rtmp://127.0.0.1/live
```

Stream Key:

```text
live
```

Cloudflare Tunnel exposes playback globally, but OBS publishes locally to MediaMTX on whichever PC is broadcasting. Use this same OBS setting on both PC1 `khan` and PC2 `host`.

## Multiple Streams

Open multiple OBS copies or profiles. Keep Stream Key as `live`; only change the Server path:

```text
Main stream:  rtmp://127.0.0.1/live   -> https://server.favoriteweb.net/live.m3u8
Stream 1:     rtmp://127.0.0.1/live1  -> https://server.favoriteweb.net/live1.m3u8
Stream 2:     rtmp://127.0.0.1/live2  -> https://server.favoriteweb.net/live2.m3u8
Stream 3:     rtmp://127.0.0.1/live3  -> https://server.favoriteweb.net/live3.m3u8
```

PC1 and PC2 both support the same pattern after running `start_all_streaming.bat` once on each PC.

## Output

Output Mode: `Advanced`

Encoder: `x264` or your hardware encoder

Rate Control: `CBR`

Bitrate: `1200 Kbps` to `1800 Kbps` for smooth public streaming through Cloudflare Tunnel. Use `2500 Kbps` only if upload is very stable.

Keyframe Interval: `2 s`

Preset: `veryfast` or `superfast` for x264, or `Performance` / `Quality` for hardware encoder

Profile: `main`

Tune: `zerolatency` if available

## Video

Base Canvas: `1920x1080`

Output Scaled: `1280x720` recommended. Use `1920x1080` only for local/LAN viewing or very strong upload.

FPS: `30` recommended

## Audio

Sample Rate: `44.1 kHz` or `48 kHz`

Track 1 Bitrate: `128 Kbps`

## Offline Message

When OBS is off, run:

```text
start_live_offline_slate.bat
```

This publishes a custom offline video message. Keep it running; it uses the separate `offline` path, and the public URL automatically falls back to it when OBS is not publishing.

## Smooth Public Streaming Preset

Use this preset when viewers watch from `server.favoriteweb.net` through Cloudflare Tunnel:

```text
Resolution: 1280x720
FPS: 30
Rate Control: CBR
Video Bitrate: 1500 Kbps
Keyframe Interval: 2 s
Encoder: hardware encoder if available, otherwise x264
x264 Preset: superfast or veryfast
Profile: main
Audio Bitrate: 128 Kbps
```

If buffering continues, lower only the video bitrate first:

```text
1500 Kbps -> 1200 Kbps -> 900 Kbps
```

Do not use 1080p or 2500+ Kbps unless upload speed is stable above 8 Mbps while streaming.