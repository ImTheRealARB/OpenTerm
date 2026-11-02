# One-command setup (Windows PowerShell 5.1+). Requires: uv, Node 20+.
# Default is the light install (just what it takes to RUN OpenTerm, about 330 MB).
# Add -Dev if you want to run the tests or change the code: that also installs the test and lint tools
# and a copy of the Chromium browser for the end-to-end tests (about 1.5 GB more).
param([switch]$Dev)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root\backend"
if ($Dev) { uv sync } else { uv sync --no-dev }
Pop-Location
Push-Location "$root\frontend"
if ($Dev) { npm install --no-audit --no-fund; npx playwright install chromium } else { npm ci --no-audit --no-fund }
Pop-Location
if (-not (Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env" }
Write-Host "Setup done. Run: .\scripts\start.ps1"
