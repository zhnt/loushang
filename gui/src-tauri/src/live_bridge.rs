//! Tauri handoff for reconnecting snapshots, validated event rounds and bounded control.
use crate::app_client::{
    AppClient, ConnectionOptions, ControlCommand, ControlResult, LiveEventRound,
    LiveInitialSnapshot,
};
use crate::connection_lifecycle::{ConnectionLifecycle, ExitAction};
use serde::{Deserialize, Serialize};
use std::ffi::OsString;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Arc, RwLock};
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
    control: Arc<RwLock<Option<LiveControl>>>,
}

#[derive(Clone)]
struct LiveControl {
    connection_epoch: u64,
    sender: mpsc::Sender<ControlCommand>,
}

impl LiveLaunchState {
    pub(crate) fn from_process() -> Self {
        Self {
            launch: parse_launch(std::env::args_os().skip(1)),
            resync: Arc::new(AtomicU64::new(0)),
            control: Arc::new(RwLock::new(None)),
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ConnectionState {
    state: &'static str,
    connection_epoch: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LiveSubmitInput {
    session_id: String,
    submission_id: String,
    text: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LiveInterruptInput {
    session_id: String,
    execution_id: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LiveControlReceipt {
    accepted: bool,
    reason: Option<String>,
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
    let control = state.control.clone();
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
                let (control_sender, control_receiver) = mpsc::channel();
                *control.write().map_err(|_| ())? = None;
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
                        control_commands: Some(&control_receiver),
                    },
                    epoch,
                    &mut |snapshot| {
                        installed = true;
                        publish.send(Publication::Initial(snapshot)).map_err(|_| ())
                    },
                    &mut |round| publish.send(Publication::Round(round)).map_err(|_| ()),
                    &mut |authority| {
                        *control.write().map_err(|_| ())? = authority.map(|_| LiveControl {
                            connection_epoch: epoch,
                            sender: control_sender.clone(),
                        });
                        Ok(())
                    },
                    &mut || Ok(resync.load(Ordering::Acquire) == token),
                );
                *control.write().map_err(|_| ())? = None;
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
pub(crate) async fn live_submit_text(
    state: tauri::State<'_, LiveLaunchState>,
    input: LiveSubmitInput,
) -> Result<LiveControlReceipt, String> {
    let control = current_control(&state)?;
    let controls = state.control.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let recovery_session_id = input.session_id.clone();
        let recovery_submission_id = input.submission_id.clone();
        let (reply, receive) = mpsc::sync_channel(1);
        control
            .sender
            .send(ControlCommand::Submit {
                session_id: input.session_id,
                submission_id: input.submission_id,
                text: input.text,
                reply,
            })
            .map_err(|_| "live control connection changed".to_owned())?;
        let result = receive
            .recv_timeout(Duration::from_secs(6))
            .map_err(|_| "live submit response timed out".to_owned())?;
        match result {
            Ok(result) => control_receipt(Ok(result), true),
            Err(()) => {
                let recovered = wait_for_reconnected_control(&controls, control.connection_epoch)?;
                let (reply, receive) = mpsc::sync_channel(1);
                recovered
                    .sender
                    .send(ControlCommand::FindSubmission {
                        session_id: recovery_session_id,
                        submission_id: recovery_submission_id,
                        reply,
                    })
                    .map_err(|_| "live recovery connection changed".to_owned())?;
                let result = receive
                    .recv_timeout(Duration::from_secs(6))
                    .map_err(|_| "live submission recovery timed out".to_owned())?;
                control_receipt(result, true)
            }
        }
    })
    .await
    .map_err(|_| "live submit worker failed".to_owned())?
}

#[tauri::command]
pub(crate) async fn live_interrupt(
    state: tauri::State<'_, LiveLaunchState>,
    input: LiveInterruptInput,
) -> Result<LiveControlReceipt, String> {
    let control = current_control(&state)?;
    tauri::async_runtime::spawn_blocking(move || {
        let (reply, receive) = mpsc::sync_channel(1);
        control
            .sender
            .send(ControlCommand::Interrupt {
                session_id: input.session_id,
                execution_id: input.execution_id,
                reply,
            })
            .map_err(|_| "live control connection changed".to_owned())?;
        let result = receive
            .recv_timeout(Duration::from_secs(6))
            .map_err(|_| "live interrupt response timed out".to_owned())?;
        control_receipt(result, false)
    })
    .await
    .map_err(|_| "live interrupt worker failed".to_owned())?
}

fn current_control(state: &LiveLaunchState) -> Result<LiveControl, String> {
    let control = state
        .control
        .read()
        .map_err(|_| "live control state is unavailable".to_owned())?
        .clone()
        .ok_or_else(|| "live control is not attached".to_owned())?;
    let _epoch = control.connection_epoch;
    Ok(control)
}

fn wait_for_reconnected_control(
    controls: &Arc<RwLock<Option<LiveControl>>>,
    previous_epoch: u64,
) -> Result<LiveControl, String> {
    let deadline = std::time::Instant::now()
        .checked_add(Duration::from_secs(6))
        .ok_or_else(|| "live recovery deadline is unavailable".to_owned())?;
    loop {
        let current = controls
            .read()
            .map_err(|_| "live control state is unavailable".to_owned())?
            .clone();
        if let Some(control) = current {
            if control.connection_epoch > previous_epoch {
                return Ok(control);
            }
        }
        if std::time::Instant::now() >= deadline {
            return Err("live control did not reconnect for submission recovery".to_owned());
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

fn control_receipt(
    result: Result<ControlResult, ()>,
    submit: bool,
) -> Result<LiveControlReceipt, String> {
    match result {
        Ok(ControlResult::Accepted) => Ok(LiveControlReceipt {
            accepted: true,
            reason: None,
        }),
        Ok(ControlResult::Rejected(reason)) => Ok(LiveControlReceipt {
            accepted: false,
            reason: Some(reason),
        }),
        Ok(ControlResult::Missing) if submit => Ok(LiveControlReceipt {
            accepted: false,
            reason: Some("submission_outcome_unknown".to_owned()),
        }),
        Ok(ControlResult::Missing) => Err("interrupt result is missing".to_owned()),
        Err(()) => Err("live control request failed".to_owned()),
    }
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
    if let Ok(mut control) = app.state::<LiveLaunchState>().control.write() {
        *control = None;
    }
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
