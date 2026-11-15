"""Freeze the OpenTerm backend into ONE executable and put it where Tauri expects a sidecar.

Run from `backend/` so uv uses the backend's locked environment (PyInstaller is in the optional `freeze` dependency
group, never a runtime dependency):

    cd backend
    uv sync --group freeze
    uv run --group freeze python ../desktop/sidecar/freeze.py            # release build
    uv run --group freeze python ../desktop/sidecar/freeze.py --with-fixtures   # + test recordings, for smoke tests only

Output: desktop/src-tauri/binaries/openterm-backend-<target triple>[.exe]
Tauri (bundle.externalBin = ["binaries/openterm-backend"]) looks for exactly that name: base name + "-" + the Rust target
triple of the machine it builds for, and strips the triple again when it copies the file next to the app.

Why PyInstaller (and not Nuitka, shiv, or `uv`'s standalone Python shipped as a folder)?
  * Tauri's sidecar wants ONE executable file. PyInstaller one-file produces that; a Python folder would have to go in
    `resources` and be launched by path, which skips the sidecar API (and its kill-on-exit handling).
  * It has ready-made hooks for the libraries that break freezing (uvicorn's string-based imports, keyring's backends,
    numpy / scipy / pandas data files), and it needs no C compiler, so the GitHub runners can run it as is.
  * Nuitka would give a faster start but needs a compiler toolchain on every OS and a much longer build.
The price of one-file: every start unpacks the program into a temp folder first (a few seconds, more on the first run
when antivirus scans it). See desktop/SIDECAR_NOTES.md.
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BACKEND = REPO / "backend"
NAME = "openterm-backend"  # must equal the tail of bundle.externalBin in tauri.conf.json

# (sys.platform, platform.machine().lower()) -> Rust target triple, for machines without `rustc` (the CI runs have both).
TRIPLES = {
    ("win32", "amd64"): "x86_64-pc-windows-msvc",
    ("win32", "arm64"): "aarch64-pc-windows-msvc",
    ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("darwin", "arm64"): "aarch64-apple-darwin",
    ("darwin", "x86_64"): "x86_64-apple-darwin",
}


def host_triple() -> str:
    """The Rust target triple of this machine. `rustc -vV` is the authority when Rust is installed."""
    try:
        out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            if line.startswith("host:"):
                return line.split(":", 1)[1].strip()
    except (OSError, subprocess.CalledProcessError):
        pass  # no Rust here: fall back to the table below
    key = (sys.platform if not sys.platform.startswith("linux") else "linux", platform.machine().lower())
    if key not in TRIPLES:
        raise SystemExit(f"unknown platform {key}: pass --triple")
    return TRIPLES[key]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--triple", help="Rust target triple for the file name (default: this machine's)")
    ap.add_argument("--out", type=Path, default=REPO / "desktop" / "src-tauri" / "binaries", help="where Tauri looks for sidecars")
    ap.add_argument("--with-fixtures", action="store_true",
                    help="also pack backend/tests/fixtures (14 MB) so OPENTERM_FIXTURES=1 works; for smoke tests, NEVER for a release")
    args = ap.parse_args()

    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        raise SystemExit("PyInstaller is missing: run this with `uv run --group freeze python ...` from backend/") from None

    triple = args.triple or host_triple()
    exe_suffix = ".exe" if "windows" in triple else ""
    sep = ";" if sys.platform == "win32" else ":"  # PyInstaller's --add-data separator is the OS path separator
    work = HERE / "build"  # PyInstaller's scratch folder (git-ignored)

    pyi_args = [
        str(HERE / "launcher.py"),
        "--name", NAME,
        "--onefile",
        "--console",  # the shell reads stdout/stderr; Tauri hides the console window itself
        "--noconfirm", "--clean",
        "--distpath", str(work / "dist"),
        "--workpath", str(work / "work"),
        "--specpath", str(work),
        "--paths", str(BACKEND),
        # Everything under openterm, including modules that are only imported by name at run time
        # (job kinds, the alpha zoo, uvicorn's loops). The static analysis would miss those.
        "--collect-submodules", "openterm",
        # Non-Python files inside the package: AI desks (ai/presets/*.yaml), skills (ai/skills/*.md), the alpha zoo index.
        "--collect-data", "openterm",
        # uvicorn picks its event loop, HTTP and websocket implementations by string name.
        "--collect-submodules", "uvicorn",
        "--hidden-import", "httptools",
        "--hidden-import", "websockets",
        # backend/openterm/quantlib/timeseries.py loads these by name (`_require("statsmodels.api", ...)`), which static analysis
        # cannot see. Keep this list equal to the `_require("...")` literals there (smoke.py runs ADF / GARCH to catch a miss).
        *[a for m in ("arch", "statsmodels.api", "statsmodels.stats.diagnostic", "statsmodels.stats.outliers_influence",
                      "statsmodels.stats.stattools", "statsmodels.tsa.regime_switching.markov_regression",
                      "statsmodels.tsa.stattools") for a in ("--hidden-import", m)],
        # keyring finds its OS backends through package metadata (entry points), which a frozen app does not have by default.
        "--collect-submodules", "keyring",
        "--copy-metadata", "keyring",
        # Not used at run time; keeps the file smaller.
        "--exclude-module", "tkinter", "--exclude-module", "pytest", "--exclude-module", "IPython",
        "--exclude-module", "matplotlib", "--exclude-module", "PIL",
    ]
    if sys.platform != "win32":
        pyi_args += ["--hidden-import", "uvloop"]  # no Windows build of uvloop exists
    if args.with_fixtures:
        # backend/openterm/providers/fixtures.py reads <package parent>/tests/fixtures; in a frozen app that parent is the
        # unpack folder, so the files go to "tests/fixtures" at its top level.
        pyi_args += ["--add-data", f"{BACKEND / 'tests' / 'fixtures'}{sep}tests/fixtures"]

    print("pyinstaller", *pyi_args[1:], flush=True)
    pyi.run(pyi_args)

    built = work / "dist" / (NAME + exe_suffix)
    if not built.is_file():
        raise SystemExit(f"PyInstaller did not produce {built}")
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{NAME}-{triple}{exe_suffix}"
    shutil.copy2(built, target)
    print(f"sidecar: {target} ({target.stat().st_size / 1e6:.1f} MB, fixtures={'yes' if args.with_fixtures else 'no'})")


if __name__ == "__main__":
    main()
