# Desktop build (Tauri 2) and Docker

Status: the desktop app now carries its own backend (a frozen Python executable, the "sidecar"), so an installer works on
a machine without the OpenTerm source folder. **Verified on Windows 11 (2026-11-15):** the frozen backend itself (build, start,
`/api/health`, the frontend, a quote, backtest and quant jobs in worker processes, stop-with-parent). **Not verified:** the
Rust shell that starts it (no Rust toolchain was available; `desktop-check.yml` compiles it on GitHub), installers on any
OS, code signing, notarisation, a real updater round trip. Earlier, on Linux x86_64 (2026-11-10): the Docker image,
`docker compose up`, `scripts/start`, `scripts/install-launcher` and the (window-only) Linux bundles were built. See
"What was verified", `desktop/SIDECAR_NOTES.md` and "Owner steps" at the end.

## What the desktop app is
A Tauri window around the normal OpenTerm backend, which ships inside the app. `desktop/src-tauri/src/main.rs`:
1. picks a free port (8765 if free, otherwise any free one),
2. starts the backend: `binaries/openterm-backend`, the backend frozen into one executable (a Tauri "sidecar", see
   "The sidecar" below), with its settings passed as environment variables: frontend and `config.yaml` from the bundle
   resources, the SQLite database and `.env` in the per-user app data folder (Windows `%APPDATA%\dev.openterm.desktop`,
   macOS `~/Library/Application Support/dev.openterm.desktop`, Linux `~/.local/share/dev.openterm.desktop`),
3. waits until the port answers (120 s limit; stops early with the sidecar's last output if it dies),
4. opens one window on `http://127.0.0.1:<port>`,
5. kills the backend when the app exits (the backend also exits by itself if the shell disappears, see below).

The backend serves the built frontend itself, so the webview needs no IPC and no Tauri permissions beyond
`core:default`. The WebSocket and `/api` calls are same-origin, as in Docker.

Port note: the webview's browser storage (per-viewer things such as the tab layout) belongs to the address
`http://127.0.0.1:<port>`. Settings, layouts and watchlists are stored by the backend and survive a port change; the
per-viewer localStorage items do not, so 8765 is kept whenever it is free.

## Prerequisites
- Rust (stable) and the Tauri 2 system packages for your OS: <https://v2.tauri.app/start/prerequisites/>
- Node 22, `uv`, Python 3.12 (as for development). Building the sidecar also needs PyInstaller, which `uv` installs from the
  optional `freeze` dependency group (it is never a runtime dependency).

## Run in development
```
# terminal 1: the backend, as always
cd backend; uv run python -m openterm            # listens on 8000
# terminal 2: only the window
cd desktop; npm install
$env:OPENTERM_ATTACH = "1"; $env:OPENTERM_PORT = "8000"
npx tauri dev --config src-tauri/tauri.dev.conf.json
```
`OPENTERM_ATTACH=1` skips starting a backend and opens a window on the one already running on `OPENTERM_PORT`.
`tauri.dev.conf.json` switches off the sidecar and the bundled resources (a normal `tauri dev` / `tauri build` needs both
to exist, see below). Other overrides are listed at the top of `main.rs`.

## The sidecar (the backend inside the app)
`desktop/sidecar/` holds three files:
- `launcher.py`: the program PyInstaller freezes. It calls `multiprocessing.freeze_support()` first (the job runner starts
  worker processes with "spawn"; a frozen program re-runs itself for that), then runs uvicorn on `openterm.main:app`
  using the host, port and paths from the environment. If `OPENTERM_PARENT_PID` is set it stops itself a few seconds
  after that process is gone (the shell passes its own pid). This matters on Windows: a PyInstaller one-file program is
  a small launcher plus the real Python process, and killing only the launcher would leave the real one holding the port.
- `freeze.py`: runs PyInstaller (one-file, console) and copies the result to
  `desktop/src-tauri/binaries/openterm-backend-<rust target triple>[.exe]`, the name Tauri expects for
  `bundle.externalBin`. `--with-fixtures` also packs `backend/tests/fixtures` (14 MB) so `OPENTERM_FIXTURES=1` works;
  that is only for local smoke tests and must never be used for a release.
- `smoke.py`: starts the frozen executable the way the shell does and checks it (see "What was verified").

Backend change for this: `OPENTERM_CONFIG_PATH` (backend/openterm/config.py) names the `config.yaml` to read; unset keeps
the old behaviour (`<repo>/config.yaml`), a path that does not exist is an error.

Why PyInstaller: Tauri's sidecar wants one executable file, PyInstaller one-file makes exactly that, it has ready-made
handling for the libraries that break freezing (uvicorn, keyring, numpy/scipy/pandas data files) and needs no C compiler.
Cost: a one-file program unpacks itself into a temp folder on every start, so the backend takes about 8 s to answer on a
warm Windows machine and about 20 s on the first start after a build (antivirus scans the unpacked files); the shell
waits up to 120 s. The executable is about 80 MB. Same backend as everywhere else, no feature removed. Anything the
backend imports by name at run time has to be listed in `freeze.py` (the quant libraries, uvicorn parts, keyring
backends): when such an import is added to the backend, `smoke.py` is what catches a missing one.

## Build an installer
```
# 1. frontend
cd frontend; npm ci; npm run build
# 2. backend executable -> desktop/src-tauri/binaries/ (PyInstaller, about 3 minutes)
cd ..\backend; uv sync --group freeze
uv run --group freeze python ../desktop/sidecar/freeze.py
# 3. (optional) test it: starts it on a free port, needs no network
uv run python ../desktop/sidecar/smoke.py ../desktop/src-tauri/binaries/openterm-backend-<triple>[.exe] --mode synthetic
# 4. the shell and the installer
cd ..\desktop; npm ci; npx tauri build
```
Steps 1 and 2 must come first: `tauri.conf.json` names `../../frontend/dist` and `../../config.yaml`
(`bundle.resources`, copied to `frontend-dist/` and `config.yaml` in the app's resource folder) and
`binaries/openterm-backend` (`bundle.externalBin`), and Tauri refuses to build when they are missing.
In CI, `.github/actions/build-sidecar` does steps 1 to 3. Both `release.yml` (tag build) and `desktop-check.yml` use it;
`desktop-check` runs by hand or on pull requests that touch `desktop/`, and compiles the shell with
`tauri build --debug --no-bundle` on Windows, macOS and Linux (no tag, nothing published or signed).

## Before shipping to other people
Done: the backend is bundled (sidecar), the frontend and `config.yaml` are bundle resources, the database lives in the
per-user app data folder, a taken port 8765 is replaced by a free one. Still open:
- Replace the placeholder icon (amber prompt on black, 256 px source). The set in `src-tauri/icons/` (`.ico` for the
  Windows build, which fails without it; `.icns` for macOS) was made with `npx tauri icon <square png> -o src-tauri/icons`
  (2026-11-15); rerun that on a square 1024 px source for sharp icons and keep only the files `tauri.conf.json` lists.
- Code signing is NOT done (owner decision): unsigned installers trigger SmartScreen (Windows) and Gatekeeper (macOS)
  warnings, and PyInstaller programs are a common antivirus false positive. When signing is added, the sidecar needs it too.
- Run the installed app once on a clean machine: the Rust shell has never been compiled or run (no Rust toolchain was
  available when the sidecar was added); `desktop-check.yml` is the first compile.
- No splash screen: for the first seconds after launch no window is visible while the sidecar unpacks itself.
- `Cargo.lock` was not regenerated (no cargo here); the first build adds `tauri-plugin-shell` and its dependencies to it.
  Commit the updated lock file after the first successful build.

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

## What was verified (2026-11-15, frozen backend, Windows 11, PyInstaller 6.22, Python 3.12)
| Item | Result |
|---|---|
| `freeze.py` (release build, no fixtures) | passed, 86.7 MB, about 3 minutes |
| `smoke.py --mode synthetic` on that exe | passed: `/api/health` after 8 to 20 s, `/` serves the frontend, `/api/sources`, quote SYN0001, BT rule job and BT Python-strategy job (sandbox) in worker processes, quant jobs ADF, GARCH, DSR (statsmodels, arch, scipy), `/api/keys`, 35 AI desks from the packed data files, backend exits 2.4 s after its parent dies, no leftover processes |
| same with `--with-fixtures` build, `--mode fixtures` (AAPL quote, 10Y BT) | passed, 89.3 MB |
| `backend/tests/test_desktop_sidecar.py` (`OPENTERM_CONFIG_PATH`, parent watcher) | 4 passed |
| Rust shell (`main.rs`, `tauri-plugin-shell`, capability, `tauri.conf.json` resources and `externalBin`) | **not compiled** (no Rust here); `desktop-check.yml` is the first compile |
| `release.yml`, `desktop-check.yml`, `.github/actions/build-sidecar` | **not run** on GitHub; YAML written to match the existing release workflow |
| macOS and Linux frozen builds | not run (uvloop hidden import and keyring backends are the likely places for a miss) |

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
on GitHub. `tauri-action` is pinned to the commit of its `v0.5.17` tag (`2a8db2c`, checked with `git ls-remote` 2026-11-10).
Before `tauri-action` the workflow builds the frontend and freezes the backend sidecar on the same runner
(`.github/actions/build-sidecar`, which also smoke-tests it), so each bundle contains the backend. The workflow has still
not run on GitHub; use `desktop-check.yml` (manual) first.

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
5. Run `desktop-check` once from the Actions tab (it compiles the Rust shell, never compiled so far), commit the updated
   `Cargo.lock`, and launch an installed build on a clean machine. The real icon set listed under "Before shipping" is open.

## Static serving without Docker
```
$env:OPENTERM_STATIC_DIR = "..\frontend\dist"; cd backend; uv run python -m openterm
```
A relative path is resolved against the repository root. If the directory has no `index.html`, the backend logs a
warning and serves only the API.
