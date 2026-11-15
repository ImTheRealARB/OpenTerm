# Desktop sidecar: build notes (2026-11-15)

Goal: the desktop app works on a machine without the OpenTerm source folder, by shipping the backend as a Tauri sidecar.
User-facing instructions are in `docs/DESKTOP.md`; this file is the engineering record.

## What was built
| File | What |
|---|---|
| `desktop/sidecar/launcher.py` | Entry point that PyInstaller freezes. `multiprocessing.freeze_support()` first, then uvicorn on `openterm.main:app` (host/port from env). Optional `OPENTERM_PARENT_PID`: stops the server when that process is gone. |
| `desktop/sidecar/freeze.py` | PyInstaller one-file build; copies to `desktop/src-tauri/binaries/openterm-backend-<triple>[.exe]`. `--with-fixtures` packs test recordings (smoke only). |
| `desktop/sidecar/smoke.py` | Starts the exe like the shell does (own port, temp DB, parent stand-in) and checks it. |
| `backend/openterm/config.py` | New `OPENTERM_CONFIG_PATH` (unset = old behaviour; a set but missing path raises). |
| `backend/pyproject.toml`, `uv.lock` | Optional dependency group `freeze` = `pyinstaller>=6.10` (not a default group, not in the Docker image). Lock changed by additions only (pyinstaller, its hooks, pefile, macholib, setuptools, altgraph, ...). |
| `backend/tests/test_desktop_sidecar.py` | 4 tests: config path, missing path fails, default still reads the repo file, parent watcher. |
| `desktop/src-tauri/src/main.rs` | Rewritten around `tauri-plugin-shell`: free port, `app.shell().sidecar("openterm-backend")` with env, output drained, early-death detection, kill on exit. `OPENTERM_ATTACH=1` kept for development. |
| `desktop/src-tauri/Cargo.toml` | `tauri-plugin-shell = "2"`. |
| `desktop/src-tauri/tauri.conf.json` | `bundle.externalBin = ["binaries/openterm-backend"]`, `bundle.resources = {../../frontend/dist/ -> frontend-dist, ../../config.yaml -> config.yaml}`. |
| `desktop/src-tauri/tauri.dev.conf.json` | Override that empties both, for `tauri dev --config ...` with `OPENTERM_ATTACH=1`. |
| `desktop/src-tauri/capabilities/default.json` | `shell:allow-spawn` scoped to the sidecar (inert: no `remote` URLs; the spawn is from Rust). |
| `.github/actions/build-sidecar/action.yml` | Shared steps: setup-python 3.12, setup-uv, frontend build, freeze, smoke (`--mode synthetic`). |
| `.github/workflows/release.yml` | Calls the action before `tauri-action`. |
| `.github/workflows/desktop-check.yml` | New: `workflow_dispatch` + PR paths; windows-latest, macos-latest, ubuntu-22.04; `tauri build --debug --no-bundle`. |
| `docs/DESKTOP.md`, `docs/RELEASE_NOTES.md` | Updated. |

Pinned actions: `actions/setup-python` v5 = `a26af69be951a213d495a4c3e4e4022e16d87065` (looked up with `gh api .../git/ref/tags/v5`);
`astral-sh/setup-uv` reuses the SHA already in `ci.yml`.

## Decisions
- **PyInstaller one-file** (not Nuitka, not a Python folder in `resources`): Tauri's sidecar API wants one executable; the
  folder form would bypass the sidecar API. Cost: unpack on every start (8 s warm, 20 s cold here; the shell waits 120 s) and
  about 87 MB.
- **Parent-pid watcher** instead of relying on `child.kill()`: on Windows a one-file exe is a launcher process plus the real
  process; killing the launcher orphans the real one with the port. The shell passes its pid in `OPENTERM_PARENT_PID`;
  psutil (already a runtime dependency) polls it every 2 s and sets uvicorn's `should_exit`, so the normal shutdown runs
  (job workers stopped, DB closed). Verified: backend gone 2.4 s after its parent died, no leftover processes.
- **Free port**: prefer 8765 (keeps the webview's localStorage origin stable), else an OS-chosen port. There is a small race
  between probing and the sidecar binding; it surfaces as the startup error.
- **No splash screen**: the window is created after the port answers, so for the first seconds nothing is visible.
  A loading page would be the fix, but `navigate()` on a webview is not something I could test without Rust.
- **Dev flow**: the base `tauri.conf.json` now requires the sidecar file and `frontend/dist` to exist (Tauri checks at
  build time), so the dev window uses `tauri.dev.conf.json` + `OPENTERM_ATTACH=1`. The old `OPENTERM_BACKEND_CMD` /
  `OPENTERM_BACKEND_DIR` overrides were removed with `spawn_backend`.

## Things the freeze needed (found by running, not guessing)
- `--collect-submodules openterm` and `--collect-data openterm`: job kinds and the alpha zoo are imported by name; `ai/presets/*.yaml`, `ai/skills/*.md`, `quantlib/alpha/zoo_index.json` are read next to the module.
- statsmodels and arch are loaded through `importlib.import_module` (`quantlib/timeseries.py` `_require`); the first smoke run failed on ADF until they were listed as hidden imports. The list in `freeze.py` must match the `_require("...")` literals.
- uvicorn submodules, httptools, websockets (and uvloop off Windows); keyring submodules plus metadata.
- The server process still does not import pandas/numpy at startup (`launcher.py` imports only `openterm.main`).

## Verified (Windows 11, PyInstaller 6.22.3, Python 3.12.3)
- Release build (no fixtures) 86.7 MB; fixtures build 89.3 MB. About 3 minutes to build.
- `smoke.py --mode synthetic` on the release build and `--mode fixtures` on the fixtures build, both all PASS:
  health (8 to 20 s), `/` frontend, `/api/sources` (config.yaml read through `OPENTERM_CONFIG_PATH`), a quote, BT rule job,
  BT Python-strategy job (sandbox), quant jobs ADF / GARCH / DSR, `/api/keys`, 35 AI desks, stop-with-parent 2.4 s, no stray processes.
- A first run of the fixtures build timed out once on a 30 s request while a worker process was starting cold; the second run
  passed and the smoke timeout is now 90 s. Treat first-job latency after a fresh build as slow (tens of seconds worst case seen once).
- `uv run ruff check` on the changed Python: clean. `pytest -n 0 tests/test_desktop_sidecar.py`: 4 passed. No full suite was run.

## NOT verified
- **The Rust shell has never been compiled.** No Rust toolchain here. Written against Tauri 2 and `tauri-plugin-shell` 2:
  `app.shell().sidecar(name)` (name without `binaries/` in Rust), `.env()`, `.spawn()` -> `(Receiver<CommandEvent>, CommandChild)`,
  `CommandEvent::{Stdout, Stderr, Error, Terminated}` (matched with `_ => {}`; output bytes are read with `as_ref()` so either
  `Vec<u8>` or `String` compiles), `CommandChild::kill(self)`. Points to check first if it fails: the `resources` map syntax with a
  directory source, the capability entry, and whether the plugin inherits the parent environment (it should; if the sidecar
  lacks `SYSTEMROOT` etc. add `.env()` for them).
- **`Cargo.lock` was not regenerated** (no cargo). `tauri build` (not `--locked`) will add `tauri-plugin-shell` and its
  dependencies. Commit the updated lock after the first build.
- Windows console flash: the plugin should start the sidecar with `CREATE_NO_WINDOW`, but job worker processes spawned by the
  frozen exe were not tested under it.
- Installers, installed-app launch on a clean machine, macOS and Linux frozen builds (uvloop, keyring backends), the three
  workflows on GitHub, antivirus behaviour of an unsigned PyInstaller exe.

## Open risks
1. Rust compile errors (see above): the first `desktop-check` run is the real test.
2. Startup time of one-file (8 to 20 s with no window shown). If that is unacceptable: a splash page, or switch the sidecar to
   one-dir stored in `resources` and launched by path (faster start, but outside the sidecar API).
3. SmartScreen / antivirus warnings on an unsigned PyInstaller exe (no signing, owner decision); signing the app does not sign the sidecar.
4. Anything the backend later imports by name at run time must be added to `freeze.py`; `smoke.py` catches the common ones only.
5. Local-only files: `CLAUDE.md` (untracked) and the tracked `HANDOFF.md` were edited in this worktree; `HANDOFF.md` also carries an
   older uncommitted diff that was there before this work and is NOT part of the commit. Copy the CLAUDE.md edit to the main checkout by hand.
