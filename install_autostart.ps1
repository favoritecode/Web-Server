$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "install_favoriteweb_startup.ps1")
