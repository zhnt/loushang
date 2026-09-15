//! Windows connection-lifecycle experiment, not a Tauri command or RPC client.
#[cfg(windows)]
#[path = "../attachment_probe.rs"]
mod attachment_probe;
#[cfg(windows)]
#[path = "../connection_epoch.rs"]
mod connection_epoch;
#[cfg(windows)]
#[path = "../record_native.rs"]
mod record_native;
#[cfg(windows)]
#[allow(dead_code)]
#[path = "../transport_auth.rs"]
mod transport_auth;

#[cfg(windows)]
mod connection {
    use super::{record_native, transport_auth};
    use serde::{Deserialize, Serialize};
    use std::io::{self, Read, Write};
    use std::net::{Ipv4Addr, Shutdown, SocketAddr, TcpStream};
    use std::path::Path;
    use std::sync::mpsc::{self, Sender};
    use std::thread::{self, JoinHandle};
    use std::time::{Duration, Instant};

    struct DeadlineStream {
        stream: TcpStream,
        deadline: Instant,
    }
    fn remaining(deadline: Instant) -> io::Result<Duration> {
        deadline
            .checked_duration_since(Instant::now())
            .filter(|time| !time.is_zero())
            .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "connection deadline"))
    }
    impl Read for DeadlineStream {
        fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
            self.stream
                .set_read_timeout(Some(remaining(self.deadline)?))?;
            self.stream.read(buffer)
        }
    }
    impl Write for DeadlineStream {
        fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
            self.stream
                .set_write_timeout(Some(remaining(self.deadline)?))?;
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
    ) -> Result<String, ()> {
        let deadline = Instant::now() + timeout;
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
        let stream = TcpStream::connect_timeout(&address, remaining(deadline).map_err(|_| ())?)
            .map_err(|_| ())?;
        let (finish, receiver) = mpsc::channel();
        let worker = if let Some(delay) = cancel {
            let socket = stream.try_clone().map_err(|_| ())?;
            let fence = attempt.cancellation();
            Some(thread::spawn(move || {
                if receiver.recv_timeout(delay).is_err() {
                    fence.invalidate();
                    let _ = socket.shutdown(Shutdown::Both);
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
            deadline,
        };
        let writer = DeadlineStream {
            stream: stream.try_clone().map_err(|_| ())?,
            deadline,
        };
        let mut channel = transport_auth::Channel::authenticate(
            transport_auth::Frames::new(reader, writer),
            &record,
        )?;
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
            super::attachment_probe::run(&mut channel, &hello.service_instance_id, &attempt)?;
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
        if args.len() != 4 && !(args.len() == 5 && args[4] == "--attach") {
            return Err(());
        }
        let timeout: u64 = args[2].to_str().ok_or(())?.parse().map_err(|_| ())?;
        let cancel: i64 = args[3].to_str().ok_or(())?.parse().map_err(|_| ())?;
        if !(1..=5000).contains(&timeout) || !(-1..=5000).contains(&cancel) {
            return Err(());
        }
        connection::run(
            &connection_epoch::ConnectionOwner::default(),
            std::path::Path::new(&args[1]),
            std::time::Duration::from_millis(timeout),
            (cancel >= 0).then(|| std::time::Duration::from_millis(cancel as u64)),
            args.len() == 5,
        )
    })();
    match outcome {
        Ok(instance) => {
            if args.len() == 5 {
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
