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
            let backend = BACKEND.get_or_init(|| Backend::new(root.clone()));
            let backend = if let Some(port) = tunnel {
                backend.through_tunnel(root.join("app-tunnels").join(&id), port)
            } else {
                backend.clone()
            };
            let mut value = tauri::async_runtime::spawn_blocking(move || backend.call(body))
                .await
                .map_err(|_| SETTINGS_ERROR)?
                .map_err(|_| "connection_failed")?;
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
