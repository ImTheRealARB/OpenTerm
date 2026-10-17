# Desktop build (Tauri 2) and Docker

Status: **scaffold, not built or run.** The machine that wrote it had no Rust toolchain and no Docker. Treat every
command below as unverified until someone runs it.

## What the desktop app is
A Tauri window around the normal OpenTerm backend. `desktop/src-tauri/src/main.rs`:
1. starts the backend (`uv run python -m openterm` in `backend/`) with `OPENTERM_STATIC_DIR=frontend/dist`,
2. waits until the port answers (30 s limit),
3. opens one window on `http://127.0.0.1:8765`,
4. kills the backend when the app exits.

The backend serves the built frontend itself, so the webview needs no IPC and no Tauri permissions beyond
`core:default`. The WebSocket and `/api` calls are same-origin, as in Docker.

## Prerequisites
- Rust (stable) and the Tauri 2 system packages for your OS: <https://v2.tauri.app/start/prerequisites/>
- Node 22, `uv`, Python 3.12 (as for development)

## Run in development
```
cd frontend; npm ci; npm run build        # frontend/dist must exist
cd ..\desktop; npm install
npx tauri dev
```
`OPENTERM_ATTACH=1` skips spawning and opens a window on a backend you already started
(`OPENTERM_PORT` must match). Other overrides are listed at the top of `main.rs`.

## Build an installer
```
cd desktop; npx tauri build
```
This bundles **only the window**. It still expects the repository checkout (backend sources, `uv`, `frontend/dist`)
next to the binary, which is fine for a developer install but not for distribution.

## Before shipping to other people (not done)
- Freeze the backend into a sidecar executable (for example PyInstaller or `uv`'s standalone Python) and declare it
  in `tauri.conf.json` under `bundle.externalBin`; replace `spawn_backend` with the sidecar API.
- Copy `frontend/dist` and `config.yaml` into the bundle `resources` and point `OPENTERM_STATIC_DIR` at them.
- Put the SQLite file in the per-user app data directory (`OPENTERM_DB_PATH`), not the repo's `data/`.
- Generate the real icon set from a source image: `npx tauri icon path/to/icon.png`. `icons/icon.png` is a plain
  placeholder (amber prompt on black).
- Code-sign the installers (Windows Authenticode, macOS notarisation).
- A port collision on 8765 currently fails startup with a message. Choose a free port at launch if that matters.

## Docker
```
docker build -t openterm .
docker run --rm -p 8000:8000 -v openterm-data:/data openterm
# or
docker compose up --build
```
Open <http://localhost:8000>. The image has two stages: Node builds `frontend/dist`, then a Python 3.12 slim image
installs the locked backend with `uv` and serves the API, the WebSocket and the static frontend on port 8000
(`OPENTERM_STATIC_DIR=/app/frontend/dist`). Layouts, watchlists, settings and the cache live in the `/data` volume
(`OPENTERM_DB_PATH=/data/openterm.db`). The container runs as an unprivileged user and has a health check on
`/api/health`. Optional API keys are passed as environment variables (see `docker-compose.yml`); nothing needs a key.

The Dockerfile was **not built** on the machine that wrote it (Docker not installed). The static-file serving it relies
on is covered by `backend/tests/test_phase10.py`.

## Static serving without Docker
```
$env:OPENTERM_STATIC_DIR = "..\frontend\dist"; cd backend; uv run python -m openterm
```
A relative path is resolved against the repository root. If the directory has no `index.html`, the backend logs a
warning and serves only the API.
