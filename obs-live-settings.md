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

Bitrate: `2500 Kbps` to `4500 Kbps`

Keyframe Interval: `2 s`

Preset: `veryfast` for x264, or `Quality` for hardware encoder

Profile: `main`

Tune: `zerolatency` if available

## Video

Base Canvas: `1920x1080`

Output Scaled: `1280x720` or `1920x1080`

FPS: `30`

## Audio

Sample Rate: `44.1 kHz` or `48 kHz`

Track 1 Bitrate: `128 Kbps`

## Offline Message

When OBS is off, run:

```text
start_live_offline_slate.bat
```

This publishes a custom offline video message. Keep it running; it uses the separate `offline` path, and the public URL automatically falls back to it when OBS is not publishing.
