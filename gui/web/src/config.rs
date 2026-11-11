use crate::Result;
use serde::Deserialize;
use std::{
    net::{IpAddr, Ipv4Addr, SocketAddr},
    path::{Path, PathBuf},
};

#[derive(Deserialize)]
#[serde(default)]
pub struct Config {
    pub bind: IpAddr,
    pub port: u16,
    pub dist: Option<PathBuf>,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            bind: IpAddr::V4(Ipv4Addr::LOCALHOST),
            port: 1422,
            dist: None,
        }
    }
}
impl Config {
    pub fn read(root: &Path) -> Result<Self> {
        let path = root.join("host.json");
        if !path.exists() {
            return Ok(Self::default());
        }
        let value: serde_json::Value = serde_json::from_slice(&std::fs::read(path)?)?;
        let web = value.get("web").cloned().unwrap_or(serde_json::json!({}));
        if web.get("certificate").is_some() || web.get("privateKey").is_some() {
            return Err("TLS deployment is outside the local Web interface".into());
        }
        let config: Self = serde_json::from_value(web)?;
        if !config.bind.is_loopback() {
            return Err("the local Web interface requires a loopback bind address".into());
        }
        Ok(config)
    }
    pub fn address(&self) -> SocketAddr {
        SocketAddr::new(self.bind, self.port)
    }
}
pub fn root() -> Result<PathBuf> {
    let home = std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .ok_or("home directory unavailable")?;
    let root = std::env::var_os("LOUSHANG_HOME")
        .filter(|x| !x.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(&home).join(".loushang"));
    if let Ok(suffix) = root.strip_prefix("~") {
        return Ok(PathBuf::from(home).join(suffix));
    }
    Ok(std::path::absolute(root)?)
}
pub fn source_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}
pub fn python() -> PathBuf {
    std::env::var_os("LOUSHANG_GUI_PYTHON")
        .map(PathBuf::from)
        .or_else(bundled_python)
        .or_else(source_python)
        .unwrap_or_else(|| PathBuf::from(if cfg!(windows) { "python" } else { "python3" }))
}
fn source_python() -> Option<PathBuf> {
    let path = source_root().join(if cfg!(windows) {
        ".venv/Scripts/python.exe"
    } else {
        ".venv/bin/python"
    });
    path.is_file().then_some(path)
}
pub fn bundled_python() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let bundled = exe.parent()?.join("../runtime/bin/python3");
    bundled.is_file().then_some(bundled)
}

pub fn state(root: &Path) -> Result<PathBuf> {
    let path = root.join("state/web");
    let mut builder = std::fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(&path)?;
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn defaults_and_explicit_local_listener_configuration() {
        let root = tempfile::tempdir().unwrap();
        assert_eq!(
            Config::read(root.path()).unwrap().address().to_string(),
            "127.0.0.1:1422"
        );
        std::fs::write(
            root.path().join("host.json"),
            r#"{"web":{"bind":"::1","port":0}}"#,
        )
        .unwrap();
        assert_eq!(
            Config::read(root.path()).unwrap().address().to_string(),
            "[::1]:0"
        );
        for value in [
            r#"{"web":{"bind":"0.0.0.0"}}"#,
            r#"{"web":{"port":65536}}"#,
            r#"{"web":{"certificate":"file"}}"#,
            "invalid",
        ] {
            std::fs::write(root.path().join("host.json"), value).unwrap();
            assert!(Config::read(root.path()).is_err());
        }
    }
}
