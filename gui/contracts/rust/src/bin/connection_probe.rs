//! Windows connection-lifecycle experiment, not a Tauri command or RPC client.
#[cfg(windows)]
#[path = "../attachment_probe.rs"]
mod attachment_probe;
#[cfg(windows)]
#[path = "../connection_epoch.rs"]
mod connection_epoch;
#[cfg(windows)]
#[path = "../../../../src-tauri/src/read_stop.rs"]
mod read_stop;
#[cfg(windows)]
#[allow(dead_code)] // Nonblocking collection is for the future desktop lifecycle.
#[path = "../../../../src-tauri/src/read_worker.rs"]
mod read_worker;
#[cfg(windows)]
#[path = "../record_native.rs"]
mod record_native;
#[cfg(windows)]
#[path = "../request_deadline.rs"]
mod request_deadline;
#[cfg(windows)]
#[allow(dead_code)]
#[path = "../transport_auth.rs"]
mod transport_auth;

#[cfg(windows)]
mod connection {
    use super::request_deadline::RequestDeadline;
    use super::{record_native, transport_auth};
    use serde::{Deserialize, Serialize};
    use std::io::{self, Read, Write};
    use std::net::{Ipv4Addr, Shutdown, SocketAddr, TcpStream};
    use std::path::Path;
    use std::sync::mpsc::{self, Sender};
    use std::thread::{self, JoinHandle};
    use std::time::Duration;

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
    pub fn run(
        owner: &super::connection_epoch::ConnectionOwner,
        root: &Path,
        timeout: Duration,
        cancel: Option<Duration>,
        attach: bool,
        stop: Option<super::read_stop::ReadStop>,
    ) -> Result<String, ()> {
        let deadline = RequestDeadline::new(timeout)?;
        let attempt = owner.begin()?;
        let name = transport_auth::record_value::Record::filename("workspace")?;
        let record =
            transport_auth::record_value::Record::decode(&record_native::read(root, &name)?)?;
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
            super::attachment_probe::run(
                &mut channel,
                &hello.service_instance_id,
                &attempt,
                &deadline,
                stop.as_ref(),
            )?;
        }
        // Authentication instance and service instance are distinct identities.
        stream.shutdown(Shutdown::Both).map_err(|_| ())?;
        attempt.apply(|| Ok(hello.service_instance_id))
    }
}

#[cfg(windows)]
fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    let outcome = (|| {
        if args.len() != 4 && !(args.len() == 5 && (args[4] == "--attach" || args[4] == "--watch"))
        {
            return Err(());
        }
        let timeout: u64 = args[2].to_str().ok_or(())?.parse().map_err(|_| ())?;
        let cancel: i64 = args[3].to_str().ok_or(())?.parse().map_err(|_| ())?;
        if !(1..=5000).contains(&timeout) || !(-1..=5000).contains(&cancel) {
            return Err(());
        }
        let watch = args.len() == 5 && args[4] == "--watch";
        if watch && cancel <= 0 {
            return Err(());
        }
        let root = std::path::PathBuf::from(&args[1]);
        let attach = args.len() == 5;
        read_worker::ReadWorker::spawn(move |stop| {
            connection::run(
                &connection_epoch::ConnectionOwner::default(),
                &root,
                std::time::Duration::from_millis(timeout),
                (cancel >= 0).then(|| std::time::Duration::from_millis(cancel as u64)),
                attach,
                watch.then_some(stop),
            )
        })
        .map_err(|_| ())?
        .wait()
        .map_err(|_| ())
    })();
    match outcome {
        Ok(instance) => {
            if args.len() == 5 && args[4] == "--watch" {
                println!("watch stopped; detached; connection closed; instance={instance}");
            } else if args.len() == 5 {
                println!("attachment snapshots verified; detached; connection closed; instance={instance}");
            } else {
                println!("hello verified; connection closed; instance={instance}");
            }
        }
        Err(()) => {
            eprintln!("connection probe failed");
            std::process::exit(1);
        }
    }
}
#[cfg(not(windows))]
fn main() {
    eprintln!("Windows connection probe unavailable");
    std::process::exit(1);
}
