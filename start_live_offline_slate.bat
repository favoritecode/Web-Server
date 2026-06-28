@echo off
cd /d "%~dp0"
title FavoriteWeb Offline Slate

echo ============================================
echo  FavoriteWeb Offline Live Slate
echo ============================================
echo.
echo This keeps publishing the custom offline HLS feed to MediaMTX.
echo If ffmpeg exits, it will restart automatically.
echo.

:loop
if exist "C:\ffmpeg\bin\ffmpeg.exe" (
  set "FFMPEG=C:\ffmpeg\bin\ffmpeg.exe"
) else (
  set "FFMPEG=ffmpeg"
)

"%FFMPEG%" -re -f lavfi -i "color=c=0x101418:s=1280x720:r=30" -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=44100" -vf "drawtext=text='Stream is offline':fontcolor=white:fontsize=56:x=(w-text_w)/2:y=(h-text_h)/2-40,drawtext=text='Please wait. Broadcast will start soon.':fontcolor=gray:fontsize=30:x=(w-text_w)/2:y=(h-text_h)/2+40" -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -g 60 -b:v 1800k -maxrate 1800k -bufsize 3600k -c:a aac -b:a 128k -f flv rtmp://127.0.0.1/offline

echo.
echo [WARN] Offline slate stopped. Restarting in 5 seconds...
timeout /t 5 /nobreak > nul
goto loop
