//! Workspace operations over the existing AppServer message stream.
use super::attachment::{decode_app_error, request};
use super::transport_auth::Channel;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
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
    Preview {
        path: &'a str,
        instance: &'a str,
        reference: &'a str,
        base: &'a str,
        fingerprint: &'a str,
    },
    LogicalPreview {
        workspace_id: &'a str,
        instance: &'a str,
        reference: &'a str,
        base: &'a str,
        fingerprint: &'a str,
    },
    Unregister(&'a str),
    Logical {
        action: &'a str,
        path: Option<&'a str>,
        fields: Value,
    },
}

impl<'a> WorkspaceRequest<'a> {
    fn wire_fields(self) -> (&'a str, Option<&'a str>) {
        match self {
            Self::List => ("list", None),
            Self::Projects => ("projects", None),
            Self::Create(path) => ("create", Some(path)),
            Self::Register(path) => ("register", Some(path)),
            Self::Inspect { path, .. } => ("inspect", Some(path)),
            Self::Open(path) => ("open", Some(path)),
            Self::Preview { path, .. } => ("preview", Some(path)),
            Self::LogicalPreview { .. } => ("preview-workspace", None),
            Self::Unregister(path) => ("unregister", Some(path)),
            Self::Logical { action, path, .. } => (action, path),
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
    pub workspace: Option<LogicalWorkspace>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub inspection: Option<WorkspaceInspection>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub preview: Option<WorkspacePreview>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LogicalWorkspace {
    pub id: String,
    pub name: String,
    pub paths: Vec<WorkspacePath>,
    pub default_path_id: Option<String>,
    pub default: bool,
    pub mux_name: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WorkspacePath {
    pub id: String,
    pub alias: String,
    pub path: String,
    pub status: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum WorkspacePreview {
    File {
        path: String,
        text: String,
    },
    Directory {
        path: String,
        entries: Vec<WorkspacePreviewEntry>,
        limited: bool,
    },
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkspacePreviewEntry {
    name: String,
    kind: WorkspaceEntryKind,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum WorkspaceEntryKind {
    File,
    Directory,
}

impl WorkspacePreview {
    fn is_valid(&self) -> bool {
        let path = match self {
            Self::File { path, text } if text.len() <= 128 * 1024 => path,
            Self::Directory { path, entries, .. }
                if entries.len() <= 128
                    && entries.iter().all(|entry| {
                        valid_relative(&entry.name, 255)
                            && !entry.name.contains('/')
                            && !matches!(entry.name.as_str(), "." | "..")
                    }) =>
            {
                path
            }
            _ => return false,
        };
        valid_relative(path, 4096)
    }
}

fn valid_relative(path: &str, limit: usize) -> bool {
    !path.is_empty()
        && path.chars().count() <= limit
        && !path.starts_with('/')
        && !path.contains(['\\', ':'])
        && !path.chars().any(char::is_control)
        && !path.split('/').any(|component| component == "..")
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
            && self.preview.as_ref().is_none_or(WorkspacePreview::is_valid)
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
        WorkspaceRequest::Preview {
            reference,
            base,
            fingerprint,
            ..
        } => {
            json!({"preview":{"reference": reference, "base": base, "scopeFingerprint": fingerprint}})
        }
        WorkspaceRequest::LogicalPreview {
            workspace_id,
            reference,
            base,
            fingerprint,
            ..
        } => {
            json!({"workspaceId": workspace_id,
                   "preview":{"reference": reference, "base": base, "scopeFingerprint": fingerprint}})
        }
        WorkspaceRequest::Logical { fields, .. } => fields.clone(),
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
    if directory.workspaces.len() > 129
        || !directory
            .workspaces
            .iter()
            .all(|workspace| workspace.is_valid() && paths.insert(&workspace.path))
    {
        return Err(());
    }
    Ok(WorkspaceResult::Accepted(directory.workspaces))
}
