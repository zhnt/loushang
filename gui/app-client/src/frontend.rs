//! Browser and desktop requests use the same AppServer client.
mod client_directories;
mod live_view;
mod service;
use crate::{
    definitive_create_rejection, AppClient, AppTarget, ConnectionOptions, ControlCommand,
    ControlResult, CreateSessionResult, InteractiveGoalCommand, InteractiveGoalReviewSubmission,
    ModelControlResult, WorkspaceInfo, WorkspaceRequest, WorkspaceResult, WorkspaceScope,
};
use live_view::{Target, View};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    num::NonZeroU16,
    path::PathBuf,
    sync::{mpsc, Arc, Mutex},
    time::Duration,
};

const TIMEOUT: Duration = Duration::from_secs(10);
const TEMPORARY: &str = "@temporary";
const TEMPORARY_MUX: &str = "gui-temporary";
type Result<T> = std::result::Result<T, String>;

#[derive(Clone)]
pub struct Backend {
    root: PathBuf,
    tunnel: Option<(PathBuf, NonZeroU16)>,
    requests: Arc<Mutex<()>>,
    views: Arc<Mutex<HashMap<String, View>>>,
    next_view_epoch: Arc<Mutex<u64>>,
    manager: Option<PathBuf>,
    managed_record: Arc<Mutex<Option<PathBuf>>>,
    client_directories: Arc<Mutex<client_directories::Grants>>,
}

impl Backend {
    pub fn new(root: PathBuf) -> Self {
        Self {
            root,
            tunnel: None,
            requests: Arc::new(Mutex::new(())),
            views: Arc::default(),
            next_view_epoch: Arc::default(),
            manager: None,
            managed_record: Arc::new(Mutex::new(None)),
            client_directories: Arc::default(),
        }
    }

    pub fn with_service_management(mut self) -> Self {
        self.manager = service::executable();
        self
    }

    pub fn through_tunnel(&self, root: PathBuf, port: NonZeroU16) -> Self {
        Self {
            tunnel: Some((root.clone(), port)),
            root,
            requests: self.requests.clone(),
            views: self.views.clone(),
            next_view_epoch: self.next_view_epoch.clone(),
            manager: None,
            managed_record: Arc::new(Mutex::new(None)),
            client_directories: self.client_directories.clone(),
        }
    }

    pub fn grant_client_directory(&self, path: PathBuf) -> Result<Value> {
        let target = self
            .host_target(self.configured_record()?)?
            .ok_or("not_connected")?;
        self.client_directories
            .lock()
            .map_err(|_| "host_unavailable")?
            .add(target, path)
    }

    pub fn call(&self, request: Value) -> Result<Value> {
        let _request = self.requests.lock().map_err(|_| "host_unavailable")?;
        self.dispatch(&request)
    }

    fn dispatch(&self, request: &Value) -> Result<Value> {
        let operation = field(request, "operation")?;
        match operation {
            "account" => Ok(json!({
                "name": std::env::var(if cfg!(windows) { "USERNAME" } else { "USER" }).unwrap_or_default(),
                "id": null
            })),
            "preferences" => self.preferences(request),
            "remember-workspace" => {
                self.set_last_workspace(field(request, "workspace")?)?;
                Ok(json!({}))
            }
            _ => self.host_request(operation, request),
        }
    }

    fn configured_record(&self) -> Result<Option<PathBuf>> {
        if self.tunnel.is_some() {
            return Ok(None);
        }
        self.record_root()
    }

    fn host_target(&self, configured_record: Option<PathBuf>) -> Result<Option<Target>> {
        if let Some((root, port)) = &self.tunnel {
            return Ok(Some(Target::Tunnel(root.clone(), *port)));
        }
        let root = match configured_record {
            Some(path) => Some(path),
            None => self
                .managed_record
                .lock()
                .map_err(|_| "host_unavailable")?
                .clone(),
        };
        Ok(root.map(Target::Local))
    }

    fn host_request(&self, operation: &str, request: &Value) -> Result<Value> {
        let configured_record = self.configured_record()?;
        let manager = self
            .manager
            .as_deref()
            .filter(|_| configured_record.is_none());
        if let (Some(manager), "manage") = (manager, operation) {
            return self.manage_service(manager, request);
        }
        let host_target = self.host_target(configured_record)?;
        let target = host_target.as_ref().map(Target::borrow);
        match operation {
            "environment" => Ok(json!({
                "supported": target.is_some() || manager.is_some(),
                "manageable": manager.is_some(), "workspace": self.last_workspace()?,
            })),
            "manage" => status(target, field(request, "action")?),
            "workspace" => self.workspace(target.ok_or("not_connected")?, request),
            "live" => self.live(target.ok_or("not_connected")?, request),
            "revoke-client-directory" => {
                let selector = field(request, "id")?;
                let target = host_target.as_ref().ok_or("not_connected")?;
                let removed = self
                    .client_directories
                    .lock()
                    .map_err(|_| "host_unavailable")?
                    .revoke(target, selector);
                Ok(json!({"removed": removed}))
            }
            _ => Err("unknown_operation".into()),
        }
    }

    fn live(&self, target: AppTarget<'_>, request: &Value) -> Result<Value> {
        let id = field(request, "viewId")?;
        if id.len() != 36
            || !id
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() || byte == b'-')
        {
            return Err("invalid_request".into());
        }
        let path = field(request, "workspace")?;
        let action = field(request, "action")?;
        let identity = Target::from(target);
        let mut views = self.views.lock().map_err(|_| "host_unavailable")?;
        views.retain(|_, view| view.active());
        if views
            .get(id)
            .is_some_and(|view| view.target != identity || view.path != path)
        {
            return Err("invalid_request".into());
        }
        if action == "close" {
            views.remove(id);
            return Ok(json!({}));
        }
        if matches!(action, "snapshot" | "find-submission") && !views.contains_key(id) {
            if views.len() >= 16 {
                return Err("connection_failed".into());
            }
            let workspace = if path == TEMPORARY {
                None
            } else {
                Some(open_workspace(target, path)?)
            };
            let mux = workspace
                .as_ref()
                .map_or_else(|| TEMPORARY_MUX.into(), workspace_mux_name);
            let epoch = {
                let mut counter = self
                    .next_view_epoch
                    .lock()
                    .map_err(|_| "host_unavailable")?;
                *counter = counter.checked_add(1).ok_or("host_unavailable")?;
                *counter
            };
            let view = View::open(identity, path.to_owned(), workspace, mux, epoch)?;
            views.insert(id.to_owned(), view);
        }
        let view = views.get(id).ok_or("connection_failed")?;
        match action {
            "snapshot" => {
                let snapshot = view.snapshot()?;
                self.client_directories
                    .lock()
                    .map_err(|_| "host_unavailable")?
                    .serve(view, &snapshot);
                Ok(snapshot)
            }
            "client-directory-reference" => self
                .client_directories
                .lock()
                .map_err(|_| "host_unavailable")?
                .reference(view, &request["input"]),
            "create" => created(view.control(None, create_command(&request["input"])?)?),
            _ => session_control(view, action, &request["input"]),
        }
    }

    fn manage_service(&self, manager: &std::path::Path, request: &Value) -> Result<Value> {
        let (action, instance) = match field(request, "action")? {
            "status" | "connect" => ("status", None),
            "start" => ("start", None),
            action @ ("stop" | "restart") => {
                let instance = field(request, "instanceId")?;
                if instance.len() != 32
                    || !instance
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                {
                    return Err("invalid_request".into());
                }
                (action, Some(instance))
            }
            _ => return Err("invalid_request".into()),
        };
        let error = |code: &str| json!({"state":"unknown", "errorCode":code, "manageable":true});
        let reply = match service::invoke(manager, &self.root, action, instance) {
            Ok(reply) => reply,
            Err(code) => return Ok(error(code)),
        };
        if let Some(code) = reply.error_code {
            return Ok(error(&code));
        }
        if reply.state != "running" {
            if !matches!(
                reply.state.as_str(),
                "not_running" | "starting" | "stopping" | "exited" | "unknown"
            ) {
                return Ok(error("management_unconfirmed"));
            }
            *self.managed_record.lock().map_err(|_| "host_unavailable")? = None;
            return Ok(json!({"state":reply.state, "errorCode":null, "manageable":true}));
        }
        let Some(root) = reply.record_root.filter(|path| path.is_absolute()) else {
            return Ok(error("management_unconfirmed"));
        };
        let client = AppClient::default();
        let service_instance = match client.instance(AppTarget::Local(&root), TIMEOUT) {
            Ok(instance) => instance,
            Err(()) => return Ok(error(client.failure_code())),
        };
        if reply
            .service_instance_id
            .is_some_and(|expected| expected != service_instance)
        {
            return Ok(error("instance_changed"));
        }
        *self.managed_record.lock().map_err(|_| "host_unavailable")? = Some(root);
        Ok(
            json!({"state":"running", "errorCode":null, "manageable":true,
                  "instanceId":reply.instance_id, "serviceInstanceId":service_instance}),
        )
    }

    fn record_root(&self) -> Result<Option<PathBuf>> {
        if let Some(path) = std::env::var_os("LOUSHANG_APP_RECORD_ROOT") {
            return absolute(PathBuf::from(path)).map(Some);
        }
        let path = self.root.join("host.json");
        let bytes = match std::fs::read(path) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err("settings_unavailable".into()),
        };
        let value: Value = serde_json::from_slice(&bytes).map_err(|_| "settings_unavailable")?;
        match value.get("appServer") {
            None => Ok(None),
            Some(config) => absolute(PathBuf::from(field(config, "recordRoot")?)).map(Some),
        }
    }

    fn workspace(&self, target: AppTarget<'_>, request: &Value) -> Result<Value> {
        let action = field(request, "action")?;
        let operation = match action {
            "navigation" => return self.navigation(target),
            "create-chat" => return create_chat(target, request),
            "delete-chat" => return delete_chat(target, request),
            "models" => {
                let selector = optional_workspace_path(request)?;
                let (workspace, path) = selector
                    .filter(|value| workspace_id(value))
                    .map_or((None, selector), |value| (Some(value), None));
                let model_id = request
                    .get("modelId")
                    .map(|id| id.as_str().ok_or("invalid_request"))
                    .transpose()?;
                let client = AppClient::default();
                return models(
                    client
                        .workspace_models(target, TIMEOUT, path, workspace, model_id)
                        .map_err(|_| client.failure_code())?,
                );
            }
            "inspect" => {
                let path = field(request, "path")?;
                let session = request.get("sessionId").and_then(Value::as_str);
                if workspace_id(path) {
                    let operation = WorkspaceRequest::Logical {
                        action: "inspect-workspace",
                        path: None,
                        fields: json!({"workspaceId": path, "sessionId": session, "scopeFingerprint": request["fingerprint"]}),
                    };
                    return Ok(json!({"workspaces": workspaces(target, operation)?}));
                }
                let inspect = WorkspaceRequest::Inspect { path, session };
                return match workspaces(target, inspect) {
                    Ok(items) => Ok(json!({"workspaces": items})),
                    Err(code)
                        if matches!(
                            code.as_str(),
                            "connection_failed" | "invalid_request" | "operation_unavailable"
                        ) =>
                    {
                        match workspaces(target, WorkspaceRequest::Projects) {
                            Ok(items) if items.iter().any(|item| item.path == path) => {
                                Err("workspace_inspection_unavailable".into())
                            }
                            _ => Err(code),
                        }
                    }
                    Err(code) => Err(code),
                };
            }
            "preview" => return preview_workspace(target, request),
            "locate" => {
                let instance = field(request, "serviceInstanceId")?;
                let client = AppClient::default();
                if client
                    .instance(target, TIMEOUT)
                    .map_err(|_| "connection_failed")?
                    != instance
                {
                    return Err("instance_changed".into());
                }
                let workspace = workspace_by_fingerprint(target, field(request, "fingerprint")?)?;
                if client
                    .instance(target, TIMEOUT)
                    .map_err(|_| "connection_failed")?
                    != instance
                {
                    return Err("instance_changed".into());
                }
                return Ok(json!({ "path": workspace.path }));
            }
            "open" => return self.open(target, field(request, "path")?),
            "create-workspace"
            | "rename-workspace"
            | "delete-workspace"
            | "delete-workspace-with-history"
            | "add-path"
            | "update-path"
            | "remove-path"
            | "set-default-path" => WorkspaceRequest::Logical {
                action,
                path: optional_workspace_path(request)?,
                fields: json!({
                    "workspaceId": request["workspaceId"], "name": request["name"],
                    "pathId": request["pathId"], "alias": request["alias"],
                }),
            },
            "list" => WorkspaceRequest::List,
            "projects" => WorkspaceRequest::Projects,
            "create" => WorkspaceRequest::Create(workspace_creation_path(request)?),
            "register" => WorkspaceRequest::Register(field(request, "path")?),
            "unregister" => WorkspaceRequest::Unregister(field(request, "path")?),
            _ => return Err("unknown_operation".into()),
        };
        Ok(json!({"workspaces": workspaces(target, operation)?}))
    }

    fn open(&self, target: AppTarget<'_>, path: &str) -> Result<Value> {
        let opened = open_workspace(target, path)?;
        let mux = workspace_mux_name(&opened);
        let mut connection = options(target, &mux, Some(&opened));
        connection.prepare_default_session = true;
        AppClient::default()
            .run(connection, &mut |_| Ok(()))
            .map_err(|_| "connection_failed")?;
        self.set_last_workspace(&opened.path)?;
        Ok(json!({"workspaces": [opened]}))
    }

    fn navigation(&self, target: AppTarget<'_>) -> Result<Value> {
        let projects = workspaces(
            target,
            WorkspaceRequest::Logical {
                action: "workspaces",
                path: None,
                fields: json!({}),
            },
        )?;
        let muxes = AppClient::default()
            .muxes(target, TIMEOUT)
            .map_err(|_| "connection_failed")?;
        let database = self.database()?;
        let chats = |name: &str| -> Result<Vec<Value>> {
            let Some(mux) = muxes.iter().find(|mux| mux["name"] == name) else {
                return Ok(vec![]);
            };
            let scope = format!("mux:{}", field(mux, "muxSpaceId")?);
            let pinned = pins(&database, &scope)?;
            // Mux members are appended in creation order and retained in that order.
            let mut result = mux["members"].as_array().ok_or("invalid_host_reply")?.iter().rev().map(|member| {
                let id = field(&member["session"], "sessionId")?;
                Ok(json!({"id": id, "continuityId": member["session"]["continuityId"], "title": member["title"], "scope": scope, "pinned": pinned.iter().any(|value| value == id)}))
            }).collect::<Result<Vec<_>>>()?;
            result.sort_by_key(|chat| chat["pinned"] != true);
            Ok(result)
        };
        let mut entries = vec![];
        let mut default_chats = vec![];
        for item in projects {
            let workspace = item.workspace.ok_or("invalid_host_reply")?;
            let sessions = chats(&workspace.mux_name)?;
            if workspace.default {
                default_chats = sessions;
                continue;
            }
            let mut entry = serde_json::to_value(&workspace).map_err(|_| "invalid_host_reply")?;
            entry["sessions"] = json!(sessions);
            entry["path"] = json!(workspace
                .paths
                .iter()
                .find(|link| Some(&link.id) == workspace.default_path_id.as_ref())
                .map(|link| &link.path));
            entries.push(entry);
        }
        Ok(json!({"projects": entries, "temporarySessions": default_chats}))
    }

    fn database(&self) -> Result<Connection> {
        let directory = self.root.join("data");
        std::fs::create_dir_all(&directory).map_err(|_| "settings_unavailable")?;
        let db = Connection::open(directory.join("client-preferences.sqlite3"))
            .map_err(|_| "settings_unavailable")?;
        db.execute_batch(
            "CREATE TABLE IF NOT EXISTS ui_pin (scope TEXT, session TEXT, PRIMARY KEY(scope, session));
             CREATE TABLE IF NOT EXISTS ui_selection (id INTEGER PRIMARY KEY CHECK(id=1), workspace TEXT);",
        ).map_err(|_| "settings_unavailable")?;
        Ok(db)
    }

    fn last_workspace(&self) -> Result<String> {
        let db = self.database()?;
        use rusqlite::OptionalExtension;
        db.query_row("SELECT workspace FROM ui_selection WHERE id=1", [], |row| {
            row.get(0)
        })
        .optional()
        .map(|value| value.unwrap_or_default())
        .map_err(|_| "settings_unavailable".into())
    }

    fn set_last_workspace(&self, path: &str) -> Result<()> {
        self.database()?
            .execute(
                "INSERT INTO ui_selection(id, workspace) VALUES(1, ?1)
             ON CONFLICT(id) DO UPDATE SET workspace=excluded.workspace",
                [path],
            )
            .map(|_| ())
            .map_err(|_| "settings_unavailable".into())
    }

    fn preferences(&self, request: &Value) -> Result<Value> {
        let scope = field(request, "scope")?;
        let db = self.database()?;
        match request
            .get("action")
            .and_then(Value::as_str)
            .unwrap_or("read")
        {
            "pin" => {
                db.execute(
                    "INSERT OR IGNORE INTO ui_pin(scope, session) VALUES(?1, ?2)",
                    params![scope, field(request, "session")?],
                )
                .map_err(|_| "settings_unavailable")?;
            }
            "unpin" => {
                db.execute(
                    "DELETE FROM ui_pin WHERE scope=?1 AND session=?2",
                    params![scope, field(request, "session")?],
                )
                .map_err(|_| "settings_unavailable")?;
            }
            "read" => (),
            _ => return Err("unknown_operation".into()),
        }
        Ok(json!({"pinned": pins(&db, scope)?, "recent": [], "selected": ""}))
    }
}

fn pins(db: &Connection, scope: &str) -> Result<Vec<String>> {
    let mut query = db
        .prepare("SELECT session FROM ui_pin WHERE scope=?1 ORDER BY rowid")
        .map_err(|_| "settings_unavailable")?;
    let rows = query
        .query_map([scope], |row| row.get(0))
        .map_err(|_| "settings_unavailable")?;
    rows.collect::<rusqlite::Result<_>>()
        .map_err(|_| "settings_unavailable".into())
}

fn absolute(path: PathBuf) -> Result<PathBuf> {
    path.is_absolute()
        .then_some(path)
        .ok_or_else(|| "settings_unavailable".into())
}

fn field<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty() && value.len() <= 1_000_000)
        .ok_or_else(|| "invalid_request".into())
}

fn mux_name(path: &str) -> String {
    format!(
        "ws-{:.60}",
        format!("{:x}", Sha256::digest(path.as_bytes()))
    )
}

fn workspace_creation_path(request: &Value) -> Result<&str> {
    let path = request["path"].as_str().ok_or("invalid_request")?;
    let absolute = path.starts_with('/')
        || matches!(path.as_bytes(), [drive, b':', b'/' | b'\\', ..] if drive.is_ascii_alphabetic());
    if !absolute || path.contains('\0') || path.chars().count() > 4096 {
        return Err("invalid_request".into());
    }
    Ok(path)
}

fn workspaces(target: AppTarget<'_>, request: WorkspaceRequest<'_>) -> Result<Vec<WorkspaceInfo>> {
    match AppClient::default()
        .workspace(target, TIMEOUT, request)
        .map_err(|_| "connection_failed")?
    {
        WorkspaceResult::Accepted(items) => Ok(items),
        WorkspaceResult::Rejected(code) => Err(code),
    }
}

fn single(items: Vec<WorkspaceInfo>) -> Result<WorkspaceInfo> {
    let [workspace]: [WorkspaceInfo; 1] = items.try_into().map_err(|_| "invalid_host_reply")?;
    Ok(workspace)
}

fn preview_workspace(target: AppTarget<'_>, request: &Value) -> Result<Value> {
    let path = field(request, "path")?;
    let fingerprint = field(request, "fingerprint")?;
    let located;
    let path = if path == TEMPORARY {
        located = workspace_by_fingerprint(target, fingerprint)?;
        located.path.as_str()
    } else {
        path
    };
    let instance = field(request, "serviceInstanceId")?;
    let reference = field(request, "reference")?;
    let base = request
        .get("base")
        .and_then(Value::as_str)
        .ok_or("invalid_request")?;
    let logical = workspace_id(path);
    let operation = if logical {
        WorkspaceRequest::LogicalPreview {
            workspace_id: path,
            instance,
            reference,
            base,
            fingerprint,
        }
    } else {
        WorkspaceRequest::Preview {
            path,
            instance,
            reference,
            base,
            fingerprint,
        }
    };
    let workspace = single(workspaces(target, operation)?)?;
    if (!logical && workspace.path != path) || workspace.scope_fingerprint != fingerprint {
        return Err("invalid_host_reply".into());
    }
    let preview = workspace.preview.ok_or("workspace_preview_unavailable")?;
    serde_json::to_value(preview).map_err(|_| "invalid_host_reply".into())
}

fn workspace_by_fingerprint(target: AppTarget<'_>, fingerprint: &str) -> Result<WorkspaceInfo> {
    let mut matches = workspaces(target, WorkspaceRequest::List)?
        .into_iter()
        .filter(|item| {
            matches!(item.scope, WorkspaceScope::Cwd) && item.scope_fingerprint == fingerprint
        });
    match (matches.next(), matches.next()) {
        (Some(workspace), None) => Ok(workspace),
        _ => Err("workspace_unavailable".into()),
    }
}

fn workspace_id(value: &str) -> bool {
    value == "default"
        || (value.len() == 32
            && value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)))
}

fn workspace_mux_name(info: &WorkspaceInfo) -> String {
    info.workspace.as_ref().map_or_else(
        || mux_name(&info.path),
        |workspace| workspace.mux_name.clone(),
    )
}

fn open_workspace(target: AppTarget<'_>, path: &str) -> Result<WorkspaceInfo> {
    let operation = if workspace_id(path) {
        WorkspaceRequest::Logical {
            action: "open-workspace",
            path: None,
            fields: json!({"workspaceId": path}),
        }
    } else {
        WorkspaceRequest::Open(path)
    };
    single(workspaces(target, operation)?)
}

fn status(target: Option<AppTarget<'_>>, action: &str) -> Result<Value> {
    if !matches!(action, "connect" | "status") {
        return Err("service_managed_externally".into());
    }
    let client = AppClient::default();
    if let Some(target) = target {
        match client.instance(target, TIMEOUT) {
            Ok(instance) => {
                return Ok(json!({
                    "state": "running", "errorCode": null,
                    "manageable": false, "serviceInstanceId": instance,
                }))
            }
            Err(()) if matches!(target, AppTarget::Tunnel { .. }) => {
                return Ok(json!({
                    "state": "unknown", "errorCode": client.failure_code(), "manageable": false,
                }))
            }
            Err(()) => {}
        }
    }
    Ok(json!({"state": "not_running", "errorCode": null, "manageable": false}))
}

fn options<'a>(
    target: AppTarget<'a>,
    mux: &'a str,
    workspace: Option<&'a WorkspaceInfo>,
) -> ConnectionOptions<'a> {
    ConnectionOptions {
        target,
        mux_name: mux,
        workspace_scope: workspace,
        timeout: TIMEOUT,
        cancel: None,
        attach: true,
        prepare_default_session: false,
        stop: None,
        control_commands: None,
    }
}

fn control<T>(
    options: ConnectionOptions<'_>,
    build: impl FnOnce(mpsc::SyncSender<std::result::Result<T, ()>>) -> ControlCommand,
) -> Result<T> {
    control_on(options, None, &mut None, build)
}

fn control_on<T>(
    options: ConnectionOptions<'_>,
    expected_instance: Option<&str>,
    observed_instance: &mut Option<String>,
    build: impl FnOnce(mpsc::SyncSender<std::result::Result<T, ()>>) -> ControlCommand,
) -> Result<T> {
    let (send, receive) = mpsc::channel();
    let (reply, result) = mpsc::sync_channel(1);
    let mut command = Some(build(reply));
    let options = ConnectionOptions {
        control_commands: Some(&receive),
        ..options
    };
    let client = AppClient::default();
    // A successful create invalidates its attachment, so the command receipt
    // can be authoritative even when the connection ends before a snapshot.
    let _ = client.run_stream(
        options,
        1,
        &mut |_| Ok(()),
        &mut |_| Ok(()),
        &mut |authority| {
            if let Some(authority) = authority {
                let instance = authority.service_instance_id();
                if expected_instance.is_some_and(|expected| expected != instance) {
                    return Err(());
                }
                if let Some(command) = command.take() {
                    *observed_instance = Some(instance.to_owned());
                    send.send(command).map_err(|_| ())?;
                }
            }
            Ok(())
        },
        &mut || Ok(false),
    );
    result
        .try_recv()
        .map_err(|_| "connection_failed")?
        .map_err(|_| "connection_failed".into())
}

fn delete_chat(target: AppTarget<'_>, input: &Value) -> Result<Value> {
    let path = field(input, "path")?;
    let session_id = field(input, "sessionId")?.to_owned();
    let mux_space_id = field(input, "scope")?
        .strip_prefix("mux:")
        .filter(|id| !id.is_empty() && id.len() <= 512)
        .ok_or("invalid_request")?
        .to_owned();
    let instance = field(input, "serviceInstanceId")?;
    let mux = if path == TEMPORARY {
        TEMPORARY_MUX.to_owned()
    } else if workspace_id(path) {
        workspace_mux_name(&open_workspace(target, path)?)
    } else {
        mux_name(path)
    };
    let accepted = control_on(
        options(target, &mux, None),
        Some(instance),
        &mut None,
        |reply| ControlCommand::CloseSession {
            mux_space_id,
            session_id,
            reply,
        },
    )?;
    Ok(json!({"accepted": accepted}))
}

fn create_command(
    input: &Value,
) -> Result<
    impl FnOnce(mpsc::SyncSender<std::result::Result<CreateSessionResult, ()>>) -> ControlCommand,
> {
    let title = field(input, "title")?.to_owned();
    let continuity_id = match input.get("continuityId") {
        Some(value) if !value.is_null() => {
            let id = value.as_str().ok_or("invalid_request")?;
            if id.len() > 512
                || !id.as_bytes().first().is_some_and(u8::is_ascii_alphanumeric)
                || !id
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"._~-".contains(&byte))
            {
                return Err("invalid_request".into());
            }
            id.to_owned()
        }
        _ => {
            let mut entropy = [0_u8; 16];
            getrandom::getrandom(&mut entropy).map_err(|_| "host_unavailable")?;
            entropy.iter().map(|byte| format!("{byte:02x}")).collect()
        }
    };
    let source_session_id = input["sourceSessionId"].as_str().map(str::to_owned);
    Ok(move |reply| ControlCommand::CreateSession {
        source_session_id,
        continuity_id,
        title,
        reply,
    })
}

fn created(result: CreateSessionResult) -> Result<Value> {
    match result {
        CreateSessionResult::Accepted(session_id) => {
            Ok(json!({"sessionId":session_id, "accepted":true}))
        }
        CreateSessionResult::Rejected(code) => Err(code),
    }
}

fn optional_workspace_path(request: &Value) -> Result<Option<&str>> {
    request
        .get("path")
        .filter(|path| !path.is_null())
        .map(|path| path.as_str().ok_or_else(|| "invalid_request".into()))
        .transpose()
}

fn create_chat(target: AppTarget<'_>, request: &Value) -> Result<Value> {
    let title = request
        .get("title")
        .map(|value| value.as_str().ok_or("invalid_request"))
        .transpose()?
        .unwrap_or("New Session");
    if title.trim().is_empty() || title.chars().count() > 256 {
        return Err("invalid_request".into());
    }
    let command = create_command(&json!({
        "title": title, "continuityId": request["continuityId"],
    }))?;
    let workspace_path = optional_workspace_path(request)?;
    let scope = match workspace_path {
        Some(path) => open_workspace(target, path),
        None => open_workspace(target, "default"),
    };
    let Ok(scope) = scope else {
        return Ok(json!({"accepted": false}));
    };
    let path = workspace_path.unwrap_or(TEMPORARY);
    let mux = workspace_mux_name(&scope);
    match control(options(target, &mux, Some(&scope)), command)? {
        CreateSessionResult::Accepted(session_id) => {
            Ok(json!({"workspace": path, "sessionId": session_id}))
        }
        CreateSessionResult::Rejected(code) if definitive_create_rejection(&code) => {
            Ok(json!({"accepted": false}))
        }
        CreateSessionResult::Rejected(code) => Err(code),
    }
}

fn session_control(view: &View, action: &str, input: &Value) -> Result<Value> {
    let session_id = field(input, "sessionId")?.to_owned();
    match action {
        "submit" | "find-submission" | "goal-start" => submission(view, action, session_id, input),
        "resource" => view.control(None, |reply| ControlCommand::Resource {
            session_id,
            query: input["query"].clone(),
            reply,
        }),
        "interrupt" => {
            let execution_id = field(input, "executionId")?.to_owned();
            let result = view.control(None, |reply| ControlCommand::Interrupt {
                session_id,
                execution_id,
                reply,
            })?;
            Ok(json!({"accepted": matches!(result, ControlResult::Accepted)}))
        }
        "interactive-goal-create" | "interactive-goal-status" => {
            let instance = field(input, "serviceInstanceId")?;
            let epoch = field(input, "connectionEpoch")?;
            let target = if action == "interactive-goal-create" {
                Some(field(input, "goalTarget")?.to_owned())
            } else {
                None
            };
            if input.as_object().map(|object| object.len())
                != Some(3 + usize::from(target.is_some()))
            {
                return Err("invalid_request".into());
            }
            if epoch != view.epoch.to_string() {
                return Ok(Value::Null);
            }
            let result = view.control(Some(instance), |reply| {
                ControlCommand::interactive_goal(session_id, target, reply)
            })?;
            Ok(json!(result))
        }
        "interactive-goal-command" => {
            let instance = field(input, "serviceInstanceId")?;
            let epoch = field(input, "connectionEpoch")?;
            if input.as_object().map(|object| object.len()) != Some(6) {
                return Err("invalid_request".into());
            }
            let command = serde_json::from_value::<InteractiveGoalCommand>(json!({
                "goalId": input["goalId"], "commandId": input["commandId"], "action": input["action"],
            })).map_err(|_| "invalid_request")?;
            if epoch != view.epoch.to_string() {
                return Ok(Value::Null);
            }
            let result = view.control(Some(instance), |reply| {
                ControlCommand::ControlInteractiveGoal {
                    session_id,
                    command,
                    reply,
                }
            })?;
            Ok(json!(result))
        }
        "interactive-goal-recovery" => {
            let instance = field(input, "serviceInstanceId")?;
            let epoch = field(input, "connectionEpoch")?;
            if input.as_object().map(|object| object.len()) != Some(3) {
                return Err("invalid_request".into());
            }
            if epoch != view.epoch.to_string() {
                return Ok(Value::Null);
            }
            let result = view.control(Some(instance), |reply| {
                ControlCommand::ReadInteractiveGoalRecovery { session_id, reply }
            })?;
            Ok(json!(result))
        }
        "interactive-goal-review" | "interactive-goal-review-submit" => {
            let instance = field(input, "serviceInstanceId")?;
            let epoch = field(input, "connectionEpoch")?;
            let goal_id = field(input, "goalId")?.to_owned();
            let submit = action == "interactive-goal-review-submit";
            if input.as_object().map(|object| object.len()) != Some(if submit { 8 } else { 4 }) {
                return Err("invalid_request".into());
            }
            if epoch != view.epoch.to_string() {
                return Ok(Value::Null);
            }
            let review = if submit {
                let reason = input.get("reason").ok_or("invalid_request")?;
                Some(serde_json::from_value::<InteractiveGoalReviewSubmission>(json!({
                    "goalId": goal_id, "commandId": input["commandId"], "reviewToken": input["reviewToken"],
                    "decision": input["decision"], "reason": reason,
                })).map_err(|_| "invalid_request")?)
            } else {
                None
            };
            let result = view.control(Some(instance), |reply| match review {
                Some(review) => ControlCommand::SubmitInteractiveGoalReview {
                    session_id,
                    review,
                    reply,
                },
                None => ControlCommand::ReadInteractiveGoalReview {
                    session_id,
                    goal_id,
                    reply,
                },
            })?;
            Ok(json!(result))
        }
        "goal-progress" => {
            let instance = field(input, "serviceInstanceId")?;
            let execution_id = field(input, "executionId")?.to_owned();
            let result = view.control(Some(instance), |reply| {
                ControlCommand::ObserveGoalProgress {
                    session_id,
                    execution_id,
                    reply,
                }
            })?;
            Ok(json!(result))
        }
        "respond-interaction" => {
            let interaction_id = field(input, "interactionId")?.to_owned();
            let outcome =
                serde_json::from_value(input["outcome"].clone()).map_err(|_| "invalid_request")?;
            if field(input, "connectionEpoch")? != view.epoch.to_string() {
                return Ok(json!({"accepted": false, "reason": "stale_attachment"}));
            }
            let result = view.control(None, |reply| ControlCommand::RespondInteraction {
                session_id,
                interaction_id,
                outcome,
                reply,
            })?;
            match result {
                ControlResult::Accepted => Ok(json!({"accepted": true})),
                ControlResult::Rejected(reason) => Ok(json!({"accepted": false, "reason": reason})),
                _ => Err("invalid_host_reply".into()),
            }
        }
        "models" => models(view.control(None, |reply| ControlCommand::ListModels {
            session_id,
            reply,
        })?),
        "select-model" => {
            let model_id = field(input, "modelId")?.to_owned();
            let thinking_level = input["thinkingLevel"].as_str().map(str::to_owned);
            models(view.control(None, |reply| ControlCommand::SelectModel {
                session_id,
                model_id,
                thinking_level,
                reply,
            })?)
        }
        _ => Err("unknown_operation".into()),
    }
}

fn submission(view: &View, action: &str, session_id: String, input: &Value) -> Result<Value> {
    let id = field(input, "submissionId")?;
    let instance = input["serviceInstanceId"].as_str();
    let result = if action == "find-submission" {
        view.control(Some(instance.ok_or("invalid_request")?), |reply| {
            ControlCommand::FindSubmission {
                session_id,
                submission_id: id.to_owned(),
                reply,
            }
        })
    } else if action == "goal-start" {
        if !input.as_object().is_some_and(|fields| fields.len() == 3) {
            return Err("invalid_request".into());
        }
        view.control(Some(field(input, "serviceInstanceId")?), |reply| {
            ControlCommand::StartGoal {
                session_id,
                submission_id: id.to_owned(),
                reply,
            }
        })
    } else {
        let text = input["text"].as_str().ok_or("invalid_request")?.to_owned();
        let resource_refs = match input.get("resourceRefs") {
            Some(value) => value.as_array().ok_or("invalid_request")?.clone(),
            None => Vec::new(),
        };
        view.control(instance, |reply| ControlCommand::Submit {
            session_id,
            submission_id: id.to_owned(),
            text,
            resource_refs,
            reply,
        })
    };
    if matches!(action, "submit" | "goal-start") && result.is_err() {
        return Err("connection_failed".into());
    }
    Ok(submission_receipt(id, result))
}

fn submission_receipt(submission_id: &str, result: Result<ControlResult>) -> Value {
    match result {
        Ok(ControlResult::Submitted(id)) => {
            json!({"accepted": true, "submissionId": submission_id, "executionId": id})
        }
        Ok(ControlResult::Rejected(reason)) => {
            json!({"accepted": false, "submissionId": submission_id, "reason": reason})
        }
        _ => {
            json!({"accepted": false, "submissionId": submission_id, "reason": "submission_outcome_unknown"})
        }
    }
}

fn models(result: ModelControlResult) -> Result<Value> {
    match result {
        ModelControlResult::Accepted(value) => Ok(value),
        ModelControlResult::Rejected(code) => Err(code),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workspace_creation_checks_the_wire_shape_without_interpreting_host_paths() {
        for path in ["/home/project", r"C:\Work Space"] {
            assert_eq!(
                workspace_creation_path(&json!({"path": path})).unwrap(),
                path
            );
        }
        for path in ["relative", "C:relative", "/bad\0path", ""] {
            assert_eq!(
                workspace_creation_path(&json!({"path": path})).unwrap_err(),
                "invalid_request"
            );
        }
    }

    #[test]
    fn invalid_chat_titles_are_rejected_before_workspace_allocation() {
        let target = AppTarget::Local(std::path::Path::new("unconfigured"));
        for title in ["   ".to_owned(), "a".repeat(257)] {
            assert_eq!(
                create_chat(target, &json!({"title": title})),
                Err("invalid_request".into())
            );
        }
        assert_eq!(
            create_chat(target, &json!({"title": "a".repeat(256)})),
            Ok(json!({"accepted": false}))
        );
    }
}
