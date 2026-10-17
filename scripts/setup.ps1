# One-command setup (Windows PowerShell 5.1+). Requires: uv, Node 20+.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root\backend"; uv sync; Pop-Location
Push-Location "$root\frontend"; npm install --no-audit --no-fund; npx playwright install chromium; Pop-Location
if (-not (Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env" }
Write-Host "Setup done. Run: .\scripts\dev.ps1"
