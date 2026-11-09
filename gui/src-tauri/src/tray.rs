//! Native presentation only. Host actions are routed to the existing GUI owner.
use crate::web_link::safe_web_url;
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, sync::Mutex};
use tauri::{
    menu::{IsMenuItem, Menu, MenuItem, MenuItemKind, PredefinedMenuItem, Submenu},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    App, AppHandle, Emitter, Manager,
};

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TrayHost {
    id: String,
    label: String,
    service_label: String,
    enable: bool,
    reconnect: bool,
    start: bool,
    stop: bool,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TrayProjection {
    revision: u32,
    user_name: String,
    current_label: String,
    show_label: String,
    web_label: String,
    manage_label: String,
    quit_label: String,
    enable_label: String,
    info_label: String,
    reconnect_label: String,
    start_label: String,
    stop_label: String,
    web_url: Option<String>,
    hosts: Vec<TrayHost>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct HostAction {
    revision: u32,
    host_id: String,
    action: String,
}

struct TrayState {
    root: Menu<tauri::Wry>,
    user: MenuItem<tauri::Wry>,
    current: MenuItem<tauri::Wry>,
    show: MenuItem<tauri::Wry>,
    web: MenuItem<tauri::Wry>,
    quit: MenuItem<tauri::Wry>,
    host_section: Mutex<Vec<MenuItemKind<tauri::Wry>>>,
    actions: Mutex<HashMap<String, HostAction>>,
    web_url: Mutex<Option<String>>,
}

pub fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        // Some X11 window managers leave an iconified GTK window unmapped after
        // deiconify/present. Remap that existing window before restoring focus.
        #[cfg(target_os = "linux")]
        if window.is_minimized().unwrap_or(false) {
            let _ = window.hide();
        }
        let result = window
            .unminimize()
            .and_then(|()| window.show())
            .and_then(|()| window.set_focus());
        if let Err(error) = result {
            eprintln!("Unable to show main window from system tray: {error}");
        }
    }
}

fn open_web(app: &AppHandle) {
    let url = app.state::<TrayState>().web_url.lock().unwrap().clone();
    let Some(url) = url.filter(|value| safe_web_url(value)) else {
        return;
    };
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        #[cfg(target_os = "linux")]
        let result = std::process::Command::new("xdg-open").arg(&url).status();
        #[cfg(target_os = "macos")]
        let result = std::process::Command::new("open").arg(&url).status();
        #[cfg(target_os = "windows")]
        let result = std::process::Command::new("rundll32.exe")
            .args(["url.dll,FileProtocolHandler", &url])
            .status();
        if !result.is_ok_and(|status| status.success()) {
            show_main_window(&app);
            let _ = app.emit_to("main", "gui://tray-error", "open_web_failed");
        }
    });
}

fn apply(app: &AppHandle, projection: TrayProjection) -> tauri::Result<()> {
    let state = app.state::<TrayState>();
    state.user.set_text(projection.user_name)?;
    state.current.set_text(projection.current_label)?;
    state.show.set_text(projection.show_label)?;
    state.web.set_text(projection.web_label)?;
    state.quit.set_text(projection.quit_label)?;
    let web_url = projection.web_url.filter(|value| safe_web_url(value));
    state.web.set_enabled(web_url.is_some())?;
    *state.web_url.lock().unwrap() = web_url;
    // AppIndicator hosts can render submenus as inline accordions. Keep just
    // one expandable level: a section heading followed by individual Hosts.
    // Retain the root menu, and rebuild the section together with its footer
    // so Quit is always preceded by a separator, independent of Host count.
    let mut section =
        vec![MenuItem::new(app, projection.manage_label, false, None::<&str>)?.kind()];
    let mut actions = HashMap::new();
    for (index, host) in projection.hosts.iter().enumerate() {
        let submenu = Submenu::new(app, &host.label, true)?;
        submenu.append(&MenuItem::new(
            app,
            &host.service_label,
            false,
            None::<&str>,
        )?)?;
        for (action, label, enabled) in [
            ("enable", &projection.enable_label, host.enable),
            ("info", &projection.info_label, true),
            ("reconnect", &projection.reconnect_label, host.reconnect),
            ("start", &projection.start_label, host.start),
            ("stop", &projection.stop_label, host.stop),
        ] {
            // Show only the applicable start/stop action, or both disabled if unknown.
            if (action == "start" && host.stop) || (action == "stop" && host.start) {
                continue;
            }
            let id = format!("tray-host-{}-{index}-{action}", projection.revision);
            submenu.append(&MenuItem::with_id(app, &id, label, enabled, None::<&str>)?)?;
            if enabled {
                actions.insert(
                    id,
                    HostAction {
                        revision: projection.revision,
                        host_id: host.id.clone(),
                        action: action.into(),
                    },
                );
            }
        }
        section.push(submenu.kind());
    }
    section.push(PredefinedMenuItem::separator(app)?.kind());
    section.push(state.quit.kind());
    let mut previous = state.host_section.lock().unwrap();
    for item in previous.iter() {
        state.root.remove(item)?;
    }
    for item in &section {
        state.root.append(item)?;
    }
    *previous = section;
    *state.actions.lock().unwrap() = actions;
    Ok(())
}

pub async fn sync_tray(app: AppHandle, projection: TrayProjection) -> Result<(), String> {
    if projection.hosts.len() > 128 {
        return Err("too_many_hosts".into());
    }
    if app.try_state::<TrayState>().is_none() {
        return Ok(());
    }
    let (sender, receiver) = std::sync::mpsc::channel();
    let handle = app.clone();
    app.run_on_main_thread(move || {
        let _ = sender.send(apply(&handle, projection).map_err(|error| error.to_string()));
    })
    .map_err(|error| error.to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        receiver.recv().map_err(|error| error.to_string())?
    })
    .await
    .map_err(|error| error.to_string())?
}

pub fn setup(app: &App) -> tauri::Result<()> {
    let user = MenuItem::new(app, "loushang", false, None::<&str>)?;
    let current = MenuItem::new(
        app,
        "⚪ 未选择 Host / No Host selected",
        false,
        None::<&str>,
    )?;
    let show = MenuItem::with_id(
        app,
        "tray-show",
        "显示窗口 / Show window",
        true,
        None::<&str>,
    )?;
    let web = MenuItem::with_id(app, "tray-web", "打开 Web / Open Web", false, None::<&str>)?;
    let quit = MenuItem::with_id(app, "tray-quit", "退出 / Quit", true, None::<&str>)?;
    let hosts = MenuItem::new(app, "管理 Host / Manage Hosts", false, None::<&str>)?;
    let quit_separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(
        app,
        &[
            &user,
            &PredefinedMenuItem::separator(app)?,
            &show,
            &web,
            &PredefinedMenuItem::separator(app)?,
            &current,
            &hosts,
            &quit_separator,
            &quit,
        ],
    )?;
    let mut builder = TrayIconBuilder::with_id("main-tray")
        .tooltip("loushang")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "tray-show" => show_main_window(app),
            "tray-web" => open_web(app),
            "tray-quit" => app.exit(0),
            id => {
                let action = app
                    .state::<TrayState>()
                    .actions
                    .lock()
                    .unwrap()
                    .get(id)
                    .cloned();
                if let Some(action) = action {
                    if action.action == "info" || action.action == "stop" {
                        show_main_window(app);
                    }
                    let _ = app.emit_to("main", "gui://tray-host-action", action);
                }
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    app.manage(TrayState {
        root: menu,
        user,
        current,
        show,
        web,
        quit: quit.clone(),
        host_section: Mutex::new(vec![hosts.kind(), quit_separator.kind(), quit.kind()]),
        actions: Mutex::default(),
        web_url: Mutex::default(),
    });
    if let Some(window) = app.get_webview_window("main") {
        let handle = window.clone();
        window.on_window_event(move |event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                // If hiding fails, retain the normal close path rather than trap the user.
                if handle.hide().is_ok() {
                    api.prevent_close();
                }
            }
        });
    }
    Ok(())
}
