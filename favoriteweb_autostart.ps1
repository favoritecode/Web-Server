$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigFile = Join-Path $Root "favoriteweb_pc_config.ps1"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$App = Join-Path $Root "app.py"
$Cloudflared = Join-Path $Root "cloudflared.exe"
$MediaMtx = Join-Path $Root "mediamtx\mediamtx.exe"
$MediaMtxConfig = Join-Path $Root "mediamtx-live.yml"
$LogFile = Join-Path $Root "favoriteweb_autostart.log"

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -LiteralPath $LogFile -Value $line
}

. $ConfigFile
$ComputerName = $env:COMPUTERNAME.ToUpperInvariant()
$PcConfig = $FavoriteWebPcConfig[$ComputerName]

if (-not $PcConfig) {
    if ($Root.ToUpperInvariant().StartsWith("C:\WEB") -and $FavoriteWebPcConfig["HOST"]) {
        $PcConfig = $FavoriteWebPcConfig["HOST"]
        Write-Log "No exact config for $ComputerName. Selected HOST config because root is $Root."
    }
}

if (-not $PcConfig) {
    $CloudflaredDir = Join-Path $env:USERPROFILE ".cloudflared"
    foreach ($entry in $FavoriteWebPcConfig.GetEnumerator()) {
        $candidateTunnelId = $entry.Value.TunnelId
        if ($candidateTunnelId -and $candidateTunnelId -notlike "PUT_*") {
            $credentialPath = Join-Path $CloudflaredDir "$candidateTunnelId.json"
            if (Test-Path -LiteralPath $credentialPath) {
                $PcConfig = $entry.Value
                Write-Log "No exact config for $ComputerName. Auto-selected tunnel $candidateTunnelId from credentials."
                break
            }
        }
    }
}

if (-not $PcConfig) {
    $PcConfig = $FavoriteWebPcConfig["HOST"]
    Write-Log "No exact config or credential match for $ComputerName. Falling back to HOST config."
}

$TunnelId = $PcConfig.TunnelId
$BackendHostname = $PcConfig.BackendHostname

function Update-CloudflaredConfig {
    param(
        [string]$SelectedTunnelId,
        [string]$SelectedBackendHostname
    )

    if (-not $SelectedTunnelId -or $SelectedTunnelId -like "PUT_*" -or -not $SelectedBackendHostname) {
        Write-Log "Skipped cloudflared config update. Missing tunnel or hostname."
        return $false
    }

    $cloudflaredDir = Join-Path $env:USERPROFILE ".cloudflared"
    $credentialPath = Join-Path $cloudflaredDir "$SelectedTunnelId.json"
    $configPath = Join-Path $cloudflaredDir "config.yml"

    if (-not (Test-Path -LiteralPath $credentialPath)) {
        Write-Log "Skipped cloudflared config update. Missing credential: $credentialPath"
        return $false
    }

    New-Item -ItemType Directory -Force -Path $cloudflaredDir | Out-Null
    $LiveIngress = @(0..50 | ForEach-Object {
        $pathName = if ($_ -eq 0) { "live" } else { "live$_" }
        "  - hostname: $SelectedBackendHostname`n    path: /$pathName/*`n    service: http://127.0.0.1:8888`n"
    }) -join "`n"

    $config = @"
tunnel: $SelectedTunnelId
credentials-file: $credentialPath

ingress:
$LiveIngress
  - hostname: $SelectedBackendHostname
    path: /offline/*
    service: http://127.0.0.1:8888

  - hostname: $SelectedBackendHostname
    path: /hls/*
    service: http://127.0.0.1:8080

  - hostname: $SelectedBackendHostname
    service: http://127.0.0.1:8000

  - service: http_status:404
"@

    Set-Content -LiteralPath $configPath -Value $config -NoNewline
    Write-Log "Updated cloudflared config for $SelectedBackendHostname with tunnel $SelectedTunnelId"
    return $true
}

function Stop-MatchingProcess {
    param([string]$Pattern)

    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine -like $Pattern } |
        ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            } catch {}
        }
}

function Stop-Executable {
    param([string]$Path)

    Get-CimInstance Win32_Process |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.Equals($Path, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            } catch {}
        }
}

Set-Location $Root
Write-Log "Starting FavoriteWeb services on $ComputerName"

# Keep only one copy of each FavoriteWeb service.
Stop-MatchingProcess "*watchdog.py*"
Stop-MatchingProcess "*app.py*"
Stop-MatchingProcess "*start_live_offline_slate.bat*"
& taskkill.exe /IM cloudflared.exe /F 2>$null | Out-Null
& taskkill.exe /IM mediamtx.exe /F 2>$null | Out-Null
Stop-MatchingProcess "*ffmpeg*rtmp://127.0.0.1/offline*"

Start-Sleep -Seconds 2

Start-Process -FilePath $Python -ArgumentList "`"$App`"" -WorkingDirectory $Root -WindowStyle Hidden
Start-Sleep -Seconds 4

if ($TunnelId -and $TunnelId -notlike "PUT_*") {
    Update-CloudflaredConfig -SelectedTunnelId $TunnelId -SelectedBackendHostname $BackendHostname | Out-Null
    Start-Process -FilePath $Cloudflared -ArgumentList "tunnel", "run", $TunnelId -WorkingDirectory $Root -WindowStyle Hidden
    Write-Log "Started cloudflared tunnel $TunnelId"
} else {
    Write-Log "Skipped cloudflared. TunnelId is missing for $ComputerName in favoriteweb_pc_config.ps1"
}

Start-Process -FilePath $MediaMtx -ArgumentList "`"$MediaMtxConfig`"" -WorkingDirectory $Root -WindowStyle Hidden
Start-Sleep -Seconds 3

Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "start_live_offline_slate.bat" -WorkingDirectory $Root -WindowStyle Hidden
Write-Log "Started Flask, MediaMTX, and offline slate"
