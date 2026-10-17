# Starts backend (:8000) and frontend (:5173). Ctrl+C stops both.
$root = Split-Path -Parent $PSScriptRoot
$be = Start-Process -PassThru -NoNewWindow -WorkingDirectory "$root\backend" uv -ArgumentList "run", "python", "-m", "openterm", "--reload"
try {
  Push-Location "$root\frontend"
  npm run dev
} finally {
  Pop-Location
  taskkill /pid $be.Id /T /F | Out-Null
}
