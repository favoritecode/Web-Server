$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $Root "favoriteweb_pc_config.ps1")

$ComputerName = $env:COMPUTERNAME.ToUpperInvariant()
$PcConfig = $FavoriteWebPcConfig[$ComputerName]

if (-not $PcConfig) {
    $CloudflaredDir = Join-Path $env:USERPROFILE ".cloudflared"
    foreach ($entry in $FavoriteWebPcConfig.GetEnumerator()) {
        $candidateTunnelId = $entry.Value.TunnelId
        if ($candidateTunnelId -and $candidateTunnelId -notlike "PUT_*") {
            $credentialPath = Join-Path $CloudflaredDir "$candidateTunnelId.json"
            if (Test-Path -LiteralPath $credentialPath) {
                $PcConfig = $entry.Value
                break
            }
        }
    }
}

if (-not $PcConfig) {
    throw "No config or matching cloudflared credential found for computer '$ComputerName' in favoriteweb_pc_config.ps1"
}

$TunnelId = $PcConfig.TunnelId
$BackendHostname = $PcConfig.BackendHostname

if (-not $TunnelId -or $TunnelId -like "PUT_*") {
    throw "TunnelId is not set for '$ComputerName' in favoriteweb_pc_config.ps1"
}

$CloudflaredDir = Join-Path $env:USERPROFILE ".cloudflared"
$ConfigPath = Join-Path $CloudflaredDir "config.yml"
$CredentialPath = Join-Path $CloudflaredDir "$TunnelId.json"

if (-not (Test-Path -LiteralPath $CredentialPath)) {
    throw "Missing tunnel credential file: $CredentialPath"
}

$LiveIngress = @(0..50 | ForEach-Object {
    $pathName = if ($_ -eq 0) { "live" } else { "live$_" }
    "  - hostname: $BackendHostname`n    path: /$pathName/*`n    service: http://127.0.0.1:8888`n"
}) -join "`n"

$config = @"
tunnel: $TunnelId
credentials-file: $CredentialPath

ingress:
$LiveIngress
  - hostname: $BackendHostname
    path: /offline/*
    service: http://127.0.0.1:8888

  - hostname: $BackendHostname
    path: /hls/*
    service: http://127.0.0.1:8080

  - hostname: $BackendHostname
    service: http://127.0.0.1:8010

  - service: http_status:404
"@

New-Item -ItemType Directory -Force -Path $CloudflaredDir | Out-Null
Set-Content -LiteralPath $ConfigPath -Value $config -NoNewline

Write-Host "[OK] Cloudflared ingress written:"
Write-Host "  $ConfigPath"
Write-Host ""
Write-Host "Backend hostname:"
Write-Host "  $BackendHostname"
Write-Host ""
Write-Host "Tunnel:"
Write-Host "  $TunnelId"
