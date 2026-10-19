# Installs an `openterm` command so that typing `openterm` in any Command Prompt or PowerShell window starts the app
# (same as .\scripts\start.ps1: builds the frontend if stale, serves http://localhost:8000, opens the browser).
# It writes one small openterm.cmd into a folder that is already on your PATH (default: %USERPROFILE%\.local\bin if it is on PATH,
# else the first writable folder under your profile on PATH). It changes no PATH, registry or system setting.
# Usage: .\scripts\install-launcher.ps1 [-Dir <folder>] [-Remove]     Run it from the checkout you want `openterm` to start.
# Flags after the command are passed on:  openterm -NoBrowser    openterm -Rebuild
param([string]$Dir = "", [switch]$Remove)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$start = Join-Path $root "scripts\start.ps1"
if (-not (Test-Path $start)) { throw "cannot find $start" }

$onPath = @($env:PATH -split ';' | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') })
if (-not $Dir) {
  $pref = Join-Path $env:USERPROFILE ".local\bin"
  $cands = @($pref) + @($onPath | Where-Object { $_ -like "$env:USERPROFILE*" -and $_ -notmatch 'WindowsApps|Packages|Programs' })
  foreach ($c in $cands) { if ($onPath -contains $c.TrimEnd('\') -and (Test-Path $c)) { $Dir = $c; break } }
  if (-not $Dir) { throw "no folder under $env:USERPROFILE is on your PATH; pass -Dir <a folder on PATH>" }
}
$target = Join-Path $Dir "openterm.cmd"
if ($Remove) { if (Test-Path $target) { Remove-Item $target; Write-Host "removed $target" } else { Write-Host "nothing to remove at $target" }; return }
if (-not ($onPath -contains $Dir.TrimEnd('\'))) { Write-Warning "$Dir is not on PATH: add it, or pick another folder with -Dir" }

# CRLF .cmd; -ExecutionPolicy Bypass only for this one script; %* forwards flags such as -NoBrowser.
$body = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$start`" %*`r`n"
[System.IO.File]::WriteAllText($target, $body, [System.Text.Encoding]::ASCII)
Write-Host "installed $target"
Write-Host "It starts OpenTerm from $root. Open a NEW Command Prompt and type: openterm"
