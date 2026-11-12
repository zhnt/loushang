//! Browser and desktop requests use the same AppServer client.
mod service;
use crate::{
    AppClient, AppTarget, ConnectionOptions, ControlCommand, ControlResult, CreateSessionResult,
    ModelControlResult, WorkspaceInfo, WorkspaceRequest, WorkspaceResult,
};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
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
    manager: Option<PathBuf>,
    managed_record: Arc<Mutex<Option<PathBuf>>>,
}

impl Backend {
    pub fn new(root: PathBuf) -> Self {
        Self {
            root,
            tunnel: None,
            requests: Arc::new(Mutex::new(())),
            manager: None,
            managed_record: Arc::new(Mutex::new(None)),
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
            manager: None,
            managed_record: Arc::new(Mutex::new(None)),
        }
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

    fn host_request(&self, operation: &str, request: &Value) -> Result<Value> {
        let configured_record = if self.tunnel.is_none() { self.record_root()? } else { None };
        let manager = self.manager.as_deref().filter(|_| configured_record.is_none());
        if let (Some(manager), "manage") = (manager, operation) {
            return self.manage_service(manager, request);
        }
        let record_root;
        let target = if let Some((credential_root, forwarded_port)) = &self.tunnel {
            Some(AppTarget::Tunnel {
                credential_root,
                forwarded_port: *forwarded_port,
            })
        } else {
            record_root = match configured_record {
                Some(path) => Some(path),
                None => self.managed_record.lock().map_err(|_| "host_unavailable")?.clone(),
            };
            record_root.as_deref().map(AppTarget::Local)
        };
        match operation {
            "environment" => Ok(json!({
                "supported": target.is_some() || manager.is_some(),
                "manageable": manager.is_some(), "workspace": self.last_workspace()?,
            })),
            "manage" => status(target, field(request, "action")?),
            "workspace" => self.workspace(target.ok_or("not_connected")?, request),
            "live" => live_request(target.ok_or("not_connected")?, request),
            _ => Err("unknown_operation".into()),
        }
    }


    fn manage_service(&self, manager: &std::path::Path, request: &Value) -> Result<Value> {
        let (action, instance) = match field(request, "action")? {
            "status" | "connect" => ("status", None),
            "start" => ("start", None),
            action @ ("stop" | "restart") => {
                let instance = field(request, "instanceId")?;
                if instance.len() != 32 || !instance.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
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
            if !matches!(reply.state.as_str(), "not_running" | "starting" | "stopping" | "exited" | "unknown") {
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
        if reply.service_instance_id.is_some_and(|expected| expected != service_instance) {
            return Ok(error("instance_changed"));
        }
        *self.managed_record.lock().map_err(|_| "host_unavailable")? = Some(root);
        Ok(json!({"state":"running", "errorCode":null, "manageable":true,
                  "instanceId":reply.instance_id, "serviceInstanceId":service_instance}))
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
            "open" => return self.open(target, field(request, "path")?),
            "list" => WorkspaceRequest::List,
            "register" => WorkspaceRequest::Register(field(request, "path")?),
            "unregister" => WorkspaceRequest::Unregister(field(request, "path")?),
            _ => return Err("unknown_operation".into()),
        };
        Ok(json!({"workspaces": workspaces(target, operation)?}))
    }

    fn open(&self, target: AppTarget<'_>, path: &str) -> Result<Value> {
        let opened = open_workspace(target, path)?;
        let mux = mux_name(&opened.path);
        let mut connection = options(target, &mux, Some(&opened));
        connection.prepare_default_session = true;
        AppClient::default()
            .run(connection, &mut |_| Ok(()))
            .map_err(|_| "connection_failed")?;
        self.set_last_workspace(&opened.path)?;
        Ok(json!({"workspaces": [opened]}))
    }

    fn navigation(&self, target: AppTarget<'_>) -> Result<Value> {
        let projects = workspaces(target, WorkspaceRequest::Projects)?;
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
            let mut result = mux["members"].as_array().ok_or("invalid_host_reply")?.iter().map(|member| {
                let id = field(&member["session"], "sessionId")?;
                Ok(json!({"id": id, "title": member["title"], "scope": scope, "pinned": pinned.iter().any(|value| value == id)}))
            }).collect::<Result<Vec<_>>>()?;
            result.sort_by_key(|chat| chat["pinned"] != true);
            Ok(result)
        };
        let projects = projects
            .iter()
            .map(|item| Ok(json!({"path": item.path, "sessions": chats(&mux_name(&item.path))?})))
            .collect::<Result<Vec<_>>>()?;
        Ok(json!({"projects": projects, "temporarySessions": chats(TEMPORARY_MUX)?}))
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

fn open_workspace(target: AppTarget<'_>, path: &str) -> Result<WorkspaceInfo> {
    single(workspaces(target, WorkspaceRequest::Open(path))?)
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

fn create(
    target: AppTarget<'_>,
    mux: &str,
    workspace: Option<&WorkspaceInfo>,
    input: &Value,
) -> Result<Value> {
    let title = field(input, "title")?.to_owned();
    let mut entropy = [0_u8; 16];
    getrandom::getrandom(&mut entropy).map_err(|_| "host_unavailable")?;
    let continuity_id = entropy.iter().map(|byte| format!("{byte:02x}")).collect();
    let source_session_id = input["sourceSessionId"].as_str().map(str::to_owned);
    match control(options(target, mux, workspace), |reply| {
        ControlCommand::CreateSession {
            source_session_id,
            continuity_id,
            title,
            reply,
        }
    })? {
        CreateSessionResult::Accepted(session_id) => {
            Ok(json!({"sessionId":session_id, "accepted":true}))
        }
        CreateSessionResult::Rejected(code) => Err(code),
    }
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
    let (path, mux, scope) = match request.get("path").filter(|path| !path.is_null()) {
        Some(path) => {
            let workspace = open_workspace(target, path.as_str().ok_or("invalid_request")?)?;
            (workspace.path.clone(), mux_name(&workspace.path), workspace)
        }
        None => {
            let scope = single(workspaces(target, WorkspaceRequest::AllocateTemporary)?)?;
            (TEMPORARY.into(), TEMPORARY_MUX.into(), scope)
        }
    };
    let result = create(target, &mux, Some(&scope), &json!({"title": title}))?;
    Ok(json!({"workspace": path, "sessionId": result["sessionId"]}))
}

fn live_request(target: AppTarget<'_>, request: &Value) -> Result<Value> {
    let path = field(request, "workspace")?;
    let workspace = if path == TEMPORARY {
        None
    } else {
        Some(open_workspace(target, path)?)
    };
    live(
        target,
        workspace.as_ref(),
        field(request, "action")?,
        &request["input"],
    )
}

fn live(
    target: AppTarget<'_>,
    workspace: Option<&WorkspaceInfo>,
    action: &str,
    input: &Value,
) -> Result<Value> {
    let mux = workspace
        .map(|item| mux_name(&item.path))
        .unwrap_or_else(|| TEMPORARY_MUX.into());
    let options = options(target, &mux, workspace);
    match action {
        "snapshot" => snapshot(options),
        "create" => create(target, &mux, workspace, input),
        _ => session_control(options, action, input),
    }
}

fn snapshot(options: ConnectionOptions<'_>) -> Result<Value> {
    let mut snapshot = None;
    AppClient::default()
        .run(options, &mut |value| {
            snapshot = Some(value);
            Ok(())
        })
        .map_err(|_| "connection_failed")?;
    serde_json::to_value(snapshot.ok_or("connection_failed")?)
        .map_err(|_| "invalid_host_reply".into())
}

fn session_control(options: ConnectionOptions<'_>, action: &str, input: &Value) -> Result<Value> {
    let session_id = field(input, "sessionId")?.to_owned();
    match action {
        "submit" => submit(options, session_id, input),
        "find-submission" => {
            let submission_id = field(input, "submissionId")?;
            let instance = field(input, "serviceInstanceId")?;
            Ok(submission_receipt(
                submission_id,
                find_submission(options, &session_id, submission_id, instance),
            ))
        }
        "interrupt" => {
            let execution_id = field(input, "executionId")?.to_owned();
            let result = control(options, |reply| ControlCommand::Interrupt {
                session_id,
                execution_id,
                reply,
            })?;
            Ok(json!({"accepted": matches!(result, ControlResult::Accepted)}))
        }
        "models" => models(control(options, |reply| ControlCommand::ListModels {
            session_id,
            reply,
        })?),
        "select-model" => {
            let model_id = field(input, "modelId")?.to_owned();
            let thinking_level = input["thinkingLevel"].as_str().map(str::to_owned);
            models(control(options, |reply| ControlCommand::SelectModel {
                session_id,
                model_id,
                thinking_level,
                reply,
            })?)
        }
        _ => Err("unknown_operation".into()),
    }
}

fn submit(options: ConnectionOptions<'_>, session_id: String, input: &Value) -> Result<Value> {
    let submission_id = field(input, "submissionId")?.to_owned();
    let text = field(input, "text")?.to_owned();
    let expected_instance = input["serviceInstanceId"].as_str();
    let mut instance = None;
    let mut result = control_on(options.clone(), expected_instance, &mut instance, |reply| {
        ControlCommand::Submit {
            session_id: session_id.clone(),
            submission_id: submission_id.clone(),
            text,
            reply,
        }
    });
    if let (Err(_), Some(instance)) = (&result, instance) {
        result = find_submission(options, &session_id, &submission_id, &instance);
    }
    Ok(submission_receipt(&submission_id, result))
}

fn find_submission(
    options: ConnectionOptions<'_>,
    session_id: &str,
    submission_id: &str,
    instance: &str,
) -> Result<ControlResult> {
    control_on(options, Some(instance), &mut None, |reply| {
        ControlCommand::FindSubmission {
            session_id: session_id.to_owned(),
            submission_id: submission_id.to_owned(),
            reply,
        }
    })
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
            Err("connection_failed".into())
        );
    }
}
