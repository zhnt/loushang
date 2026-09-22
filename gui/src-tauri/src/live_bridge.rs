//! Tauri handoff for reconnecting read-only snapshots and validated event rounds.
use crate::app_client::{AppClient, ConnectionOptions, LiveEventRound, LiveInitialSnapshot};
use crate::connection_lifecycle::{ConnectionLifecycle, ExitAction};
use serde::Serialize;
use std::ffi::OsString;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Arc};
use std::time::Duration;
use tauri::{Emitter, Manager};

const INITIAL_EVENT: &str = "gui://live-initial-snapshot";
const ROUND_EVENT: &str = "gui://live-event-round";
const STATE_EVENT: &str = "gui://live-connection-state";
const FAILURE_EVENT: &str = "gui://live-connection-failed";

#[derive(Clone)]
struct LiveLaunch {
    record_root: PathBuf,
    mux_name: String,
}

pub(crate) struct LiveLaunchState {
    launch: Result<Option<LiveLaunch>, ()>,
    resync: Arc<AtomicU64>,
}

impl LiveLaunchState {
    pub(crate) fn from_process() -> Self {
        Self {
            launch: parse_launch(std::env::args_os().skip(1)),
            resync: Arc::new(AtomicU64::new(0)),
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ConnectionState {
    state: &'static str,
    connection_epoch: String,
}

enum Publication {
    Initial(LiveInitialSnapshot),
    Round(LiveEventRound),
    State(ConnectionState),
}

#[tauri::command]
pub(crate) fn live_readonly_available(app: tauri::AppHandle) -> bool {
    matches!(app.state::<LiveLaunchState>().launch, Ok(Some(_)))
}

fn parse_launch(arguments: impl IntoIterator<Item = OsString>) -> Result<Option<LiveLaunch>, ()> {
    let mut arguments = arguments.into_iter();
    let mut record_root = None;
    let mut mux_name = None;
    while let Some(flag) = arguments.next() {
        let value = arguments.next().ok_or(())?;
        match flag.to_str().ok_or(())? {
            "--loushang-app-record-root" if record_root.is_none() => {
                record_root = Some(PathBuf::from(value));
            }
            "--loushang-mux-name" if mux_name.is_none() => {
                let value = value.into_string().map_err(|_| ())?;
                if value.trim().is_empty() || value.chars().count() > 256 {
                    return Err(());
                }
                mux_name = Some(value);
            }
            _ => return Err(()),
        }
    }
    match (record_root, mux_name) {
        (None, None) => Ok(None),
        (Some(record_root), Some(mux_name)) => Ok(Some(LiveLaunch {
            record_root,
            mux_name,
        })),
        _ => Err(()),
    }
}

#[tauri::command]
pub(crate) fn start_live_readonly(app: tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<LiveLaunchState>();
    let launch = state
        .launch
        .as_ref()
        .map_err(|_| "invalid native launch configuration".to_owned())?
        .clone()
        .ok_or_else(|| "live AppHost launch configuration is unavailable".to_owned())?;
    let resync = state.resync.clone();
    let owner = app.state::<Arc<ConnectionLifecycle>>().inner().clone();
    let (publish, receive) = mpsc::channel::<Publication>();
    owner
        .start(move |stop| {
            let client = AppClient::default();
            let mut epoch = 0_u64;
            let mut backoff = Duration::from_millis(250);
            while !stop.requested()? {
                epoch = epoch.checked_add(1).ok_or(())?;
                let token = resync.load(Ordering::Acquire);
                publish
                    .send(Publication::State(ConnectionState {
                        state: "connecting",
                        connection_epoch: epoch.to_string(),
                    }))
                    .map_err(|_| ())?;
                let mut installed = false;
                let outcome = client.run_stream(
                    ConnectionOptions {
                        root: &launch.record_root,
                        timeout: Duration::from_secs(5),
                        cancel: None,
                        attach: true,
                        mux_name: &launch.mux_name,
                        stop: Some(stop.clone()),
                    },
                    epoch,
                    &mut |snapshot| {
                        installed = true;
                        publish.send(Publication::Initial(snapshot)).map_err(|_| ())
                    },
                    &mut |round| publish.send(Publication::Round(round)).map_err(|_| ()),
                    &mut || Ok(resync.load(Ordering::Acquire) == token),
                );
                if stop.requested()? {
                    break;
                }
                publish
                    .send(Publication::State(ConnectionState {
                        state: "disconnected",
                        connection_epoch: epoch.to_string(),
                    }))
                    .map_err(|_| ())?;
                if outcome.is_ok() || installed || resync.load(Ordering::Acquire) != token {
                    backoff = Duration::from_millis(250);
                } else {
                    backoff = (backoff * 2).min(Duration::from_secs(2));
                }
                if stop.wait(backoff)? {
                    break;
                }
            }
            Ok(())
        })
        .map_err(|_| "live connection is already running or closing".to_owned())?;

    tauri::async_runtime::spawn_blocking(move || {
        while let Ok(publication) = receive.recv() {
            let emitted = match publication {
                Publication::Initial(snapshot) => app.emit(INITIAL_EVENT, snapshot),
                Publication::Round(round) => app.emit(ROUND_EVENT, round),
                Publication::State(state) => app.emit(STATE_EVENT, state),
            };
            if emitted.is_err() {
                let _ = app.emit(FAILURE_EVENT, ());
                break;
            }
        }
    });
    Ok(())
}

#[tauri::command]
pub(crate) fn resync_live_readonly(app: tauri::AppHandle) -> Result<(), String> {
    app.state::<LiveLaunchState>()
        .resync
        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
            value.checked_add(1)
        })
        .map(|_| ())
        .map_err(|_| "live resynchronization counter exhausted".to_owned())
}

#[tauri::command]
pub(crate) fn stop_live_readonly(app: tauri::AppHandle) {
    let owner = app.state::<Arc<ConnectionLifecycle>>().inner().clone();
    if let ExitAction::Join(worker) = owner.begin_exit() {
        tauri::async_runtime::spawn_blocking(move || owner.finish_exit(worker.wait()));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn launch_is_all_or_nothing_and_rejects_duplicates() {
        assert!(parse_launch(Vec::<OsString>::new()).unwrap().is_none());
        assert!(
            parse_launch(["--loushang-app-record-root", "C:\\records"].map(Into::into)).is_err()
        );
        assert!(parse_launch(
            [
                "--loushang-app-record-root",
                "C:\\records",
                "--loushang-mux-name",
                "gui"
            ]
            .map(Into::into)
        )
        .unwrap()
        .is_some());
        assert!(parse_launch(
            ["--loushang-mux-name", "a", "--loushang-mux-name", "b"].map(Into::into)
        )
        .is_err());
    }
}
