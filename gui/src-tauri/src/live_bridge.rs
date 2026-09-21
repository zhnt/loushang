//! Tauri handoff for the first read-only snapshot. Launch facts stay native.
use crate::app_client::{AppClient, ConnectionOptions, LiveInitialSnapshot};
use crate::connection_lifecycle::ConnectionLifecycle;
use crate::connection_lifecycle::ExitAction;
use std::ffi::OsString;
use std::path::PathBuf;
use std::sync::{mpsc, Arc};
use std::time::Duration;
use tauri::{Emitter, Manager};

const INITIAL_EVENT: &str = "gui://live-initial-snapshot";
const FAILURE_EVENT: &str = "gui://live-connection-failed";

#[derive(Clone)]
struct LiveLaunch {
    record_root: PathBuf,
    mux_name: String,
}

pub(crate) struct LiveLaunchState(Result<Option<LiveLaunch>, ()>);

impl LiveLaunchState {
    pub(crate) fn from_process() -> Self {
        Self(parse_launch(std::env::args_os().skip(1)))
    }
}

#[tauri::command]
pub(crate) fn live_readonly_available(app: tauri::AppHandle) -> bool {
    matches!(app.state::<LiveLaunchState>().0, Ok(Some(_)))
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
    let launch = app
        .state::<LiveLaunchState>()
        .0
        .as_ref()
        .map_err(|_| "invalid native launch configuration".to_owned())?
        .clone()
        .ok_or_else(|| "live AppHost launch configuration is unavailable".to_owned())?;
    let owner = app.state::<Arc<ConnectionLifecycle>>().inner().clone();
    let (publish, receive) = mpsc::channel::<Result<LiveInitialSnapshot, ()>>();
    owner
        .start(move |stop| {
            let mut sent = false;
            let outcome = AppClient::default().run(
                ConnectionOptions {
                    root: &launch.record_root,
                    timeout: Duration::from_secs(5),
                    cancel: None,
                    attach: true,
                    mux_name: &launch.mux_name,
                    stop: Some(stop),
                },
                &mut |snapshot| {
                    publish.send(Ok(snapshot)).map_err(|_| ())?;
                    sent = true;
                    Ok(())
                },
            );
            if outcome.is_err() && !sent {
                let _ = publish.send(Err(()));
            }
            outcome.map(|_| ())
        })
        .map_err(|_| "live connection is already running or closing".to_owned())?;

    tauri::async_runtime::spawn_blocking(move || {
        match receive.recv_timeout(Duration::from_secs(6)) {
            Ok(Ok(snapshot)) => {
                let _ = app.emit(INITIAL_EVENT, snapshot);
            }
            Ok(Err(())) | Err(_) => {
                let _ = app.emit(FAILURE_EVENT, ());
            }
        }
    });
    Ok(())
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
