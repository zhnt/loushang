// Compiled here and exercised by the native integration driver. No live invoke
// is registered yet; desktop shutdown must schedule blocking joins off the UI.
#[allow(dead_code)]
mod read_stop;
#[allow(dead_code)]
mod read_worker;

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
    #[cfg(feature = "fixture-bridge")]
    let builder = builder.invoke_handler(tauri::generate_handler![fixture_bridge_handshake]);
    builder
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
