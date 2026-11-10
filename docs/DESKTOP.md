# Desktop build (Tauri 2) and Docker

Status (verified 2026-11-10 on Linux x86_64, Ubuntu 24.04): the Linux desktop build, the Docker image, `docker compose up`,
`scripts/start` and `scripts/install-launcher` were run. **Not verified:** Windows and macOS builds, code signing,
notarisation, a real updater round trip (needs the owner's key and a published release), and running the AppImage/deb
window (the build machine had no display). See "What was verified" and "Owner steps" at the end.

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

The static-file serving the image relies on is covered by `backend/tests/test_phase10.py`.

### Docker behind a proxy
If the build machine sits behind a TLS-intercepting proxy, `uv sync` fails with `invalid peer certificate: UnknownIssuer`.
Do not edit the Dockerfile; copy it to a local file that trusts your CA and pass the CA as a named build context:
```
sed -e '/^WORKDIR \/src\/frontend/a COPY --from=ca ca-bundle.crt /ca.crt\nENV NODE_EXTRA_CA_CERTS=/ca.crt' \
    -e '/^WORKDIR \/app\/backend/a COPY --from=ca ca-bundle.crt /ca.crt\nENV SSL_CERT_FILE=/ca.crt UV_SYSTEM_CERTS=1' \
    Dockerfile > /tmp/Dockerfile.local
docker build --build-context ca=/dir/with/ca-bundle.crt -f /tmp/Dockerfile.local -t openterm:local .
```
Docker Hub also rate-limits anonymous pulls per IP (`429 Too Many Requests` on `registry-1.docker.io`); wait or `docker login`.

## What was verified (2026-11-10)
| Item | Result |
|---|---|
| `docker build` (with the CA override above; this machine is behind an intercepting proxy) | passed, image 919 MB |
| `docker compose up` on a remapped port, `/api/health` 200, `/` 200, container `healthy`, `down -v` | passed |
| `docker compose -f deploy/docker-compose.remote.yml config` (with `OPENTERM_DOMAIN` set) | passed; not started or exposed |
| Tauri Linux build `npx tauri build --bundles deb,appimage` (Tauri CLI 2.12.4, Rust 1.97) | passed: `.deb` 1.66 MiB, `.AppImage` 76.84 MiB, under `desktop/src-tauri/target/release/bundle/` (not committed). The build downloads linuxdeploy from GitHub. Not launched (no display) |
| Release configuration build `--no-bundle --config src-tauri/tauri.release.conf.json --features updater` | compiled; no signature or update fetch exercised |
| `scripts/start --no-browser` | passed (installed packages, built the frontend, `/api/health` and `/` answered) |
| `scripts/install-launcher DIR` | passed (wrote the launcher) |
| `scripts/check.sh --dry-run` | passed |
| `scripts/setup`, `scripts/dev`, `scripts/gates.mjs` | not run: `setup` runs `npm ci`, `dev` is a long-running watcher, `gates.mjs` is the full gate |

Note for contributors: `scripts/start` runs `npm ci` when `package-lock.json` is newer than `node_modules/.package-lock.json`.
If `frontend/node_modules` is a symlink to another checkout, npm replaces it; use a real directory.

## Updater and release workflow
`desktop/src-tauri` has an optional `updater` cargo feature (`tauri-plugin-updater`). Developer builds do not include it and
need no keys. `.github/workflows/release.yml` runs on a `v*` tag, checks the tag equals `tauri.conf.json`'s version, builds
Linux (AppImage, deb), Windows (NSIS, MSI) and macOS (arm64 and Intel dmg/app) with `tauri-apps/tauri-action` and attaches
them to a **draft** release. With the updater key configured it also builds with `--features updater`, signs the update
artifacts and uploads `latest.json`; the app (when built with the feature) reads
`https://<repo>/releases/latest/download/latest.json`, verifies the signature against the public key, and by default only logs
that an update exists (`OPENTERM_AUTO_UPDATE=1` installs it, `OPENTERM_NO_UPDATE_CHECK=1` skips the check). With no secrets the
workflow still runs and produces unsigned bundles without an updater; the job summary says so. The workflow has not been run
on GitHub, and the action tag (`tauri-action@v0.5.17`) could not be checked online from the build machine.
The bundles still contain only the window, not the backend (see "Before shipping").

## Owner steps (cannot be done by an agent)
1. Updater key: `npx tauri signer generate -w ~/.tauri/openterm.key`. Store the private key and its password as the
   Actions secrets `TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`; store the public key as the
   Actions variable `TAURI_UPDATER_PUBKEY`. Never commit the private key.
2. macOS: an Apple Developer ID certificate exported as .p12 (`APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`,
   `APPLE_SIGNING_IDENTITY`) and notarisation credentials (`APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`). The macOS build and
   run were not tested; do it on a Mac before publishing a draft.
3. Windows: an Authenticode certificate and a `bundle.windows.signCommand` (or Azure Trusted Signing) in the config; unsigned
   installers trigger SmartScreen warnings.
4. Bump the version in `desktop/src-tauri/tauri.conf.json` and `Cargo.toml`, tag `vX.Y.Z`, review the draft, then publish it.
5. The sidecar backend and real icon set listed under "Before shipping" remain open.

## Static serving without Docker
```
$env:OPENTERM_STATIC_DIR = "..\frontend\dist"; cd backend; uv run python -m openterm
```
A relative path is resolved against the repository root. If the directory has no `index.html`, the backend logs a
warning and serves only the API.
