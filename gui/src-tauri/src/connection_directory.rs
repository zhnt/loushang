//! The desktop reads the shared v1 connection directory without contacting a Host.
use crate::web_link::parse_web_url;
use rusqlite::{Connection, TransactionBehavior};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::num::NonZeroU16;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tauri::Url;

pub(crate) const LOCAL: &str = "local";
const CONFIG_ERROR: &str = "settings_unavailable";
const MAX_FILE_BYTES: u64 = 1_048_576;

type Result<T> = std::result::Result<T, &'static str>;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct SavedDirectory {
    version: u8,
    default_connection: Option<String>,
    servers: Vec<SavedServer>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct SavedServer {
    id: String,
    tunnel_port: NonZeroU16,
    web_url: Option<String>,
    name: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Entry {
    id: String,
    name: String,
    kind: &'static str,
    selected: bool,
    web_url: Option<Url>,
    #[serde(skip)]
    tunnel_port: Option<NonZeroU16>,
}

pub(crate) struct Directory {
    selected: String,
    entries: Vec<Entry>,
}

impl Directory {
    pub(crate) fn read(root: &Path) -> Result<Self> {
        Self::from_document(root, read_document(root)?)
    }

    fn from_document(root: &Path, document: Value) -> Result<Self> {
        let saved: SavedDirectory = serde_json::from_value(document).map_err(|_| CONFIG_ERROR)?;
        if saved.version != 1 || saved.servers.len() > 128 {
            return Err(CONFIG_ERROR);
        }
        let selected = saved
            .default_connection
            .filter(|id| !id.is_empty())
            .unwrap_or_else(|| LOCAL.into());
        let mut entries = vec![Entry {
            id: LOCAL.into(),
            name: "Local".into(),
            kind: LOCAL,
            selected: selected == LOCAL,
            web_url: local_url(root),
            tunnel_port: None,
        }];
        let mut ids = HashSet::new();
        for server in saved.servers {
            if !valid_id(&server.id) || !ids.insert(server.id.clone()) {
                return Err(CONFIG_ERROR);
            }
            let web_url = match server.web_url {
                Some(url) => Some(parse_web_url(&url).ok_or(CONFIG_ERROR)?),
                None => None,
            };
            entries.push(Entry {
                selected: server.id == selected,
                name: server.name.unwrap_or_else(|| server.id.clone()),
                id: server.id,
                kind: "remote",
                web_url,
                tunnel_port: Some(server.tunnel_port),
            });
        }
        let directory = Self { selected, entries };
        directory.entry(directory.selected())?;
        Ok(directory)
    }

    pub(crate) fn selected(&self) -> &str {
        &self.selected
    }

    fn entry(&self, id: &str) -> Result<&Entry> {
        self.entries
            .iter()
            .find(|entry| entry.id == id)
            .ok_or("unknown_connection")
    }

    pub(crate) fn tunnel_port(&self, id: &str) -> Result<Option<NonZeroU16>> {
        Ok(self.entry(id)?.tunnel_port)
    }

    pub(crate) fn listing(self) -> Value {
        json!({ "selectedId": self.selected, "connections": self.entries })
    }

    pub(crate) fn select(root: &Path, id: &str) -> Result<Value> {
        let mut lock = open_writer_lock(root)?;
        let _guard = lock
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|_| CONFIG_ERROR)?;
        let mut document = read_document(root)?;
        let mut directory = Self::from_document(root, document.clone())?;
        directory.entry(id)?;
        update_selection(&mut document, id)?;
        write_document(root, &document).map_err(|_| CONFIG_ERROR)?;
        directory.selected = id.into();
        for entry in &mut directory.entries {
            entry.selected = entry.id == id;
        }
        Ok(directory.listing())
    }
}

fn update_selection(document: &mut Value, id: &str) -> Result<()> {
    let fields = document.as_object_mut().ok_or(CONFIG_ERROR)?;
    if id == LOCAL {
        fields.remove("defaultConnection");
    } else {
        fields.insert("defaultConnection".into(), json!(id));
    }
    Ok(())
}

fn open_writer_lock(root: &Path) -> Result<Connection> {
    let state = root.join("state");
    create_private_dirs(&state).map_err(|_| CONFIG_ERROR)?;
    // The browser-side writer uses the same SQLite database and BEGIN IMMEDIATE.
    let lock =
        Connection::open(state.join("connection-config-lock.sqlite3")).map_err(|_| CONFIG_ERROR)?;
    lock.busy_timeout(Duration::from_secs(10))
        .map_err(|_| CONFIG_ERROR)?;
    Ok(lock)
}

fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id != LOCAL
        && id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
}

fn read_optional<T: DeserializeOwned>(path: PathBuf) -> Result<Option<T>> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(CONFIG_ERROR),
    };
    let mut bytes = Vec::new();
    file.take(MAX_FILE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| CONFIG_ERROR)?;
    if bytes.len() as u64 > MAX_FILE_BYTES {
        return Err(CONFIG_ERROR);
    }
    serde_json::from_slice(&bytes)
        .map(Some)
        .map_err(|_| CONFIG_ERROR)
}

fn read_document(root: &Path) -> Result<Value> {
    Ok(
        read_optional(root.join("connections.json"))?.unwrap_or_else(|| {
            json!({
                "version": 1, "defaultWorkspace": "", "servers": []
            })
        }),
    )
}

fn create_private_dirs(path: &Path) -> io::Result<()> {
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(path)
}

fn write_document(root: &Path, document: &Value) -> io::Result<()> {
    let mut temporary = tempfile::NamedTempFile::new_in(root)?;
    serde_json::to_writer(temporary.as_file_mut(), document)?;
    temporary.write_all(b"\n")?;
    temporary.as_file().sync_all()?;
    temporary
        .persist(root.join("connections.json"))
        .map_err(|error| error.error)?;
    Ok(())
}

#[derive(Default, Deserialize)]
struct HostConfig {
    #[serde(default)]
    web: WebConfig,
}

#[derive(Default, Deserialize)]
struct WebConfig {
    bind: Option<String>,
    port: Option<u16>,
    certificate: Option<String>,
}

#[derive(Deserialize)]
struct EndpointRecord {
    url: String,
}

fn local_url(root: &Path) -> Option<Url> {
    let configured = configured_local_url(root)?;
    let port = configured.port_or_known_default()?;
    let discovered = read_optional::<EndpointRecord>(root.join("state/web/endpoint.json"))
        .ok()
        .flatten()
        .and_then(|record| parse_web_url(&record.url));
    discovered
        .filter(|url| matches_local_endpoint(url, &configured, port))
        .or_else(|| (port != 0).then_some(configured))
}

fn matches_local_endpoint(url: &Url, configured: &Url, port: u16) -> bool {
    url.host() == configured.host()
        && url.scheme() == configured.scheme()
        && url.path() == "/"
        && url.port_or_known_default() != Some(0)
        && (port == 0 || url.port_or_known_default() == Some(port))
}

fn configured_local_url(root: &Path) -> Option<Url> {
    let config = read_optional::<HostConfig>(root.join("host.json"))
        .ok()?
        .unwrap_or_default()
        .web;
    let bind = match config.bind.as_deref() {
        None | Some("localhost" | "0.0.0.0") => "127.0.0.1",
        Some(bind) => bind,
    };
    let scheme = if config.certificate.is_some_and(|cert| !cert.is_empty()) {
        "https"
    } else {
        "http"
    };
    let port = config.port.unwrap_or(1422);
    parse_web_url(&format!("{scheme}://{bind}:{port}")).filter(|url| url.path() == "/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn selects_a_saved_host_even_if_local_settings_are_unreadable() {
        let home = tempfile::tempdir().unwrap();
        let root = home.path();
        let mut document = json!({ "version": 1, "defaultWorkspace": "/saved",
            "servers": [{ "id": "office", "webUrl": "https://office.example/base", "tunnelPort": 24420, "extra": 42 }],
            "extension": ["preserve me"] });
        write_document(root, &document).unwrap();
        fs::write(root.join("host.json"), "invalid json").unwrap();
        let listing = Directory::read(root).unwrap().listing();
        assert_eq!(listing["connections"][0]["webUrl"], Value::Null);
        assert_eq!(
            listing["connections"][1]["webUrl"],
            "https://office.example/base"
        );

        let switched = Directory::select(root, "office").unwrap();
        assert_eq!(switched["selectedId"], "office");
        assert_eq!(switched["connections"][0]["selected"], false);
        assert_eq!(switched["connections"][1]["selected"], true);
        document["defaultConnection"] = json!("office");
        assert_eq!(read_document(root).unwrap(), document);
        assert_eq!(
            Directory::select(root, "missing"),
            Err("unknown_connection")
        );
        assert_eq!(read_document(root).unwrap(), document);
        Directory::select(root, LOCAL).unwrap();
        assert!(read_document(root)
            .unwrap()
            .get("defaultConnection")
            .is_none());
    }

    #[test]
    fn discovers_dynamic_local_port_and_rejects_records_for_another_host() {
        let home = tempfile::tempdir().unwrap();
        let root = home.path();
        fs::create_dir_all(root.join("state/web")).unwrap();
        fs::write(root.join("host.json"), r#"{"web":{"port":0}}"#).unwrap();
        let record = root.join("state/web/endpoint.json");
        fs::write(&record, r#"{"url":"http://127.0.0.1:42000"}"#).unwrap();
        let active = Directory::read(root).unwrap().entries[0]
            .web_url
            .clone()
            .unwrap();
        assert_eq!(active.port(), Some(42000));
        fs::write(&record, r#"{"url":"http://example.test:42000"}"#).unwrap();
        assert_eq!(Directory::read(root).unwrap().entries[0].web_url, None);
    }
}
