use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use tauri::{Manager, WindowEvent};

// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

fn find_backend_dir() -> Option<PathBuf> {
    let current_dir = std::env::current_dir().ok()?;
    let candidates = [current_dir.join("backend"), current_dir.join("../backend")];

    candidates
        .into_iter()
        .find(|path| path.join("main.py").is_file())
}

fn python_path(backend_dir: &Path) -> PathBuf {
    backend_dir.join("venv/bin/python")
}

fn start_backend() {
    if TcpStream::connect("127.0.0.1:8000").is_ok() {
        return;
    }

    let Some(backend_dir) = find_backend_dir() else {
        eprintln!("Vexa backend directory was not found.");
        return;
    };

    let python = python_path(&backend_dir);

    if !python.is_file() {
        eprintln!(
            "Vexa backend Python executable was not found at {:?}.",
            python
        );
        return;
    }

    if let Err(error) = Command::new(python)
        .args([
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ])
        .current_dir(backend_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        eprintln!("Failed to start Vexa backend: {error}");
    }
}

#[tauri::command]
fn toggle_main_window(app: tauri::AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "Main window was not found.".to_string())?;

    if window.is_visible().map_err(|error| error.to_string())? {
        window.hide().map_err(|error| error.to_string())?;
        return Ok(());
    }

    window.show().map_err(|error| error.to_string())?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            start_backend();

            if let Some(window) = app.get_webview_window("main") {
                let main_window = window.clone();

                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();

                        if let Err(error) = main_window.hide() {
                            eprintln!("Failed to hide Vexa main window: {error}");
                        }
                    }
                });
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![greet, toggle_main_window])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
