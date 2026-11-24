use std::sync::{
    atomic::{AtomicU64, Ordering},
    Mutex,
};
use tauri::{AppHandle, Manager, WebviewWindowBuilder, Window, WindowEvent};

pub(crate) const MAIN: &str = "main";
const SECONDARY_PREFIX: &str = "workspace-";

#[derive(Default)]
pub(crate) struct DesktopWindows {
    next: AtomicU64,
    focus_history: Mutex<Vec<String>>,
}

#[tauri::command]
pub(crate) async fn new_window(app: AppHandle) -> Result<(), String> {
    let windows = app.state::<DesktopWindows>();
    let id = windows.next.fetch_add(1, Ordering::Relaxed);
    let mut config = app
        .config()
        .app
        .windows
        .iter()
        .find(|config| config.label == MAIN)
        .cloned()
        .ok_or("main window configuration is unavailable")?;
    config.label = format!("{SECONDARY_PREFIX}{id}");
    config.title = app.package_info().name.clone();
    WebviewWindowBuilder::from_config(&app, &config)
        .and_then(|builder| builder.build())
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub(crate) fn on_window_event(window: &Window, event: &WindowEvent) {
    let label = window.label();
    if label != MAIN && !label.starts_with(SECONDARY_PREFIX) {
        return;
    }
    if matches!(event, WindowEvent::Focused(true) | WindowEvent::Destroyed) {
        let windows = window.state::<DesktopWindows>();
        let mut history = windows.focus_history.lock().unwrap();
        history.retain(|previous| previous != label);
        if matches!(event, WindowEvent::Focused(true)) {
            history.push(label.to_owned());
        }
    }
}

pub(crate) fn activate(app: &AppHandle) {
    let windows = app.state::<DesktopWindows>();
    let history = windows.focus_history.lock().unwrap().clone();
    let window = history
        .iter()
        .rev()
        .find_map(|label| app.get_webview_window(label))
        .or_else(|| app.get_webview_window(MAIN));
    if let Some(window) = window {
        reveal(&window);
    }
}

pub(crate) fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN) {
        reveal(&window);
    }
}

fn reveal(window: &tauri::WebviewWindow) {
    // On X11, remap an iconified window before asking the window manager to focus it.
    #[cfg(target_os = "linux")]
    if window.is_minimized().unwrap_or(false) {
        let _ = window.hide();
    }
    let result = window
        .unminimize()
        .and_then(|()| window.show())
        .and_then(|()| window.set_focus());
    if let Err(error) = result {
        eprintln!("Unable to activate desktop window: {error}");
    }
}
