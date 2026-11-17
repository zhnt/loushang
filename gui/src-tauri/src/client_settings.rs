//! Desktop connection selection and transport. AppHost owns management and sessions.
use crate::connection_directory::Directory;
use loushang_app_client::frontend::Backend;
use serde::Deserialize;
use serde_json::{json, Value};
use std::num::NonZeroU16;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use tauri::{AppHandle, Manager};

const SETTINGS_ERROR: &str = "settings_unavailable";
type Result<T> = std::result::Result<T, &'static str>;

#[derive(Deserialize)]
#[serde(tag = "operation", deny_unknown_fields)]
pub(crate) enum Request {
    #[serde(rename = "connections/list")]
    List,
    #[serde(rename = "connections/select")]
    Select {
        #[serde(rename = "connectionId")]
        id: String,
    },
    #[serde(rename = "host/request")]
    ToHost {
        #[serde(rename = "connectionId")]
        id: String,
        request: Value,
    },
    #[serde(rename = "remote-call")]
    ToSelected { request: Value },
    #[serde(rename = "environment")]
    Environment,
}

enum Routed {
    Settings(Value),
    AppServer {
        root: PathBuf,
        id: String,
        tunnel: Option<NonZeroU16>,
        body: Value,
        environment: bool,
    },
}

fn route(root: &Path, request: Request) -> Result<Routed> {
    match request {
        Request::List => {
            Directory::read(root).map(|directory| Routed::Settings(directory.listing()))
        }
        Request::Select { id } => Directory::select(root, &id).map(Routed::Settings),
        Request::ToHost { id, request } => Directory::read(root)
            .and_then(|directory| forward(root, &directory, &id, request, false)),
        Request::ToSelected { request } => {
            let directory = Directory::read(root)?;
            forward(root, &directory, directory.selected(), request, false)
        }
        Request::Environment => {
            let directory = Directory::read(root)?;
            forward(
                root,
                &directory,
                directory.selected(),
                json!({ "operation": "environment" }),
                true,
            )
        }
    }
}

fn forward(
    root: &Path,
    directory: &Directory,
    id: &str,
    body: Value,
    environment: bool,
) -> Result<Routed> {
    Ok(Routed::AppServer {
        root: root.to_path_buf(),
        id: id.to_owned(),
        tunnel: directory.tunnel_port(id)?,
        body,
        environment,
    })
}

fn application_root(app: &AppHandle) -> Result<PathBuf> {
    let home = || app.path().home_dir().map_err(|_| SETTINGS_ERROR);
    let Some(path) = std::env::var_os("LOUSHANG_HOME").filter(|value| !value.is_empty()) else {
        return Ok(home()?.join(".loushang"));
    };
    let path = PathBuf::from(path);
    if let Ok(suffix) = path.strip_prefix("~") {
        return Ok(home()?.join(suffix));
    }
    std::path::absolute(path).map_err(|_| SETTINGS_ERROR)
}

fn workspace_error(creating: bool, code: &str) -> &'static str {
    if !creating {
        return "connection_failed";
    }
    match code {
        "invalid_request" => "invalid_request",
        "not_found" => "not_found",
        "already_exists" => "already_exists",
        "permission_denied" => "permission_denied",
        "workspace_registration_failed" => "workspace_registration_failed",
        "operation_unavailable" => "operation_unavailable",
        _ => "connection_failed",
    }
}

async fn dispatch(routed: Routed) -> Result<Value> {
    match routed {
        Routed::Settings(value) => Ok(value),
        Routed::AppServer {
            root,
            id,
            tunnel,
            body,
            environment,
        } => {
            static BACKEND: OnceLock<Backend> = OnceLock::new();
            let backend =
                BACKEND.get_or_init(|| Backend::new(root.clone()).with_service_management());
            let backend = if let Some(port) = tunnel {
                backend.through_tunnel(root.join("app-tunnels").join(&id), port)
            } else {
                backend.clone()
            };
            let creating_workspace = body["operation"] == "workspace" && body["action"] == "create";
            if body["operation"] == "open-project-path" {
                if tunnel.is_some() || id != "local" {
                    return Err("operation_unavailable");
                }
                return tauri::async_runtime::spawn_blocking(move || {
                    open_project_path(&backend, &body)
                })
                .await
                .map_err(|_| SETTINGS_ERROR)?;
            }
            let mut value = tauri::async_runtime::spawn_blocking(move || backend.call(body))
                .await
                .map_err(|_| SETTINGS_ERROR)?
                .map_err(|code| workspace_error(creating_workspace, &code))?;
            if environment {
                value
                    .as_object_mut()
                    .ok_or(SETTINGS_ERROR)?
                    .insert("connectionId".into(), json!(id));
            }
            Ok(value)
        }
    }
}

fn open_project_path(backend: &Backend, body: &Value) -> Result<Value> {
    let workspace = body["workspace"].as_str().ok_or("invalid_request")?;
    let fingerprint = body["fingerprint"].as_str().ok_or("invalid_request")?;
    let projects = backend
        .call(json!({"operation":"workspace","action":"projects"}))
        .map_err(|_| "connection_failed")?;
    let admitted = projects["workspaces"].as_array().is_some_and(|rows| {
        rows.iter().any(|row| {
            row["path"] == workspace
                && row["scope"] == "cwd"
                && row["scopeFingerprint"] == fingerprint
        })
    });
    if !admitted {
        return Err("workspace_unavailable");
    }
    let relative = match body.get("file") {
        Some(Value::String(file)) => Some(file.as_str()),
        None => None,
        _ => return Err("invalid_request"),
    };
    let path = resolve_project_path(Path::new(workspace), relative)?;
    open_in_desktop(&path)?;
    Ok(json!({}))
}

fn resolve_project_path(workspace: &Path, relative: Option<&str>) -> Result<PathBuf> {
    let root = workspace.canonicalize().map_err(|_| "not_found")?;
    if !root.is_dir() {
        return Err("not_found");
    }
    if let Some(relative) = relative {
        use std::path::Component;
        let relative = Path::new(relative);
        if !relative
            .components()
            .all(|part| matches!(part, Component::Normal(_)))
        {
            return Err("invalid_request");
        }
        let file = root
            .join(relative)
            .canonicalize()
            .map_err(|_| "not_found")?;
        let supported = file
            .extension()
            .and_then(|value| value.to_str())
            .is_some_and(|value| {
                [
                    "html", "htm", "pdf", "png", "jpg", "jpeg", "webp", "txt", "md",
                ]
                .iter()
                .any(|extension| value.eq_ignore_ascii_case(extension))
            });
        if !file.starts_with(&root) || !file.is_file() || !supported {
            return Err("operation_unavailable");
        }
        Ok(file)
    } else {
        Ok(root)
    }
}

#[cfg(target_os = "windows")]
fn open_in_desktop(path: &Path) -> Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::{w, PCWSTR};
    use windows::Win32::UI::Shell::ShellExecuteW;

    let mut path: Vec<u16> = path.as_os_str().encode_wide().collect();
    let verbatim_prefix = [b'\\' as u16, b'\\' as u16, b'?' as u16, b'\\' as u16];
    // ShellExecute expects the usual drive-path spelling for shell associations.
    if path.starts_with(&verbatim_prefix) && path.get(5) == Some(&(b':' as u16)) {
        path.drain(..verbatim_prefix.len());
    }
    path.push(0);
    let result = unsafe {
        ShellExecuteW(
            None,
            w!("open"),
            PCWSTR(path.as_ptr()),
            PCWSTR::null(),
            PCWSTR::null(),
            windows::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL,
        )
    };
    if result.0 as isize <= 32 {
        Err("open_failed")
    } else {
        Ok(())
    }
}

#[cfg(target_os = "linux")]
fn open_in_desktop(path: &Path) -> Result<()> {
    use gtk::gio::{self, prelude::FileExt};

    let uri = gio::File::for_path(path).uri();
    gio::AppInfo::launch_default_for_uri(&uri, None::<&gio::AppLaunchContext>)
        .map_err(|_| "open_failed")
}

#[cfg(not(any(target_os = "linux", target_os = "windows")))]
fn open_in_desktop(path: &Path) -> Result<()> {
    let status = std::process::Command::new("open").arg(path).status();
    if status.is_ok_and(|status| status.success()) {
        Ok(())
    } else {
        Err("open_failed")
    }
}

#[tauri::command]
pub(crate) async fn client_settings(app: AppHandle, request: Request) -> Result<Value> {
    let root = application_root(&app)?;
    let routed = tauri::async_runtime::spawn_blocking(move || route(&root, request))
        .await
        .map_err(|_| SETTINGS_ERROR)??;
    dispatch(routed).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_file_open_resolves_supported_files_and_rejects_traversal() {
        let root = tempfile::tempdir().unwrap();
        let project = root.path().join("workspace");
        std::fs::create_dir(&project).unwrap();
        let doc = project.join("index.html");
        std::fs::write(&doc, "<h1>Dashboard</h1>").unwrap();
        let outside = root.path().join("external.html");
        std::fs::write(&outside, "<h1>Outside</h1>").unwrap();

        assert_eq!(
            resolve_project_path(&project, Some("index.html")).unwrap(),
            doc.canonicalize().unwrap()
        );
        assert_eq!(
            resolve_project_path(&project, Some("../external.html")),
            Err("invalid_request")
        );
        assert_eq!(
            resolve_project_path(&project, Some("missing.html")),
            Err("not_found")
        );
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink(outside, project.join("link.html")).unwrap();
            assert_eq!(
                resolve_project_path(&project, Some("link.html")),
                Err("operation_unavailable")
            );
        }
    }

    #[test]
    fn local_environment_does_not_start_a_web_listener() {
        let home = tempfile::tempdir().unwrap();
        let routed = route(home.path(), Request::Environment).unwrap();
        let result = tauri::async_runtime::block_on(dispatch(routed)).unwrap();
        assert_eq!(result["connectionId"], "local");
        assert_eq!(result["manageable"], false);
        assert!(!home.path().join("state/web").exists());
    }

    #[test]
    fn selected_tunnel_has_separate_preferences_and_no_web_dependency() {
        let home = tempfile::tempdir().unwrap();
        let root = home.path();
        let config = json!({ "version": 1, "defaultConnection": "office",
            "servers": [{ "id": "office", "tunnelPort": 24420 }] });
        std::fs::write(root.join("connections.json"), config.to_string()).unwrap();

        let routed = route(
            root,
            Request::ToSelected {
                request: json!({"operation":"remember-workspace", "workspace":"/remote"}),
            },
        )
        .unwrap();
        tauri::async_runtime::block_on(dispatch(routed)).unwrap();
        let routed = route(root, Request::Environment).unwrap();
        let result = tauri::async_runtime::block_on(dispatch(routed)).unwrap();
        assert_eq!(
            result,
            json!({"workspace":"/remote", "connectionId":"office",
                                  "supported":true, "manageable":false})
        );
        let routed = route(
            root,
            Request::ToSelected {
                request: json!({"operation":"manage", "action":"connect"}),
            },
        )
        .unwrap();
        let result = tauri::async_runtime::block_on(dispatch(routed)).unwrap();
        assert_eq!(
            result,
            json!({"state":"unknown", "errorCode":"record_invalid",
                                  "manageable":false})
        );
        assert!(!root.join("state/web").exists());
    }

    #[test]
    fn http_only_entries_do_not_supply_an_appserver_target() {
        let home = tempfile::tempdir().unwrap();
        let config = json!({ "version": 1, "defaultConnection": "office",
            "servers": [{ "id": "office", "webUrl": "http://127.0.0.1:1234" }] });
        std::fs::write(home.path().join("connections.json"), config.to_string()).unwrap();
        assert!(route(home.path(), Request::Environment).is_err());
    }
}
