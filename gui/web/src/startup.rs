use crate::{config, Result};
use std::{
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::Duration,
};

pub fn executable() -> Result<PathBuf> {
    if let Some(path) = std::env::var_os("LOUSHANG_GUI_WEB") {
        return Ok(path.into());
    }
    let name = if cfg!(windows) {
        "loushang-web.exe"
    } else {
        "loushang-web"
    };
    let sibling = std::env::current_exe()?.with_file_name(name);
    let source = config::source_root()
        .join("gui/web/target/debug")
        .join(name);
    [sibling, source]
        .into_iter()
        .find(|path| path.is_file())
        .ok_or_else(|| "build the GUI Web binary first (gui/web/Cargo.toml)".into())
}

async fn probe(root: &Path, client: &reqwest::Client) -> Result<Option<String>> {
    let Ok(bytes) = std::fs::read(root.join("state/web/endpoint.json")) else {
        return Ok(None);
    };
    let value: serde_json::Value = serde_json::from_slice(&bytes)?;
    let url = value["url"].as_str().ok_or("invalid endpoint")?;
    let parsed = url::Url::parse(url)?;
    let config = config::Config::read(root)?;
    if !local_endpoint(&parsed, config.bind) {
        return Err("invalid local endpoint".into());
    }
    let result = client
        .post(format!("{url}/api/loushang"))
        .header("X-Loushang-Client", "1")
        .json(&serde_json::json!({"operation":"environment"}))
        .send()
        .await;
    let running = result
        .ok()
        .is_some_and(|response| response.status().is_success());
    if running && value["implementation"] != "gui-rust/v1" {
        return Err("restart the old Python Web adapter before using GUI Web".into());
    }
    Ok(running.then(|| url.to_owned()))
}
fn client() -> Result<reqwest::Client> {
    Ok(reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(3))
        .build()?)
}
fn startup_lock(state: &Path) -> Result<rusqlite::Connection> {
    let lock = rusqlite::Connection::open(state.join("startup.sqlite3"))?;
    lock.busy_timeout(Duration::from_secs(30))?;
    lock.execute_batch("BEGIN IMMEDIATE")?;
    Ok(lock)
}
fn spawn(root: &Path, state: &Path) -> Result<std::process::Child> {
    let log = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(state.join("server.log"))?;
    let mut command = Command::new(executable()?);
    command
        .env("LOUSHANG_HOME", root)
        .stdin(Stdio::null())
        .stdout(log.try_clone()?)
        .stderr(log);
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x00000200 | 0x00000008);
    }
    Ok(command.spawn()?)
}
async fn wait_ready(
    root: &Path,
    client: &reqwest::Client,
    child: &mut std::process::Child,
) -> Result<String> {
    for _ in 0..150 {
        if child.try_wait()?.is_some() {
            return Err("GUI Web startup failed; see state/web/server.log".into());
        }
        if let Some(url) = probe(root, client).await? {
            return Ok(url);
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    Err("GUI Web startup timed out".into())
}
pub async fn ensure(root: PathBuf) -> Result<String> {
    let client = client()?;
    let state = config::state(&root)?;
    if let Some(url) = probe(&root, &client).await? {
        return Ok(url);
    }
    let _lock = startup_lock(&state)?;
    if let Some(url) = probe(&root, &client).await? {
        return Ok(url);
    }
    let mut child = spawn(&root, &state)?;
    wait_ready(&root, &client, &mut child).await
}

fn local_endpoint(url: &url::Url, bind: std::net::IpAddr) -> bool {
    url.host_str().and_then(|host| {
        host.trim_matches(['[', ']'])
            .parse::<std::net::IpAddr>()
            .ok()
    }) == Some(bind)
        && url.scheme() == "http"
        && url.username().is_empty()
        && url.password().is_none()
        && url.path() == "/"
        && url.query().is_none()
        && url.fragment().is_none()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn discovered_endpoint_is_only_a_plain_local_origin() {
        let bind = "127.0.0.1".parse().unwrap();
        assert!(local_endpoint(
            &url::Url::parse("http://127.0.0.1:1422").unwrap(),
            bind
        ));
        for url in [
            "http://192.0.2.1:1422",
            "https://127.0.0.1:1422",
            "http://name@127.0.0.1:1422",
            "http://name:pass@127.0.0.1:1422",
            "http://127.0.0.1:1422/path",
            "http://127.0.0.1:1422/?query",
            "http://127.0.0.1:1422/#fragment",
        ] {
            assert!(!local_endpoint(&url::Url::parse(url).unwrap(), bind));
        }
        assert!(local_endpoint(
            &url::Url::parse("http://[::1]:1422").unwrap(),
            "::1".parse().unwrap()
        ));
    }
}
