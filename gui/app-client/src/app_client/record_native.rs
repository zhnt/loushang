//! Private connection-record admission. Platform details stay behind this port.
use std::path::{Component, Path};

#[cfg(unix)]
#[path = "record_native/posix.rs"]
mod platform;
#[cfg(windows)]
#[path = "record_native/windows.rs"]
mod platform;

pub fn read(root: &Path, name: &str) -> Result<Vec<u8>, ()> {
    if !root.is_absolute()
        || root
            .components()
            .any(|part| matches!(part, Component::ParentDir))
        || name.is_empty()
        || name == "."
        || name == ".."
        || !name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
    {
        return Err(());
    }
    platform::read(root, name)
}
