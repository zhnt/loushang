//! Workspace operations over the existing AppServer message stream.
use super::attachment::{decode_app_error, request};
use super::transport_auth::Channel;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::BTreeSet;
use std::io::{Read, Write};

/// Workspace paths are interpreted by the connected AppHost.
pub enum WorkspaceRequest<'a> {
    List,
    Projects,
    Create(&'a str),
    Register(&'a str),
    Open(&'a str),
    Inspect {
        path: &'a str,
        session: Option<&'a str>,
    },
    Unregister(&'a str),
    AllocateTemporary,
}

impl<'a> WorkspaceRequest<'a> {
    fn wire_fields(self) -> (&'static str, Option<&'a str>) {
        match self {
            Self::List => ("list", None),
            Self::Projects => ("projects", None),
            Self::Create(path) => ("create", Some(path)),
            Self::Register(path) => ("register", Some(path)),
            Self::Inspect { path, .. } => ("inspect", Some(path)),
            Self::Open(path) => ("open", Some(path)),
            Self::Unregister(path) => ("unregister", Some(path)),
            Self::AllocateTemporary => ("allocate-temporary", None),
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkspaceScope {
    Cwd,
    UserHome,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WorkspaceInfo {
    pub path: String,
    pub scope: WorkspaceScope,
    pub scope_fingerprint: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub inspection: Option<WorkspaceInspection>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WorkspaceInspection {
    git: Option<GitInspection>,
    changes: Vec<GitChange>,
    toolchains: Vec<Toolchain>,
    limited: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    staged_diff: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    unstaged_diff: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    session_changes: Option<Vec<SessionChange>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    session_diff: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct GitInspection {
    root: String,
    branch: String,
    commit: String,
    worktree: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct GitChange {
    path: String,
    kind: ChangeKind,
    added: Option<u32>,
    removed: Option<u32>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum ChangeKind {
    Staged,
    Unstaged,
    Untracked,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SessionChange {
    path: String,
    created: bool,
    added: Option<u32>,
    removed: Option<u32>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Toolchain {
    name: String,
    declared: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    detected: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    environment: Option<String>,
}

pub enum WorkspaceResult {
    Accepted(Vec<WorkspaceInfo>),
    Rejected(String),
}

impl WorkspaceInfo {
    fn is_valid(&self) -> bool {
        !self.path.is_empty()
            && self.path.chars().count() <= 4096
            && !self.path.contains('\0')
            && self.scope_fingerprint.len() == 64
            && self
                .scope_fingerprint
                .bytes()
                .all(|value| value.is_ascii_digit() || (b'a'..=b'f').contains(&value))
    }
}

pub(super) fn workspace_request<R: Read, W: Write>(
    channel: &mut Channel<R, W>,
    operation: WorkspaceRequest<'_>,
) -> Result<WorkspaceResult, ()> {
    let mut fields = match &operation {
        WorkspaceRequest::Inspect {
            session: Some(session),
            ..
        } => json!({"sessionId": session}),
        _ => json!({}),
    };
    let (action, path) = operation.wire_fields();
    fields["action"] = json!(action);
    fields["path"] = json!(path);
    let response = request(channel, "workspace/request", "1", fields)?;
    if let Some(code) = decode_app_error(&response.result_type, &response.result)? {
        return Ok(WorkspaceResult::Rejected(code));
    }
    if response.result_type != "workspaces" {
        return Err(());
    }
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Directory {
        workspaces: Vec<WorkspaceInfo>,
    }
    let directory: Directory = serde_json::from_str(response.result.get()).map_err(|_| ())?;
    let mut paths = BTreeSet::new();
    if directory.workspaces.len() > 128
        || !directory
            .workspaces
            .iter()
            .all(|workspace| workspace.is_valid() && paths.insert(&workspace.path))
    {
        return Err(());
    }
    Ok(WorkspaceResult::Accepted(directory.workspaces))
}
