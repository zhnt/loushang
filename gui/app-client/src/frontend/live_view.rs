//! Shared AppClient attachment for active polling views of a workspace.
use super::{options, Result, TIMEOUT};
use crate::{
    read_stop::ReadStop, AppClient, AppTarget, ConnectionOptions, ControlCommand,
    LiveInitialSnapshot, WorkspaceInfo,
};
use serde_json::Value;
use std::{
    num::NonZeroU16,
    path::PathBuf,
    sync::{mpsc, Arc, Mutex},
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

pub(super) const LEASE: Duration = Duration::from_secs(8);

#[derive(Clone, PartialEq, Eq)]
pub(super) enum Target {
    Local(PathBuf),
    Tunnel(PathBuf, NonZeroU16),
}

impl From<AppTarget<'_>> for Target {
    fn from(value: AppTarget<'_>) -> Self {
        match value {
            AppTarget::Local(path) => Self::Local(path.to_owned()),
            AppTarget::Tunnel {
                credential_root,
                forwarded_port,
            } => Self::Tunnel(credential_root.to_owned(), forwarded_port),
        }
    }
}

impl Target {
    pub(super) fn borrow(&self) -> AppTarget<'_> {
        match self {
            Self::Local(root) => AppTarget::Local(root),
            Self::Tunnel(root, port) => AppTarget::Tunnel {
                credential_root: root,
                forwarded_port: *port,
            },
        }
    }
}

pub(super) struct View {
    pub(super) target: Target,
    pub(super) credential_binding: [u8; 32],
    pub(super) path: String,
    pub(super) mux: String,
    pub(super) epoch: u64,
    stop: ReadStop,
    worker: Option<JoinHandle<()>>,
    seen: Arc<Mutex<Instant>>,
    latest: Arc<Mutex<Option<LiveInitialSnapshot>>>,
    commands: mpsc::Sender<ControlCommand>,
}

impl View {
    pub(super) fn open(
        target: Target,
        path: String,
        workspace: Option<WorkspaceInfo>,
        mux: String,
        epoch: u64,
    ) -> Result<Self> {
        let credential_binding =
            AppClient::target_binding(target.borrow()).map_err(|_| "connection_failed")?;
        let (commands, receive) = mpsc::channel();
        let (ready, initialized) = mpsc::channel();
        let stop = ReadStop::default();
        let latest = Arc::new(Mutex::new(None::<LiveInitialSnapshot>));
        let seen = Arc::new(Mutex::new(Instant::now()));

        let (worker_target, worker_stop, worker_latest, worker_seen) =
            (target.clone(), stop.clone(), latest.clone(), seen.clone());
        let worker_mux = mux.clone();
        let worker = thread::Builder::new()
            .name("app-client-view".into())
            .spawn(move || {
                let client = AppClient::default();
                let connection = ConnectionOptions {
                    control_commands: Some(&receive),
                    stop: Some(worker_stop.clone()),
                    ..options(worker_target.borrow(), &worker_mux, workspace.as_ref())
                };
                let _ = client.run_stream(
                    connection,
                    epoch,
                    &mut |snapshot| {
                        *worker_seen.lock().map_err(|_| ())? = Instant::now();
                        *worker_latest.lock().map_err(|_| ())? = Some(snapshot);
                        ready.send(()).map_err(|_| ())
                    },
                    &mut |round| {
                        let mut published = worker_latest.lock().map_err(|_| ())?;
                        published.as_mut().ok_or(())?.sessions = round.sessions;
                        Ok(())
                    },
                    &mut |_| Ok(()),
                    &mut || Ok(worker_seen.lock().map_err(|_| ())?.elapsed() < LEASE),
                );
                worker_stop.request();
                if let Ok(mut published) = worker_latest.lock() {
                    *published = None;
                }
            })
            .map_err(|_| "host_unavailable")?;

        let view = Self {
            target,
            credential_binding,
            path,
            mux,
            epoch,
            stop,
            worker: Some(worker),
            seen,
            latest,
            commands,
        };
        initialized
            .recv_timeout(TIMEOUT)
            .map_err(|_| "connection_failed")?;
        if AppClient::target_binding(view.target.borrow()).ok() != Some(view.credential_binding) {
            return Err("connection_failed".into());
        }
        Ok(view)
    }

    pub(super) fn active(&self) -> bool {
        self.stop.requested() == Ok(false)
            && self.seen.lock().is_ok_and(|seen| seen.elapsed() < LEASE)
    }

    pub(super) fn snapshot(&self) -> Result<Value> {
        let mut seen = self.seen.lock().map_err(|_| "connection_failed")?;
        if seen.elapsed() >= LEASE || self.stop.requested() != Ok(false) {
            return Err("connection_failed".into());
        }
        let snapshot = self.latest.lock().map_err(|_| "connection_failed")?;
        let value = snapshot.as_ref().ok_or("connection_failed")?;
        *seen = Instant::now();
        serde_json::to_value(value).map_err(|_| "invalid_host_reply".into())
    }

    pub(super) fn control<T>(
        &self,
        expected_instance: Option<&str>,
        build: impl FnOnce(mpsc::SyncSender<std::result::Result<T, ()>>) -> ControlCommand,
    ) -> Result<T> {
        if !self.active() {
            return Err("connection_failed".into());
        }
        let snapshot = self.latest.lock().map_err(|_| "connection_failed")?;
        let actual = &snapshot
            .as_ref()
            .ok_or("connection_failed")?
            .service_instance_id;
        if expected_instance.is_some_and(|expected| expected != actual) {
            return Err("instance_changed".into());
        }
        drop(snapshot);
        let (reply, result) = mpsc::sync_channel(1);
        self.commands
            .send(build(reply))
            .map_err(|_| "connection_failed")?;
        result
            .recv_timeout(TIMEOUT)
            .map_err(|_| "connection_failed")?
            .map_err(|_| "connection_failed".into())
    }
}

impl Drop for View {
    fn drop(&mut self) {
        self.stop.request();
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}
