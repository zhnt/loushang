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
    Register(&'a str),
    Open(&'a str),
    Unregister(&'a str),
    AllocateTemporary,
}

impl<'a> WorkspaceRequest<'a> {
    fn wire_fields(self) -> (&'static str, Option<&'a str>) {
        match self {
            Self::List => ("list", None),
            Self::Projects => ("projects", None),
            Self::Register(path) => ("register", Some(path)),
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
    let (action, path) = operation.wire_fields();
    let response = request(
        channel,
        "workspace/request",
        "1",
        json!({"action": action, "path": path}),
    )?;
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
