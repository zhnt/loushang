//! Blocking, read-only AppHost adapter. The desktop owns its worker and stop.
mod attachment;
mod connection_epoch;
mod record_native;
mod request_deadline;
mod transport_auth;

use request_deadline::RequestDeadline;
use serde::{Deserialize, Serialize};
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, Shutdown, SocketAddr, TcpStream};
use std::path::Path;
use std::sync::mpsc::{self, Sender};
use std::thread::{self, JoinHandle};
use std::time::Duration;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LiveInitialSnapshot {
    pub(crate) service_instance_id: String,
    pub(crate) mux_space: serde_json::Value,
    pub(crate) sessions: Vec<serde_json::Value>,
}

struct DeadlineStream {
    stream: TcpStream,
    deadline: RequestDeadline,
}
impl Read for DeadlineStream {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        self.stream
            .set_read_timeout(Some(self.deadline.remaining()?))?;
        self.stream.read(buffer)
    }
}
impl Write for DeadlineStream {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        self.stream
            .set_write_timeout(Some(self.deadline.remaining()?))?;
        self.stream.write(buffer)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.stream.flush()
    }
}

struct CancelOwner {
    finish: Option<Sender<()>>,
    worker: Option<JoinHandle<()>>,
}
impl Drop for CancelOwner {
    fn drop(&mut self) {
        if let Some(finish) = self.finish.take() {
            let _ = finish.send(());
        }
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Hello {
    profile: String,
    protocol_version: String,
    execution_version: String,
    service_instance_id: String,
    submission_retention: String,
    restart_recovery: bool,
}

/// `publish` must only perform a bounded local handoff. It runs after the full
/// snapshot membership barrier and before ongoing reads become observable.
pub(crate) struct ConnectionOptions<'a> {
    pub(crate) root: &'a Path,
    pub(crate) timeout: Duration,
    pub(crate) cancel: Option<Duration>,
    pub(crate) attach: bool,
    pub(crate) mux_name: &'a str,
    pub(crate) stop: Option<super::read_stop::ReadStop>,
}

fn run_attempt(
    owner: &connection_epoch::ConnectionOwner,
    options: ConnectionOptions<'_>,
    publish: &mut dyn FnMut(LiveInitialSnapshot) -> Result<(), ()>,
) -> Result<String, ()> {
    let ConnectionOptions {
        root,
        timeout,
        cancel,
        attach,
        mux_name,
        stop,
    } = options;
    let deadline = RequestDeadline::new(timeout)?;
    let attempt = owner.begin()?;
    let name = transport_auth::record_value::Record::filename("workspace")?;
    let record = transport_auth::record_value::Record::decode(&record_native::read(root, &name)?)?;
    let profile = "local-detachable-execution/v1";
    record.selected("workspace", profile)?;
    if cancel == Some(Duration::ZERO) {
        return Err(());
    }
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, record.port()));
    let stream = TcpStream::connect_timeout(&address, deadline.remaining().map_err(|_| ())?)
        .map_err(|_| ())?;
    let (finish, receiver) = mpsc::channel();
    let worker = if let Some(delay) = cancel {
        let socket = stream.try_clone().map_err(|_| ())?;
        let fence = attempt.cancellation();
        let stop = stop.clone();
        Some(thread::spawn(move || {
            if receiver.recv_timeout(delay).is_err() {
                if let Some(stop) = stop {
                    stop.request();
                } else {
                    fence.invalidate();
                    let _ = socket.shutdown(Shutdown::Both);
                }
            }
        }))
    } else {
        None
    };
    let _cancel_owner = CancelOwner {
        finish: Some(finish),
        worker,
    };
    let reader = DeadlineStream {
        stream: stream.try_clone().map_err(|_| ())?,
        deadline: deadline.clone(),
    };
    let writer = DeadlineStream {
        stream: stream.try_clone().map_err(|_| ())?,
        deadline: deadline.clone(),
    };
    let mut channel = transport_auth::Channel::authenticate(
        transport_auth::Frames::new(reader, writer),
        &record,
    )?;
    let send_deadline = deadline.clone();
    channel.before_send(move || send_deadline.before_send());
    channel.send(b"app")?;
    let bytes = channel.receive()?;
    let hello: Hello = serde_json::from_slice(&bytes).map_err(|_| ())?;
    let instance = &hello.service_instance_id;
    if hello.profile != profile
        || hello.protocol_version != "loushang.app/v1"
        || hello.execution_version != "loushang.execution/v1"
        || hello.restart_recovery
        || hello.submission_retention != "service_instance_lifetime"
        || instance.is_empty()
        || instance.len() > 128
        || !instance.as_bytes()[0].is_ascii_alphanumeric()
        || !instance
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._~-".contains(&byte))
    {
        return Err(());
    }
    let canonical =
        serde_json::to_vec(&serde_json::to_value(&hello).map_err(|_| ())?).map_err(|_| ())?;
    if bytes != canonical {
        return Err(());
    }
    channel.send(&bytes)?;
    if attach {
        let mut session =
            attachment::ReadSession::attach(&mut channel, instance, mux_name, &attempt)?;
        let outcome = (|| {
            let initial = session.initialize(&mut channel, &attempt)?;
            attempt.apply(|| {
                publish(LiveInitialSnapshot {
                    service_instance_id: hello.service_instance_id.clone(),
                    mux_space: initial.mux_space,
                    sessions: initial.sessions,
                })
            })?;
            deadline.enter_session()?;
            if let Some(stop) = stop.as_ref() {
                while !stop.requested()? {
                    if !session.poll(&mut channel, &attempt, Some(stop))? {
                        break;
                    }
                    if stop.wait(Duration::from_millis(100))? {
                        break;
                    }
                }
            } else {
                for _ in 0..2 {
                    session.poll(&mut channel, &attempt, None)?;
                }
            }
            Ok(())
        })();
        let detached = session.detach(&mut channel, &attempt);
        outcome?;
        detached?;
    }
    stream.shutdown(Shutdown::Both).map_err(|_| ())?;
    attempt.apply(|| Ok(hello.service_instance_id))
}

#[derive(Default)]
pub(crate) struct AppClient(connection_epoch::ConnectionOwner);

impl AppClient {
    pub(crate) fn run(
        &self,
        options: ConnectionOptions<'_>,
        publish: &mut dyn FnMut(LiveInitialSnapshot) -> Result<(), ()>,
    ) -> Result<String, ()> {
        run_attempt(&self.0, options, publish)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn initial_snapshot_never_serializes_attachment_authority() {
        let value = serde_json::to_value(LiveInitialSnapshot {
            service_instance_id: "service-1".into(),
            mux_space: serde_json::json!({"muxSpaceId":"mux-1","members":[]}),
            sessions: vec![],
        })
        .unwrap();
        let text = value.to_string();
        assert!(!text.contains("attachmentId"));
        assert!(!text.contains("controllerGeneration"));
    }
}
