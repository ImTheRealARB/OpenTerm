#!/usr/bin/env bash
# Runs only the checks a change can affect: tsc, ruff on changed files, and the pytest / vitest / Playwright files that depend on them.
# Thin wrapper over scripts/check.mjs (one planner for bash and PowerShell; see its header for the mapping rules).
#   scripts/check.sh [--base REF] [--all] [--dry-run] [--no-e2e] [--files a,b]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --base) args+=("--base=$2"); shift 2 ;;
    --files) args+=("--files=$2"); shift 2 ;;
    --all|--dry-run|--no-e2e) args+=("$1"); shift ;;
    -h|--help) sed -n '2,4p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
exec node "$here/check.mjs" "${args[@]}"
