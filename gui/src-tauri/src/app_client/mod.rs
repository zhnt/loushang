//! Blocking, read-only AppHost adapter. The desktop owns its worker and stop.
mod attachment;
mod connection_epoch;
#[cfg(not(target_os = "linux"))]
mod record_native;
#[cfg(target_os = "linux")]
#[path = "record_linux.rs"]
mod record_native;
mod request_deadline;
mod transport_auth;
pub(crate) use attachment::{
    ControlAuthority, ControlResult, CreateSessionResult, ModelControlResult,
};

use request_deadline::RequestDeadline;
use serde::{Deserialize, Serialize};
use std::cell::Cell;
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, Shutdown, SocketAddr, TcpStream};
use std::path::Path;
use std::sync::mpsc::{self, Receiver, Sender, SyncSender, TryRecvError};
use std::thread::{self, JoinHandle};
use std::time::Duration;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LiveInitialSnapshot {
    pub(crate) connection_epoch: String,
    pub(crate) service_instance_id: String,
    pub(crate) mux_space: serde_json::Value,
    pub(crate) sessions: Vec<serde_json::Value>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LiveEventRound {
    pub(crate) connection_epoch: String,
    pub(crate) sequence: String,
    pub(crate) service_instance_id: String,
    pub(crate) mux_space_id: serde_json::Value,
    pub(crate) members: Vec<attachment::MemberEvents>,
    pub(crate) sessions: Vec<serde_json::Value>,
}

pub(crate) enum ControlCommand {
    CreateSession {
        source_session_id: Option<String>,
        continuity_id: String,
        title: String,
        reply: SyncSender<Result<CreateSessionResult, ()>>,
    },
    Submit {
        session_id: String,
        submission_id: String,
        text: String,
        reply: SyncSender<Result<ControlResult, ()>>,
    },
    FindSubmission {
        session_id: String,
        submission_id: String,
        reply: SyncSender<Result<ControlResult, ()>>,
    },
    Interrupt {
        session_id: String,
        execution_id: String,
        reply: SyncSender<Result<ControlResult, ()>>,
    },
    ListModels {
        session_id: String,
        reply: SyncSender<Result<ModelControlResult, ()>>,
    },
    SelectModel {
        session_id: String,
        model_id: String,
        reply: SyncSender<Result<ModelControlResult, ()>>,
    },
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

fn validate_hello(bytes: &[u8], profile: &str) -> Result<Hello, ()> {
    let hello: Hello = serde_json::from_slice(bytes).map_err(|_| ())?;
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
    Ok(hello)
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
    pub(crate) prepare_default_session: bool,
    pub(crate) mux_name: &'a str,
    pub(crate) stop: Option<super::read_stop::ReadStop>,
    pub(crate) control_commands: Option<&'a Receiver<ControlCommand>>,
}

fn run_attempt(
    client: &AppClient,
    options: ConnectionOptions<'_>,
    connection_epoch: u64,
    publish_initial: &mut dyn FnMut(LiveInitialSnapshot) -> Result<(), ()>,
    publish_round: &mut dyn FnMut(LiveEventRound) -> Result<(), ()>,
    publish_control: &mut dyn FnMut(Option<attachment::ControlAuthority>) -> Result<(), ()>,
    continue_reading: &mut dyn FnMut() -> Result<bool, ()>,
) -> Result<String, ()> {
    let owner = &client.0;
    client.1.set("record_invalid");
    let ConnectionOptions {
        root,
        timeout,
        cancel,
        attach,
        prepare_default_session,
        mux_name,
        stop,
        control_commands,
    } = options;
    let deadline = RequestDeadline::new(timeout)?;
    let attempt = owner.begin()?;
    let name = transport_auth::record_value::Record::filename("workspace")?;
    let record = transport_auth::record_value::Record::decode(&record_native::read(root, &name)?)?;
    client.1.set("protocol_incompatible");
    let profile = record.semantic_profile()?;
    record.selected("workspace", &profile)?;
    if !record.supports_execution() {
        return Err(());
    }
    if cancel == Some(Duration::ZERO) {
        return Err(());
    }
    client.1.set("connection_failed");
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
    client.1.set("authentication_failed");
    let mut channel = transport_auth::Channel::authenticate(
        transport_auth::Frames::new(reader, writer),
        &record,
    )?;
    let send_deadline = deadline.clone();
    channel.before_send(move || send_deadline.before_send());
    client.1.set("connection_failed");
    channel.send(b"app")?;
    let bytes = channel.receive()?;
    client.1.set("protocol_incompatible");
    let hello = validate_hello(&bytes, &profile)?;
    let instance = &hello.service_instance_id;
    channel.send(&bytes)?;
    if attach {
        client.1.set("attachment_unavailable");
        let mut session =
            attachment::ReadSession::attach(&mut channel, instance, mux_name, &attempt, &record)?;
        let outcome = (|| {
            if prepare_default_session {
                session.ensure_default(&mut channel, &attempt)?;
            }
            let initial = session.initialize(&mut channel, &attempt)?;
            let authority = session.control_authority()?;
            let control_authority = authority.clone();
            let mux_space_id = initial.mux_space["muxSpaceId"].clone();
            attempt.apply(|| publish_control(Some(authority)))?;
            if let Some(commands) = control_commands {
                process_controls(&mut session, &control_authority, &mut channel, commands)?;
            }
            attempt.apply(|| {
                publish_initial(LiveInitialSnapshot {
                    connection_epoch: connection_epoch.to_string(),
                    service_instance_id: hello.service_instance_id.clone(),
                    mux_space: initial.mux_space,
                    sessions: initial.sessions,
                })
            })?;
            client.1.set("client_disconnected");
            deadline.enter_session()?;
            let mut sequence = 0_u64;
            if let Some(stop) = stop.as_ref() {
                while !stop.requested()? && continue_reading()? {
                    if let Some(commands) = control_commands {
                        process_controls(&mut session, &control_authority, &mut channel, commands)?;
                    }
                    let Some(round) = session.poll(&mut channel, &attempt, Some(stop))? else {
                        if stop.requested()? {
                            break;
                        }
                        if stop.wait(Duration::from_millis(100))? {
                            break;
                        }
                        continue;
                    };
                    sequence = sequence.checked_add(1).ok_or(())?;
                    attempt.apply(|| {
                        publish_round(LiveEventRound {
                            connection_epoch: connection_epoch.to_string(),
                            sequence: sequence.to_string(),
                            service_instance_id: hello.service_instance_id.clone(),
                            mux_space_id: mux_space_id.clone(),
                            members: round.members,
                            sessions: round.sessions,
                        })
                    })?;
                    if !continue_reading()? {
                        break;
                    }
                    if stop.wait(Duration::from_millis(100))? {
                        break;
                    }
                }
            } else {
                for _ in 0..2 {
                    let _ = session.poll(&mut channel, &attempt, None)?;
                }
            }
            Ok(())
        })();
        let detached = session.detach(&mut channel, &attempt);
        let control_released = publish_control(None);
        outcome?;
        detached?;
        control_released?;
    }
    stream.shutdown(Shutdown::Both).map_err(|_| ())?;
    attempt.apply(|| Ok(hello.service_instance_id))
}

#[derive(Default)]
pub(crate) struct AppClient(connection_epoch::ConnectionOwner, Cell<&'static str>);

impl AppClient {
    pub(crate) fn failure_code(&self) -> &'static str {
        self.1.get()
    }

    #[allow(dead_code)] // One-shot contract probes do not use reconnect streaming.
    pub(crate) fn run(
        &self,
        options: ConnectionOptions<'_>,
        publish: &mut dyn FnMut(LiveInitialSnapshot) -> Result<(), ()>,
    ) -> Result<String, ()> {
        run_attempt(
            self,
            options,
            1,
            publish,
            &mut |_| unreachable!(),
            &mut |_| Ok(()),
            &mut || Ok(true),
        )
    }

    #[allow(dead_code)] // One-shot contract probes do not use reconnect streaming.
    pub(crate) fn run_stream(
        &self,
        options: ConnectionOptions<'_>,
        connection_epoch: u64,
        publish_initial: &mut dyn FnMut(LiveInitialSnapshot) -> Result<(), ()>,
        publish_round: &mut dyn FnMut(LiveEventRound) -> Result<(), ()>,
        publish_control: &mut dyn FnMut(Option<attachment::ControlAuthority>) -> Result<(), ()>,
        continue_reading: &mut dyn FnMut() -> Result<bool, ()>,
    ) -> Result<String, ()> {
        run_attempt(
            self,
            options,
            connection_epoch,
            publish_initial,
            publish_round,
            publish_control,
            continue_reading,
        )
    }
}

fn process_controls<R: Read, W: Write>(
    session: &mut attachment::ReadSession,
    authority: &ControlAuthority,
    channel: &mut transport_auth::Channel<R, W>,
    commands: &Receiver<ControlCommand>,
) -> Result<(), ()> {
    loop {
        let command = match commands.try_recv() {
            Ok(command) => command,
            Err(TryRecvError::Empty) => return Ok(()),
            Err(TryRecvError::Disconnected) => return Err(()),
        };
        let request_id = session.next_control_request_id()?;
        let failed = match command {
            ControlCommand::CreateSession {
                source_session_id,
                continuity_id,
                title,
                reply,
            } => {
                let result = authority.create_session(
                    channel,
                    source_session_id.as_deref(),
                    &continuity_id,
                    &title,
                    &request_id,
                );
                let reconnect = matches!(result, Ok(CreateSessionResult::Accepted(_)) | Err(()));
                let _ = reply.send(result);
                reconnect
            }
            ControlCommand::Submit {
                session_id,
                submission_id,
                text,
                reply,
            } => {
                let result =
                    authority.submit(channel, &session_id, &submission_id, &text, &request_id);
                let failed = result.is_err();
                let _ = reply.send(result);
                failed
            }
            ControlCommand::FindSubmission {
                session_id,
                submission_id,
                reply,
            } => {
                let result =
                    authority.find_submission(channel, &session_id, &submission_id, &request_id);
                let failed = result.is_err();
                let _ = reply.send(result);
                failed
            }
            ControlCommand::Interrupt {
                session_id,
                execution_id,
                reply,
            } => {
                let result = authority.interrupt(channel, &session_id, &execution_id, &request_id);
                let failed = result.is_err();
                let _ = reply.send(result);
                failed
            }
            ControlCommand::ListModels { session_id, reply } => {
                let result = authority.models(channel, &session_id, &request_id);
                let failed = result.is_err();
                let _ = reply.send(result);
                failed
            }
            ControlCommand::SelectModel {
                session_id,
                model_id,
                reply,
            } => {
                let result = authority.select_model(channel, &session_id, &model_id, &request_id);
                let failed = result.is_err();
                let _ = reply.send(result);
                failed
            }
        };
        if failed {
            return Err(());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn execution_hello_requires_exact_profile_version_and_lifetime() {
        let profile = "local-detachable-discovery-execution-managed/v2";
        let value = serde_json::json!({"profile":profile,"protocolVersion":"loushang.app/v1",
            "executionVersion":"loushang.execution/v1","serviceInstanceId":"host-1",
            "restartRecovery":false,"submissionRetention":"service_instance_lifetime"});
        assert!(validate_hello(&serde_json::to_vec(&value).unwrap(), profile).is_ok());
        for (field, bad) in [
            (
                "profile",
                serde_json::json!("local-detachable-execution/v1"),
            ),
            ("protocolVersion", serde_json::json!("loushang.app/v2")),
            (
                "executionVersion",
                serde_json::json!("loushang.execution/v2"),
            ),
            ("restartRecovery", serde_json::json!(true)),
            ("serviceInstanceId", serde_json::json!("")),
            ("submissionRetention", serde_json::json!("persistent")),
        ] {
            let mut changed = value.clone();
            changed[field] = bad;
            assert!(validate_hello(&serde_json::to_vec(&changed).unwrap(), profile).is_err());
        }
        let mut bytes = serde_json::to_vec(&value).unwrap();
        bytes.push(b' ');
        assert!(validate_hello(&bytes, profile).is_err());
    }

    #[test]
    fn initial_snapshot_never_serializes_attachment_authority() {
        let value = serde_json::to_value(LiveInitialSnapshot {
            connection_epoch: "1".into(),
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
