//! Native composition only: invoke the installed Product's managed entrypoint.
//! No service spawning policy, credentials or Runtime are implemented here.
use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;

#[derive(Default)]
pub(crate) struct LocalHostState {
    operation: Mutex<()>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LocalHostRequest {
    action: String,
    workspace: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    instance_id: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LocalHostStatus {
    version: String,
    supported: bool,
    state: String,
    error_code: Option<String>,
    workspace: Option<String>,
    service_id: Option<String>,
    instance_id: Option<String>,
    service_instance_id: Option<String>,
    pid: Option<u32>,
    cleanly_stopped: Option<bool>,
    mux_name: Option<String>,
    #[serde(skip_serializing)]
    record_root: Option<PathBuf>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LocalHostEnvironment {
    supported: bool,
    workspace: String,
}

#[tauri::command]
pub(crate) fn local_host_environment() -> LocalHostEnvironment {
    LocalHostEnvironment {
        supported: cfg!(target_os = "linux"),
        workspace: std::env::current_dir()
            .ok()
            .and_then(|value| value.into_os_string().into_string().ok())
            .unwrap_or_default(),
    }
}

fn run(request: &LocalHostRequest) -> Result<LocalHostStatus, String> {
    if !cfg!(target_os = "linux") {
        return Err("platform_unsupported".into());
    }
    if !matches!(
        request.action.as_str(),
        "status" | "start" | "connect" | "stop" | "restart"
    ) || request.workspace.len() > 4096
        || !PathBuf::from(&request.workspace).is_absolute()
    {
        return Err("invalid_request".into());
    }
    let python = std::env::var_os("LOUSHANG_GUI_PYTHON").unwrap_or_else(|| "python3".into());
    let mut child = Command::new(python)
        .args(["-m", "loushang.coding.gui_local_host"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "management_unavailable".to_owned())?;
    // Dropping GUI ownership does not signal this helper or the managed Host.
    let sent = (|| {
        let mut input = child.stdin.take().ok_or(())?;
        let payload = serde_json::to_vec(request).map_err(|_| ())?;
        input.write_all(&payload).map_err(|_| ())
    })();
    let mut output = Vec::new();
    let read = child
        .stdout
        .take()
        .ok_or(())
        .and_then(|stream| stream.take(65_537).read_to_end(&mut output).map_err(|_| ()));
    let exited = child
        .wait()
        .map_err(|_| "management_unconfirmed".to_owned())?;
    if sent.is_err() || read.is_err() || !exited.success() || output.len() > 65_536 {
        return Err("management_unconfirmed".into());
    }
    let result: LocalHostStatus =
        serde_json::from_slice(&output).map_err(|_| "management_response_invalid".to_owned())?;
    if result.version != "gui-local-host/v1"
        || !matches!(
            result.state.as_str(),
            "unknown" | "not_running" | "starting" | "running" | "stopping" | "exited"
        )
    {
        return Err("management_response_invalid".into());
    }
    Ok(result)
}

#[tauri::command]
pub(crate) async fn local_host_action(
    app: tauri::AppHandle,
    request: LocalHostRequest,
) -> Result<LocalHostStatus, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<LocalHostState>();
        let _operation = if request.action == "status" {
            None
        } else {
            Some(
                state
                    .operation
                    .try_lock()
                    .map_err(|_| "management_busy".to_owned())?,
            )
        };
        let connecting = matches!(request.action.as_str(), "start" | "connect" | "restart");
        let result = run(&request)?;
        if connecting && result.state == "running" && result.error_code.is_none() {
            let root = result
                .record_root
                .clone()
                .ok_or("management_response_invalid")?;
            let mux = result
                .mux_name
                .clone()
                .ok_or("management_response_invalid")?;
            crate::live_bridge::configure_local_connection(&app, root, mux)?;
        }
        Ok(result)
    })
    .await
    .map_err(|_| "management_unconfirmed".to_owned())?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn record_path_is_native_only() {
        let value = serde_json::json!({"version":"gui-local-host/v1", "supported":true,
            "state":"running", "recordRoot":"/private/record", "muxName":"main"});
        let status: LocalHostStatus = serde_json::from_value(value).unwrap();
        assert_eq!(status.record_root, Some(PathBuf::from("/private/record")));
        assert!(serde_json::to_value(status)
            .unwrap()
            .get("recordRoot")
            .is_none());
    }

    #[test]
    fn action_is_not_an_arbitrary_command() {
        let request = LocalHostRequest {
            action: "shell".into(),
            workspace: "/tmp".into(),
            instance_id: None,
        };
        assert!(run(&request).is_err());
    }
}

/// Shared client configuration and Host navigation state, owned by Python.
#[tauri::command]
pub(crate) async fn client_settings(
    request: serde_json::Value,
) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let python = std::env::var_os("LOUSHANG_GUI_PYTHON").unwrap_or_else(|| "python3".into());
        let mut child = Command::new(python)
            .args(["-m", "loushang.coding.client_settings"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "settings_unavailable".to_owned())?;
        let payload = serde_json::to_vec(&request).map_err(|_| "invalid_request".to_owned())?;
        let sent = child
            .stdin
            .take()
            .ok_or_else(|| "settings_unavailable".to_owned())?
            .write_all(&payload);
        let output = child
            .wait_with_output()
            .map_err(|_| "settings_unavailable".to_owned())?;
        if sent.is_err() || !output.status.success() || output.stdout.len() > 16777216 {
            return Err("settings_unavailable".to_owned());
        }
        let value: serde_json::Value = serde_json::from_slice(&output.stdout)
            .map_err(|_| "settings_unavailable".to_owned())?;
        value
            .get("result")
            .cloned()
            .ok_or_else(|| "settings_unavailable".to_owned())
    })
    .await
    .map_err(|_| "settings_unavailable".to_owned())?
}
