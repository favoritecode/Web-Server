$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Startup = [Environment]::GetFolderPath("Startup")
$shell = New-Object -ComObject WScript.Shell

# Disable old/conflicting startup launchers.
$oldNames = @(
    "FavoriteWeb_Watchdog.lnk",
    "FavoriteWeb_Flask.lnk",
    "FavoriteWeb_Tunnel.lnk",
    "server-start.bat"
)

foreach ($name in $oldNames) {
    $path = Join-Path $Startup $name
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

Get-ChildItem -LiteralPath $Startup -Filter "*.disabled-by-favoriteweb" -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Force
}

Get-ChildItem -LiteralPath $Startup -Filter "*.lnk" | ForEach-Object {
    $shortcut = $shell.CreateShortcut($_.FullName)
    $target = "$($shortcut.TargetPath) $($shortcut.Arguments)"
    if ($target -match "launch_watchdog|watchdog\.bat|FavoriteWeb_Watchdog|E:\\web") {
        Remove-Item -LiteralPath $_.FullName -Force
    }
}

schtasks /delete /tn "FavoriteWeb_Watchdog" /f 2>$null | Out-Null
schtasks /delete /tn "FavoriteWeb_Flask" /f 2>$null | Out-Null
schtasks /delete /tn "FavoriteWeb_Tunnel" /f 2>$null | Out-Null

$shortcutPath = Join-Path $Startup "FavoriteWeb AutoStart.lnk"
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $Root "favoriteweb_autostart.vbs"
$shortcut.WorkingDirectory = $Root
$shortcut.Description = "Start FavoriteWeb Flask, Cloudflare tunnel, MediaMTX, and offline slate"
$shortcut.Save()

Write-Host "[OK] FavoriteWeb AutoStart installed:"
Write-Host "  $shortcutPath"
Write-Host ""
Write-Host "Run now:"
Write-Host "  $Root\start_all_streaming.bat"
