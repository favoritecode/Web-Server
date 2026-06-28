@echo off
cd /d "%~dp0"
echo ============================================
echo  FavoriteWeb Live Streaming - MediaMTX
echo ============================================
echo.
echo Public playback URL:
echo   https://server.favoriteweb.net/live.m3u8
echo   https://server.favoriteweb.net/live1.m3u8
echo   https://server.favoriteweb.net/live2.m3u8
echo.
echo OBS server:
echo   rtmp://127.0.0.1/live
echo   rtmp://127.0.0.1/live1
echo   rtmp://127.0.0.1/live2
echo OBS stream key:
echo   live
echo.
echo Start start_live_offline_slate.bat in another window for the offline message.
echo.
echo Starting MediaMTX...
mediamtx\mediamtx.exe mediamtx-live.yml
pause
