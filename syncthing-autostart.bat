@echo off
:: Syncthing Auto-Start - Universal version
:: This will find syncthing.exe automatically

set "SYNCTHING_EXE="

:: Check common locations
if exist "C:\syncthing-windows-amd64-v2.1.1\syncthing.exe" set "SYNCTHING_EXE=C:\syncthing-windows-amd64-v2.1.1\syncthing.exe"
if exist "C:\Program Files\Syncthing\syncthing.exe" set "SYNCTHING_EXE=C:\Program Files\Syncthing\syncthing.exe"
if exist "C:\Program Files (x86)\Syncthing\syncthing.exe" set "SYNCTHING_EXE=C:\Program Files (x86)\Syncthing\syncthing.exe"

:: If not found, try to find it in PATH
if "%SYNCTHING_EXE%"=="" (
    for %%X in (syncthing.exe) do (
        if not "%%~$PATH:X"=="" set "SYNCTHING_EXE=%%~$PATH:X"
    )
)

:: If still not found, try common download folders
if "%SYNCTHING_EXE%"=="" (
    if exist "%USERPROFILE%\Downloads\syncthing-windows-amd64-v2.1.1\syncthing.exe" set "SYNCTHING_EXE=%USERPROFILE%\Downloads\syncthing-windows-amd64-v2.1.1\syncthing.exe"
    if exist "%USERPROFILE%\Desktop\syncthing-windows-amd64-v2.1.1\syncthing.exe" set "SYNCTHING_EXE=%USERPROFILE%\Desktop\syncthing-windows-amd64-v2.1.1\syncthing.exe"
)

:: Run if found
if not "%SYNCTHING_EXE%"=="" (
    start /B /MIN "" "%SYNCTHING_EXE%" --no-browser
) else (
    echo Syncthing not found! Please install first.
    pause
)