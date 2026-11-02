# Runs OpenTerm as one app in the browser: builds the frontend when it is missing or out of date,
# serves it from the backend on :8000 and opens the default browser. Ctrl+C stops it.
# Usage: .\scripts\start.ps1 [-Rebuild] [-NoBrowser]
param([switch]$Rebuild, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$fe = Join-Path $root "frontend"
$dist = Join-Path $fe "dist"
$index = Join-Path $dist "index.html"

# Reinstall frontend packages when package-lock.json changed since the last install (e.g. after `git pull`).
# npm writes node_modules/.package-lock.json on every install, so a lockfile newer than it means new packages.
# The backend needs no check: `uv run` below already syncs its packages to uv.lock on every start.
$lock = Join-Path $fe "package-lock.json"
$installed = Join-Path $fe "node_modules\.package-lock.json"
$needInstall = -not (Test-Path $installed)
if (-not $needInstall) { $needInstall = (Get-Item $lock).LastWriteTimeUtc -gt (Get-Item $installed).LastWriteTimeUtc }
if ($needInstall) {
  Write-Host "Frontend packages changed: installing (npm ci)..."
  Push-Location $fe
  try { npm ci --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { throw "npm ci failed" } } finally { Pop-Location }
}

$stale = $Rebuild -or $needInstall -or -not (Test-Path $index)
if (-not $stale) {
  $built = (Get-Item $index).LastWriteTimeUtc
  $inputs = @(Get-ChildItem -Recurse -File (Join-Path $fe "src")) + @(Get-Item (Join-Path $fe "index.html"), (Join-Path $fe "package.json"))
  $stale = [bool]($inputs | Where-Object { $_.LastWriteTimeUtc -gt $built } | Select-Object -First 1)
}
if ($stale) {
  Write-Host "Building the frontend..."
  Push-Location $fe
  try { npm run build; if ($LASTEXITCODE -ne 0) { throw "frontend build failed" } } finally { Pop-Location }
}

$port = if ($env:OPENTERM_PORT) { $env:OPENTERM_PORT } else { "8000" }
$url = "http://localhost:$port"
$env:OPENTERM_STATIC_DIR = $dist
$be = Start-Process -PassThru -NoNewWindow -WorkingDirectory "$root\backend" uv -ArgumentList "run", "--no-dev", "python", "-m", "openterm"
try {
  $ready = $false
  for ($i = 0; $i -lt 60 -and -not $ready -and -not $be.HasExited; $i++) {
    # 127.0.0.1, not localhost: PowerShell 5.1 tries IPv6 first and loses ~2 s per request on "localhost".
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:$port/api/sources" | Out-Null; $ready = $true } catch { Start-Sleep -Milliseconds 500 }
  }
  if (-not $ready) { throw "backend did not start on $url (is the port in use?)" }
  Write-Host "OpenTerm is running at $url  (Ctrl+C to stop)"
  if (-not $NoBrowser) { Start-Process $url }
  Wait-Process -Id $be.Id
} finally {
  # Ctrl+C usually stops the child tree already; taskkill then only reports "no running instance".
  if (-not $be.HasExited) { cmd /c "taskkill /pid $($be.Id) /T /F >nul 2>&1" }
}
