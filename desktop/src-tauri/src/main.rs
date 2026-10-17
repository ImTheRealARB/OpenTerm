// OpenTerm desktop shell (scaffold, not compiled on the machine that wrote it; see docs/DESKTOP.md).
//
// Starts the OpenTerm backend as a child process, waits until its port answers, opens one window on
// http://127.0.0.1:<port>, and stops the backend when the window closes. The backend serves the built
// frontend itself (OPENTERM_STATIC_DIR), so the window is a plain webview and needs no IPC.
//
// Environment (all optional):
//   OPENTERM_PORT           backend port, default 8765 (not 8000, so it can run next to `scripts/dev.ps1`)
//   OPENTERM_BACKEND_CMD    full command that starts the backend, default `uv run python -m openterm`
//   OPENTERM_BACKEND_DIR    working directory for that command, default <repo>/backend
//   OPENTERM_STATIC_DIR     built frontend, default <repo>/frontend/dist
//   OPENTERM_ATTACH=1       do not spawn a backend; open a window on one that is already running
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

struct Backend(Mutex<Option<Child>>);

fn repo_root() -> PathBuf {
    // desktop/src-tauri -> repo root (two levels up from CARGO_MANIFEST_DIR at build time).
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from("."))
}

fn spawn_backend(port: u16) -> std::io::Result<Child> {
    let root = repo_root();
    let dir = std::env::var("OPENTERM_BACKEND_DIR").map(PathBuf::from).unwrap_or_else(|_| root.join("backend"));
    let static_dir = std::env::var("OPENTERM_STATIC_DIR")
        .unwrap_or_else(|_| root.join("frontend").join("dist").to_string_lossy().into_owned());
    let cmd = std::env::var("OPENTERM_BACKEND_CMD").unwrap_or_else(|_| "uv run python -m openterm".to_string());
    let mut parts = cmd.split_whitespace();
    let program = parts.next().expect("OPENTERM_BACKEND_CMD is empty");
    Command::new(program)
        .args(parts)
        .current_dir(dir)
        .env("OPENTERM_HOST", "127.0.0.1")
        .env("OPENTERM_PORT", port.to_string())
        .env("OPENTERM_STATIC_DIR", static_dir)
        .stdin(Stdio::null())
        .spawn()
}

fn wait_for_port(port: u16, timeout: Duration) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let start = Instant::now();
    while start.elapsed() < timeout {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    false
}

fn main() {
    let port: u16 = std::env::var("OPENTERM_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(8765);
    let attach = std::env::var("OPENTERM_ATTACH").map(|v| v == "1").unwrap_or(false);

    let app = tauri::Builder::default()
        .manage(Backend(Mutex::new(None)))
        .setup(move |app| {
            if !attach {
                let child = spawn_backend(port).map_err(|e| format!("cannot start the backend: {e}"))?;
                *app.state::<Backend>().0.lock().unwrap() = Some(child);
            }
            if !wait_for_port(port, Duration::from_secs(30)) {
                return Err(format!("the backend did not open port {port} within 30 s").into());
            }
            let url = format!("http://127.0.0.1:{port}");
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.parse().unwrap()))
                .title("OpenTerm")
                .inner_size(1440.0, 900.0)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building OpenTerm desktop");

    app.run(|handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(mut child) = handle.state::<Backend>().0.lock().unwrap().take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
