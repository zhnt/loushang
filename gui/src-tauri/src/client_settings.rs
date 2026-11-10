//! Desktop connection selection and transport. AppHost owns management and sessions.
use crate::connection_directory::Directory;
use serde::Deserialize;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::Duration;
use tauri::{AppHandle, Manager, Url};

const SETTINGS_ERROR: &str = "settings_unavailable";
const MAX_REQUEST: usize = 1_000_000;
const MAX_RESPONSE: usize = 16 * 1024 * 1024;
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
    Local(Value),
    Http {
        endpoint: Url,
        body: Value,
        selected: Option<String>,
    },
}

fn route(root: &Path, request: Request) -> Result<Routed> {
    match request {
        Request::List => Directory::read(root).map(|directory| Routed::Local(directory.listing())),
        Request::Select { id } => Directory::select(root, &id).map(Routed::Local),
        Request::ToHost { id, request } => {
            Directory::read(root).and_then(|directory| forward(&directory, &id, request, false))
        }
        Request::ToSelected { request } => {
            let directory = Directory::read(root)?;
            forward(&directory, directory.selected(), request, false)
        }
        Request::Environment => {
            let directory = Directory::read(root)?;
            forward(
                &directory,
                directory.selected(),
                json!({ "operation": "environment" }),
                true,
            )
        }
    }
}

fn forward(directory: &Directory, id: &str, body: Value, environment: bool) -> Result<Routed> {
    Ok(Routed::Http {
        endpoint: directory.endpoint(id)?,
        body,
        selected: environment.then(|| id.to_owned()),
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

fn http_client() -> Result<&'static reqwest::Client> {
    static CLIENT: OnceLock<Result<reqwest::Client>> = OnceLock::new();
    CLIENT
        .get_or_init(|| {
            reqwest::Client::builder()
                .no_proxy()
                .redirect(reqwest::redirect::Policy::none())
                .retry(reqwest::retry::never())
                .connect_timeout(Duration::from_secs(3))
                .timeout(Duration::from_secs(80))
                .build()
                .map_err(|_| SETTINGS_ERROR)
        })
        .as_ref()
        .map_err(|error| *error)
}

#[derive(Deserialize)]
struct Reply {
    result: Value,
}

async fn send(endpoint: Url, body: Value) -> Result<Value> {
    let url = format!("{}/api/loushang", endpoint.as_str().trim_end_matches('/'));
    let payload = serde_json::to_vec(&body).map_err(|_| "invalid_request")?;
    if payload.len() > MAX_REQUEST {
        return Err("invalid_request");
    }
    let mut response = http_client()?
        .post(url)
        .header("X-Loushang-Client", "1")
        .header("Content-Type", "application/json")
        .body(payload)
        .send()
        .await
        .map_err(|_| "connection_failed")?;
    if !response.status().is_success() {
        return Err("connection_failed");
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "connection_failed")? {
        if chunk.len() > MAX_RESPONSE - bytes.len() {
            return Err("response_too_large");
        }
        bytes.extend_from_slice(&chunk);
    }
    serde_json::from_slice::<Reply>(&bytes)
        .map(|reply| reply.result)
        .map_err(|_| SETTINGS_ERROR)
}

async fn dispatch(routed: Routed) -> Result<Value> {
    match routed {
        Routed::Local(value) => Ok(value),
        Routed::Http {
            endpoint,
            body,
            selected,
        } => {
            let mut value = send(endpoint, body).await?;
            if let Some(id) = selected {
                let fields = value.as_object_mut().ok_or(SETTINGS_ERROR)?;
                fields.insert("connectionId".into(), json!(id));
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
    use std::io::{BufRead, BufReader, Write};
    use std::net::TcpListener;

    fn http_peer(
        status: &str,
        headers: &str,
        body: &str,
    ) -> (Url, std::thread::JoinHandle<String>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = Url::parse(&format!("http://{}/prefix", listener.local_addr().unwrap())).unwrap();
        let response = format!(
            "HTTP/1.1 {status}\r\n{headers}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        );
        let worker = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(3)))
                .unwrap();
            let mut reader = BufReader::new(&mut stream);
            let mut request = String::new();
            loop {
                let mut line = String::new();
                reader.read_line(&mut line).unwrap();
                if line == "\r\n" || line.is_empty() {
                    break;
                }
                request.push_str(&line);
            }
            stream.write_all(response.as_bytes()).unwrap();
            request
        });
        (url, worker)
    }

    #[test]
    fn sends_environment_to_the_selected_endpoint() {
        let (url, peer) = http_peer("200 OK", "", r#"{"result":{"workspace":"/remote"}}"#);
        let home = tempfile::tempdir().unwrap();
        let config = json!({ "version": 1, "defaultConnection": "office",
            "servers": [{ "id": "office", "url": url }] });
        std::fs::write(home.path().join("connections.json"), config.to_string()).unwrap();
        let routed = route(home.path(), Request::Environment).unwrap();
        let result = tauri::async_runtime::block_on(dispatch(routed)).unwrap();
        assert_eq!(
            result,
            json!({ "workspace": "/remote", "connectionId": "office" })
        );
        let request = peer.join().unwrap().to_ascii_lowercase();
        assert!(request.starts_with("post /prefix/api/loushang http/1.1\r\n"));
        assert!(request.contains("\r\nx-loushang-client: 1\r\n"));
    }

    #[test]
    fn refuses_to_forward_a_host_request_to_a_redirect_target() {
        let destination = TcpListener::bind("127.0.0.1:0").unwrap();
        let location = format!(
            "Location: http://{}/api/loushang\r\n",
            destination.local_addr().unwrap()
        );
        let (url, peer) = http_peer("307 Temporary Redirect", &location, "");
        assert_eq!(
            tauri::async_runtime::block_on(send(url, json!({"operation":"environment"}))),
            Err("connection_failed")
        );
        peer.join().unwrap();
        destination.set_nonblocking(true).unwrap();
        assert!(destination.accept().is_err());
    }
}
