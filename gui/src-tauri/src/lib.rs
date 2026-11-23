mod client_settings;
mod connection_directory;
mod connection_lifecycle;
mod live_bridge;
mod offline_account;
mod project_folder;
#[cfg(desktop)]
mod tray;
mod web_link;
mod windows;
// Exit joins run on the blocking pool.
#[allow(dead_code)]
mod read_worker;

use connection_lifecycle::{ConnectionLifecycle, ExitAction};
use std::sync::Arc;
use tauri::Manager;

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
fn open_devtools(window: tauri::WebviewWindow) {
    window.open_devtools();
}

#[tauri::command]
fn show_tray_window(app: tauri::AppHandle) {
    windows::show_main_window(&app);
}

#[tauri::command]
async fn sync_tray(
    window: tauri::WebviewWindow,
    projection: serde_json::Value,
) -> Result<(), String> {
    #[cfg(desktop)]
    {
        if window.label() != windows::MAIN {
            return Ok(());
        }
        let projection = serde_json::from_value(projection).map_err(|error| error.to_string())?;
        tray::sync_tray(window.app_handle().clone(), projection).await
    }
    #[cfg(not(desktop))]
    {
        let _ = (window, projection);
        Ok(())
    }
}

#[cfg(feature = "fixture-bridge")]
use serde::Serialize;
#[cfg(feature = "fixture-bridge")]
use tauri::Emitter;

#[cfg(feature = "fixture-bridge")]
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct FixtureBridgeReceipt {
    bridge_version: &'static str,
    transport: &'static str,
    generation: &'static str,
}

#[cfg(feature = "fixture-bridge")]
#[tauri::command]
fn fixture_bridge_handshake(app: tauri::AppHandle) -> Result<FixtureBridgeReceipt, String> {
    let receipt = FixtureBridgeReceipt {
        bridge_version: "gui-b1-fixture/v1",
        transport: "tauri-invoke-event",
        generation: "9007199254740993",
    };
    app.emit("gui://fixture-bridge", receipt.clone())
        .map_err(|error| error.to_string())?;
    Ok(receipt)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default();
    #[cfg(desktop)]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _, _| {
        let handle = app.clone();
        let _ = app.run_on_main_thread(move || windows::activate(&handle));
    }));
    let builder = builder
        .manage(windows::DesktopWindows::default())
        .on_window_event(windows::on_window_event)
        .plugin(tauri_plugin_os::init())
        .manage(Arc::new(ConnectionLifecycle::default()))
        .manage(client_settings::AttachmentFiles::default());
    let builder = builder.manage(live_bridge::LiveLaunchState::from_process());
    #[cfg(feature = "fixture-bridge")]
    let builder = builder.invoke_handler(tauri::generate_handler![
        sync_tray,
        windows::new_window,
        web_link::open_web_link,
        quit_app,
        open_devtools,
        show_tray_window,
        project_folder::pick_project_folder,
        client_settings::pick_client_directory,
        client_settings::open_text_attachment,
        fixture_bridge_handshake,
        client_settings::client_settings,
        offline_account::offline_account,
        live_bridge::live_connection_available,
        live_bridge::live_submit_text,
        live_bridge::live_find_submission,
        live_bridge::live_session_resource,
        live_bridge::live_interrupt,
        live_bridge::live_respond_interaction,
        live_bridge::live_create_session,
        live_bridge::live_session_models,
        live_bridge::live_goal_progress,
        live_bridge::live_interactive_goal_command,
        live_bridge::live_interactive_goal_recovery,
        live_bridge::live_interactive_goal_review,
        live_bridge::live_interactive_goal_review_submit,
        live_bridge::live_interactive_goal_create,
        live_bridge::live_interactive_goal_status,
        live_bridge::live_goal_start,
        live_bridge::live_select_model,
        live_bridge::resync_live_connection,
        live_bridge::start_live_connection,
        live_bridge::stop_live_connection
    ]);
    #[cfg(not(feature = "fixture-bridge"))]
    let builder = builder.invoke_handler(tauri::generate_handler![
        sync_tray,
        windows::new_window,
        web_link::open_web_link,
        quit_app,
        open_devtools,
        show_tray_window,
        project_folder::pick_project_folder,
        client_settings::pick_client_directory,
        client_settings::open_text_attachment,
        client_settings::client_settings,
        offline_account::offline_account,
        live_bridge::live_connection_available,
        live_bridge::live_submit_text,
        live_bridge::live_find_submission,
        live_bridge::live_session_resource,
        live_bridge::live_interrupt,
        live_bridge::live_respond_interaction,
        live_bridge::live_create_session,
        live_bridge::live_session_models,
        live_bridge::live_goal_progress,
        live_bridge::live_interactive_goal_command,
        live_bridge::live_interactive_goal_recovery,
        live_bridge::live_interactive_goal_review,
        live_bridge::live_interactive_goal_review_submit,
        live_bridge::live_interactive_goal_create,
        live_bridge::live_interactive_goal_status,
        live_bridge::live_goal_start,
        live_bridge::live_select_model,
        live_bridge::resync_live_connection,
        live_bridge::start_live_connection,
        live_bridge::stop_live_connection
    ]);
    builder
        .setup(|app| {
            if let Some(window) = app.get_webview_window(windows::MAIN) {
                window.set_title(&app.package_info().name)?;
            }
            #[cfg(desktop)]
            if let Err(error) = tray::setup(app) {
                // A desktop without a tray host must still be able to launch.
                eprintln!("Unable to create system tray: {error}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            #[cfg(target_os = "macos")]
            if matches!(event, tauri::RunEvent::Reopen { .. }) {
                windows::activate(app);
            }
            if let tauri::RunEvent::ExitRequested { api, code, .. } = event {
                let owner = app.state::<Arc<ConnectionLifecycle>>().inner().clone();
                match owner.begin_exit() {
                    ExitAction::Ready => (),
                    ExitAction::Pending => api.prevent_exit(),
                    ExitAction::Join(worker) => {
                        api.prevent_exit();
                        let app = app.clone();
                        tauri::async_runtime::spawn_blocking(move || {
                            owner.finish_exit(worker.wait());
                            let failed = owner.cleanup_failed();
                            if failed {
                                eprintln!("GUI connection cleanup failed; ownership release is unconfirmed");
                            }
                            app.exit(if failed { 1 } else { code.unwrap_or(0) });
                        });
                    }
                }
            }
        });
}
