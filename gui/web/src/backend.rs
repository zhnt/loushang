use crate::{config, Result};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    process::Stdio,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::Duration,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, Command},
    sync::{oneshot, Mutex},
};

type Pending = Arc<Mutex<HashMap<u64, oneshot::Sender<Value>>>>;
pub struct Backend {
    input: Mutex<Option<ChildStdin>>,
    child: Mutex<Child>,
    pending: Pending,
    next: AtomicU64,
}
impl Backend {
    pub fn spawn() -> Result<Self> {
        let mut command = Command::new(config::python());
        command
            .args(["-m", "loushang.coding.web_gateway"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .kill_on_drop(true);
        let source = config::source_root().join("src");
        if config::bundled_python().is_some() {
            command.env_remove("PYTHONPATH").env_remove("PYTHONHOME");
        } else if source.is_dir() {
            command.env("PYTHONPATH", source);
        }
        let mut child = command.spawn()?;
        let input = child.stdin.take().ok_or("backend input unavailable")?;
        let output = child.stdout.take().ok_or("backend output unavailable")?;
        let pending = Pending::default();
        tokio::spawn(read_replies(output, pending.clone()));
        Ok(Self {
            input: Mutex::new(Some(input)),
            child: Mutex::new(child),
            pending,
            next: AtomicU64::new(1),
        })
    }
    pub async fn call(&self, request: Value) -> Result<Value> {
        let id = self.next.fetch_add(1, Ordering::Relaxed);
        let mut bytes = serde_json::to_vec(&json!({"id":id,"request":request}))?;
        bytes.push(b'\n');
        let (sender, receiver) = oneshot::channel();
        self.pending.lock().await.insert(id, sender);
        let result = async {
            let mut input = self.input.lock().await;
            input
                .as_mut()
                .ok_or("backend closed")?
                .write_all(&bytes)
                .await?;
            drop(input);
            Ok::<_, crate::Error>(tokio::time::timeout(Duration::from_secs(75), receiver).await??)
        }
        .await;
        self.pending.lock().await.remove(&id);
        result
    }
    pub async fn close(&self) {
        self.input.lock().await.take();
        let mut child = self.child.lock().await;
        if tokio::time::timeout(Duration::from_secs(5), child.wait())
            .await
            .is_err()
        {
            let _ = child.kill().await;
        }
    }
}
async fn read_replies(output: tokio::process::ChildStdout, pending: Pending) {
    let mut output = BufReader::new(output);
    loop {
        let mut bytes = Vec::new();
        use tokio::io::AsyncReadExt;
        let read = (&mut output)
            .take(16_777_217)
            .read_until(b'\n', &mut bytes)
            .await;
        if !matches!(read, Ok(1..=16_777_216)) {
            break;
        }
        let Ok(mut reply) = serde_json::from_slice::<Value>(&bytes) else {
            break;
        };
        if let Some(id) = reply.get("id").and_then(Value::as_u64) {
            if let Some(sender) = pending.lock().await.remove(&id) {
                reply.as_object_mut().map(|fields| fields.remove("id"));
                let _ = sender.send(reply);
            }
        }
    }
    pending.lock().await.clear();
}
