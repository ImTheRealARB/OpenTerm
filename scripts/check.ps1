<#
.SYNOPSIS
  Runs only the checks a change can affect: tsc, ruff on changed files, and the pytest / vitest / Playwright files that depend on them.
.DESCRIPTION
  Thin wrapper over scripts/check.mjs (one planner for PowerShell and bash). The changed files come from `git diff --name-only`
  against the merge-base of -Base and HEAD, plus the working tree and untracked files.
.PARAMETER Base
  Git ref to compare against (default main).
.PARAMETER All
  Ignore the diff and run everything (ruff ., tsc, all pytest, vitest, Playwright).
.PARAMETER DryRun
  Print the plan and the commands, run nothing.
.PARAMETER NoE2e
  Leave Playwright out (it needs ports 4173 and 8000 free).
.PARAMETER Files
  Plan for these repo-relative paths instead of the git diff.
.EXAMPLE
  .\scripts\check.ps1 -DryRun
.EXAMPLE
  .\scripts\check.ps1 -NoE2e
#>
param(
  [string]$Base = "main",
  [switch]$All,
  [switch]$DryRun,
  [switch]$NoE2e,
  [string[]]$Files
)
$ErrorActionPreference = "Stop"
$planner = Join-Path $PSScriptRoot "check.mjs"
$nodeArgs = @($planner, "--base=$Base")
if ($All) { $nodeArgs += "--all" }
if ($DryRun) { $nodeArgs += "--dry-run" }
if ($NoE2e) { $nodeArgs += "--no-e2e" }
if ($Files) { $nodeArgs += ("--files=" + ($Files -join ",")) }
& node @nodeArgs
exit $LASTEXITCODE
