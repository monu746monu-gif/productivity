use std::net::TcpStream;
use tauri::{
    image::Image,
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, PhysicalPosition, Rect, WindowEvent,
};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;

// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

fn start_local_backend_fallback() {
    let Some(backend_dir) = std::env::current_dir()
        .ok()
        .and_then(|current_dir| {
            [current_dir.join("backend"), current_dir.join("../backend")]
                .into_iter()
                .find(|path| path.join("main.py").is_file())
        }) else {
        eprintln!("Vexa backend directory was not found.");
        return;
    };

    let python = backend_dir.join("venv/bin/python");

    if !python.is_file() {
        eprintln!(
            "Vexa backend Python executable was not found at {:?}.",
            python
        );
        return;
    }

    if let Err(error) = std::process::Command::new(python)
        .arg("sidecar_main.py")
        .current_dir(backend_dir)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
    {
        eprintln!("Failed to start Vexa backend fallback: {error}");
    }
}

fn start_bundled_backend_fallback() -> bool {
    let Some(sidecar_path) = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(|parent| parent.join("vexa-backend")))
    else {
        return false;
    };

    if !sidecar_path.is_file() {
        return false;
    }

    match std::process::Command::new(sidecar_path)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
    {
        Ok(_) => true,
        Err(error) => {
            eprintln!("Failed to start bundled Vexa backend fallback: {error}");
            false
        }
    }
}

fn start_backend(app: &tauri::AppHandle) {
    if TcpStream::connect("127.0.0.1:8000").is_ok() {
        return;
    }

    match app.shell().sidecar("binaries/vexa-backend") {
        Ok(command) => match command.spawn() {
            Ok((mut rx, _child)) => {
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(line) => {
                                eprintln!(
                                    "Vexa sidecar stdout: {}",
                                    String::from_utf8_lossy(&line)
                                );
                            }
                            CommandEvent::Stderr(line) => {
                                eprintln!(
                                    "Vexa sidecar stderr: {}",
                                    String::from_utf8_lossy(&line)
                                );
                            }
                            CommandEvent::Error(error) => {
                                eprintln!("Vexa sidecar error: {error}");
                            }
                            CommandEvent::Terminated(payload) => {
                                eprintln!(
                                    "Vexa sidecar terminated with code {:?} and signal {:?}",
                                    payload.code, payload.signal
                                );
                            }
                            _ => {}
                        }
                    }
                });
            }
            Err(error) => {
                eprintln!("Failed to spawn Vexa sidecar backend: {error}");
                if !start_bundled_backend_fallback() {
                    start_local_backend_fallback();
                }
            }
        },
        Err(error) => {
            eprintln!("Failed to prepare Vexa sidecar backend: {error}");
            if !start_bundled_backend_fallback() {
                start_local_backend_fallback();
            }
        }
    }
}

#[tauri::command]
fn toggle_main_window(app: tauri::AppHandle) -> Result<(), String> {
    toggle_main_window_for(&app)
}

#[tauri::command]
fn toggle_main_window_and_listen(app: tauri::AppHandle) -> Result<(), String> {
    let is_visible = show_or_hide_main_window(&app, None)?;

    if !is_visible {
        app.emit_to("main", "vexa-start-listening", ())
            .map_err(|error| error.to_string())?;
    }

    Ok(())
}

fn toggle_main_window_for(app: &tauri::AppHandle) -> Result<(), String> {
    show_or_hide_main_window(app, None)?;
    Ok(())
}

fn toggle_main_window_from_menu_bar(
    app: &tauri::AppHandle,
    position: PhysicalPosition<f64>,
    rect: Rect,
) -> Result<(), String> {
    let was_visible = show_or_hide_main_window(app, Some((position, rect)))?;

    if !was_visible {
        app.emit_to("main", "vexa-start-listening", ())
            .map_err(|error| error.to_string())?;
    }

    Ok(())
}

fn menu_bar_v_icon() -> Image<'static> {
    let width = 18;
    let height = 18;
    let mut rgba = vec![0; width * height * 4];

    for y in 3..15 {
        let left_x = 4 + (y - 3) / 3;
        let right_x = 13 - (y - 3) / 3;

        for x in [left_x, left_x + 1, right_x, right_x + 1] {
            let offset = (y * width + x) * 4;
            rgba[offset] = 255;
            rgba[offset + 1] = 255;
            rgba[offset + 2] = 255;
            rgba[offset + 3] = 255;
        }
    }

    Image::new_owned(rgba, width as u32, height as u32)
}

fn position_main_window_under_menu_bar_icon(
    app: &tauri::AppHandle,
    window: &tauri::WebviewWindow,
    position: PhysicalPosition<f64>,
    rect: Rect,
) -> Result<(), String> {
    let window_size = window.outer_size().map_err(|error| error.to_string())?;
    let monitor = app
        .monitor_from_point(position.x, position.y)
        .map_err(|error| error.to_string())?
        .or_else(|| app.primary_monitor().ok().flatten());

    let Some(monitor) = monitor else {
        return Ok(());
    };

    let scale_factor = monitor.scale_factor();
    let icon_position = rect.position.to_physical::<f64>(scale_factor);
    let icon_size = rect.size.to_physical::<f64>(scale_factor);
    let icon_center_x = icon_position.x + icon_size.width / 2.0;
    let work_area = monitor.work_area();
    let min_x = f64::from(work_area.position.x) + 8.0;
    let min_y = f64::from(work_area.position.y) + 8.0;
    let max_x = f64::from(work_area.position.x + work_area.size.width as i32)
        - f64::from(window_size.width)
        - 8.0;
    let max_y = f64::from(work_area.position.y + work_area.size.height as i32)
        - f64::from(window_size.height)
        - 8.0;

    let x = (icon_center_x - f64::from(window_size.width) / 2.0).clamp(min_x, max_x);
    let below_icon_y = icon_position.y + icon_size.height + 8.0;
    let above_icon_y = icon_position.y - f64::from(window_size.height) - 8.0;
    let y = if below_icon_y <= max_y {
        below_icon_y
    } else {
        above_icon_y.clamp(min_y, max_y)
    };

    window
        .set_position(PhysicalPosition::new(x.round() as i32, y.round() as i32))
        .map_err(|error| error.to_string())
}

fn show_or_hide_main_window(
    app: &tauri::AppHandle,
    anchor_rect: Option<(PhysicalPosition<f64>, Rect)>,
) -> Result<bool, String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "Main window was not found.".to_string())?;

    let is_visible = window.is_visible().map_err(|error| error.to_string())?;

    if is_visible {
        app.emit_to("main", "vexa-stop-listening", ())
            .map_err(|error| error.to_string())?;
        window.hide().map_err(|error| error.to_string())?;
        return Ok(true);
    }

    if let Some((position, rect)) = anchor_rect {
        position_main_window_under_menu_bar_icon(app, &window, position, rect)?;
    }

    window.show().map_err(|error| error.to_string())?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;

    Ok(false)
}

fn create_menu_bar_icon(app: &tauri::AppHandle) -> tauri::Result<()> {
    TrayIconBuilder::with_id("vexa-menu-bar")
        .icon(menu_bar_v_icon())
        .icon_as_template(true)
        .title("V")
        .tooltip("Vexa")
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                position,
                rect,
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                if let Err(error) =
                    toggle_main_window_from_menu_bar(tray.app_handle(), position, rect)
                {
                    eprintln!("Failed to toggle Vexa from menu bar icon: {error}");
                }
            }
        })
        .build(app)?;

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            start_backend(app.handle());
            create_menu_bar_icon(app.handle())?;

            if let Some(window) = app.get_webview_window("main") {
                let main_window = window.clone();

                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();

                        if let Err(error) = main_window.hide() {
                            eprintln!("Failed to hide Vexa main window: {error}");
                        }

                        if let Err(error) = main_window.emit("vexa-stop-listening", ()) {
                            eprintln!("Failed to stop Vexa listening loop: {error}");
                        }
                    }
                });
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            greet,
            toggle_main_window,
            toggle_main_window_and_listen
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
