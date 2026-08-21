@echo off
title Media Scraper Tool
echo ============================================
echo    Media Scraper Tool - Starting...
echo ============================================
echo.

cd /d "%~dp0"

REM Check if Python is installed
where python >nul 2>nul
if %errorlevel%==0 (
    echo [OK] Python found. Starting server...
    echo.
    python server.py
    goto :end
)

REM Try python3 as fallback
where python3 >nul 2>nul
if %errorlevel%==0 (
    echo [OK] Python 3 found. Starting server...
    echo.
    python3 server.py
    goto :end
)

echo [ERROR] Python is not installed or not in PATH.
echo.
echo Please install Python from: https://www.python.org/downloads/
echo Make sure to check "Add Python to PATH" during installation.
echo.
pause
:end