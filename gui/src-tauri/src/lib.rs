#[cfg(windows)]
#[allow(dead_code)]
mod app_client;
mod connection_lifecycle;
#[cfg(windows)]
mod live_bridge;
// Exit joins run on the blocking pool.
#[allow(dead_code)]
mod read_stop;
#[allow(dead_code)]
mod read_worker;

use connection_lifecycle::{ConnectionLifecycle, ExitAction};
use std::sync::Arc;
use tauri::Manager;

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
    let builder = tauri::Builder::default().manage(Arc::new(ConnectionLifecycle::default()));
    #[cfg(windows)]
    let builder = builder.manage(live_bridge::LiveLaunchState::from_process());
    #[cfg(all(windows, feature = "fixture-bridge"))]
    let builder = builder.invoke_handler(tauri::generate_handler![
        fixture_bridge_handshake,
        live_bridge::live_readonly_available,
        live_bridge::resync_live_readonly,
        live_bridge::start_live_readonly,
        live_bridge::stop_live_readonly
    ]);
    #[cfg(all(windows, not(feature = "fixture-bridge")))]
    let builder = builder.invoke_handler(tauri::generate_handler![
        live_bridge::live_readonly_available,
        live_bridge::resync_live_readonly,
        live_bridge::start_live_readonly,
        live_bridge::stop_live_readonly
    ]);
    #[cfg(all(not(windows), feature = "fixture-bridge"))]
    let builder = builder.invoke_handler(tauri::generate_handler![fixture_bridge_handshake]);
    builder
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
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
