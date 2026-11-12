use serde::Deserialize;
use std::{
    io::Read,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::{Duration, Instant},
};

const LIMIT: u64 = 8192;
const TIMEOUT: Duration = Duration::from_secs(95);

pub(super) fn executable() -> Option<PathBuf> {
    let path = if let Some(configured) = std::env::var_os("LOUSHANG_MUX") {
        PathBuf::from(configured)
    } else {
        let binary = std::env::current_exe().ok()?;
        if cfg!(windows) {
            binary.with_file_name("loushang-mux.exe")
        } else {
            binary.parent()?.parent()?.join("loushang-mux")
        }
    };
    (path.is_absolute() && path.is_file()).then_some(path)
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct State {
    pub(super) state: String,
    pub(super) instance_id: Option<String>,
    pub(super) service_instance_id: Option<String>,
    pub(super) record_root: Option<PathBuf>,
    pub(super) error_code: Option<String>,
}

pub(super) fn invoke(
    executable: &Path,
    home: &Path,
    action: &str,
    instance: Option<&str>,
) -> Result<State, &'static str> {
    let mut command = Command::new(executable);
    command
        .args(["service", action, "--json"])
        .env("LOUSHANG_HOME", home)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    if let Some(instance) = instance {
        command.args(["--instance", instance]);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = command.spawn().map_err(|_| "management_unavailable")?;
    let deadline = Instant::now() + TIMEOUT;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(25));
            }
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("management_unconfirmed");
            }
        }
    };
    let mut bytes = Vec::new();
    child
        .stdout
        .take()
        .ok_or("management_unconfirmed")?
        .take(LIMIT + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "management_unconfirmed")?;
    if bytes.len() as u64 > LIMIT {
        return Err("management_unconfirmed");
    }
    let reply: State = serde_json::from_slice(&bytes).map_err(|_| "management_unconfirmed")?;
    if status.success() != reply.error_code.is_none() {
        return Err("management_unconfirmed");
    }
    Ok(reply)
}
