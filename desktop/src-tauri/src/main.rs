// OpenTerm desktop shell (Tauri 2). See docs/DESKTOP.md.
//
// What it does, in order:
//   1. picks a free local port (8765 if it is free, otherwise any free one),
//   2. starts the backend: a frozen Python program shipped inside the app as a Tauri "sidecar"
//      (bundle.externalBin = binaries/openterm-backend, built by desktop/sidecar/freeze.py),
//   3. waits until that port answers (and stops with a message if the sidecar dies first),
//   4. opens one window on http://127.0.0.1:<port>,
//   5. kills the sidecar when the app exits.
//
// The backend serves the built frontend itself, so the window is a plain webview and needs no IPC. Everything the
// backend needs is handed over as environment variables (the same ones the normal backend reads, see
// desktop/sidecar/launcher.py for the list):
//   frontend  -> <resource dir>/frontend-dist      (bundle.resources)
//   config    -> <resource dir>/config.yaml        (bundle.resources)
//   database  -> <per-user app data dir>/openterm.db   (e.g. %APPDATA%\dev.openterm.desktop on Windows)
//   API keys  -> <per-user app data dir>/.env      (only used when the OS has no keyring)
//
// Environment of the shell itself (all optional):
//   OPENTERM_PORT           preferred backend port, default 8765 (not 8000, so it can run next to `scripts/dev.ps1`)
//   OPENTERM_ATTACH=1       do not start a backend; open a window on one that is already running on OPENTERM_PORT
//                           (this is the developer workflow: `uv run python -m openterm` in another terminal)
//   OPENTERM_NO_UPDATE_CHECK=1   skip the update check (release builds only, see below)
//   OPENTERM_AUTO_UPDATE=1       install an available update instead of only logging it (release builds only)
//
// Updater: compiled only with `--features updater` (the release workflow). It reads a static manifest (latest.json)
// published as a release asset, verifies the download against the public key in tauri.release.conf.json, and
// by default only logs "update X is available". A developer build has no updater and no keys.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// File name of the sidecar without the target triple: the tail of `bundle.externalBin` in tauri.conf.json.
const SIDECAR: &str = "openterm-backend";
const DEFAULT_PORT: u16 = 8765;
/// A one-file Python program unpacks itself on every start (a few seconds; the first run after an install is the
/// slowest because antivirus scans it), so the wait is generous.
const STARTUP_TIMEOUT: Duration = Duration::from_secs(120);

/// The running sidecar, kept so the exit handler can stop it.
struct Backend(Mutex<Option<CommandChild>>);

/// Set by the task that reads the sidecar's output when the sidecar ends: what it printed last, for the error message.
type Died = Arc<Mutex<Option<String>>>;

/// Port to use: the preferred one if nothing is listening there, otherwise one the OS picks.
/// (Binding and dropping the listener frees the port again; another program could grab it in between, which is rare
/// and shows up as the startup error below.)
fn pick_port() -> u16 {
    let preferred = std::env::var("OPENTERM_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(DEFAULT_PORT);
    if TcpListener::bind(("127.0.0.1", preferred)).is_ok() {
        return preferred;
    }
    // Port 0 means "any free port".
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .expect("no free local port")
}

/// Start the frozen backend and return its handle plus a slot that is filled if it ends.
fn start_backend(app: &tauri::App, port: u16) -> Result<(CommandChild, Died), Box<dyn std::error::Error>> {
    let resources = app.path().resource_dir()?;
    let data_dir = app.path().app_data_dir()?;
    std::fs::create_dir_all(&data_dir)?;

    // `sidecar()` finds the executable next to the app's own executable, where the bundler puts it (without the triple).
    // The shell plugin lets the child inherit this process's environment and adds the variables below.
    let (mut rx, child) = app
        .shell()
        .sidecar(SIDECAR)?
        .env("OPENTERM_HOST", "127.0.0.1")
        .env("OPENTERM_PORT", port.to_string())
        .env("OPENTERM_STATIC_DIR", resources.join("frontend-dist"))
        .env("OPENTERM_CONFIG_PATH", resources.join("config.yaml"))
        .env("OPENTERM_DB_PATH", data_dir.join("openterm.db"))
        .env("OPENTERM_DOTENV_PATH", data_dir.join(".env"))
        // The backend exits by itself once this process is gone. Needed on Windows, where killing a one-file Python
        // program only kills its small launcher and leaves the real process (and the port) behind.
        .env("OPENTERM_PARENT_PID", std::process::id().to_string())
        .spawn()?;

    // The plugin hands the child's output over a small channel; if nobody reads it, the child blocks once it is full.
    // So: always drain it, and remember the last lines for the error message if the sidecar dies.
    let died: Died = Arc::new(Mutex::new(None));
    let died_writer = died.clone();
    tauri::async_runtime::spawn(async move {
        let mut tail: Vec<String> = Vec::new();
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    let text = String::from_utf8_lossy(line.as_ref()).trim_end().to_string();
                    eprintln!("[backend] {text}");
                    tail.push(text);
                    if tail.len() > 20 {
                        tail.remove(0);
                    }
                }
                CommandEvent::Error(e) => eprintln!("[backend] error: {e}"),
                CommandEvent::Terminated(payload) => {
                    *died_writer.lock().unwrap() =
                        Some(format!("it exited (code {:?}). Last output:\n{}", payload.code, tail.join("\n")));
                    break;
                }
                _ => {}
            }
        }
    });
    Ok((child, died))
}

/// Wait until `port` accepts connections. Err = the sidecar ended first, or the time ran out.
fn wait_for_port(port: u16, died: Option<&Died>, timeout: Duration) -> Result<(), String> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let start = Instant::now();
    while start.elapsed() < timeout {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
            return Ok(());
        }
        if let Some(why) = died.and_then(|d| d.lock().unwrap().clone()) {
            return Err(format!("the backend stopped before it opened port {port}: {why}"));
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    Err(format!("the backend did not open port {port} within {} s", timeout.as_secs()))
}

#[cfg(feature = "updater")]
async fn check_for_update(app: tauri::AppHandle) {
    use tauri_plugin_updater::UpdaterExt;
    if std::env::var("OPENTERM_NO_UPDATE_CHECK").map(|v| v == "1").unwrap_or(false) {
        return;
    }
    let updater = match app.updater() {
        Ok(u) => u,
        Err(e) => return eprintln!("update check unavailable: {e}"),
    };
    match updater.check().await {
        Ok(Some(update)) => {
            eprintln!("OpenTerm update {} is available (running {})", update.version, update.current_version);
            if std::env::var("OPENTERM_AUTO_UPDATE").map(|v| v == "1").unwrap_or(false) {
                match update.download_and_install(|_, _| {}, || {}).await {
                    Ok(()) => eprintln!("update installed; it applies on the next start"),
                    Err(e) => eprintln!("update failed: {e}"),
                }
            }
        }
        Ok(None) => {}
        Err(e) => eprintln!("update check failed: {e}"),
    }
}

fn main() {
    let attach = std::env::var("OPENTERM_ATTACH").map(|v| v == "1").unwrap_or(false);

    let builder = tauri::Builder::default().plugin(tauri_plugin_shell::init());
    #[cfg(feature = "updater")]
    let builder = builder.plugin(tauri_plugin_updater::Builder::new().build());
    let app = builder
        .manage(Backend(Mutex::new(None)))
        .setup(move |app| {
            let port;
            if attach {
                // Developer workflow: the backend is somebody else's job; use the port they said.
                port = std::env::var("OPENTERM_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(DEFAULT_PORT);
                wait_for_port(port, None, Duration::from_secs(30))?;
            } else {
                port = pick_port();
                let (child, died) = start_backend(app, port).map_err(|e| format!("cannot start the backend: {e}"))?;
                *app.state::<Backend>().0.lock().unwrap() = Some(child);
                wait_for_port(port, Some(&died), STARTUP_TIMEOUT)?;
            }
            let url = format!("http://127.0.0.1:{port}");
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.parse().unwrap()))
                .title("OpenTerm")
                .inner_size(1440.0, 900.0)
                .build()?;
            #[cfg(feature = "updater")]
            tauri::async_runtime::spawn(check_for_update(app.handle().clone()));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building OpenTerm desktop");

    app.run(|handle, event| {
        if let tauri::RunEvent::Exit = event {
            // Stop the backend with the window. (On Windows this ends the sidecar's launcher; the real process notices
            // that this one is gone within a couple of seconds and shuts down by itself, see OPENTERM_PARENT_PID.)
            if let Some(child) = handle.state::<Backend>().0.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}
