//! Rust client for the existing authenticated AppServer protocol.
mod app_client;
#[cfg(feature = "frontend")]
pub mod frontend;
pub mod read_stop;

pub use app_client::{
    AppClient, AppTarget, ConnectionOptions, ControlAuthority, ControlCommand, ControlResult,
    CreateSessionResult, LiveEventRound, LiveInitialSnapshot, MemberEvents, ModelControlResult,
    WorkspaceInfo, WorkspaceRequest, WorkspaceResult, WorkspaceScope,
};
