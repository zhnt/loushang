//! Linux private-file admission. Read only through retained, no-follow descriptors.
use std::ffi::CString;
use std::fs::{File, Metadata};
use std::io::Read;
use std::os::fd::{AsRawFd, FromRawFd};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::path::{Component, Path};

type Result<T> = std::result::Result<T, ()>;
fn openat(parent: i32, name: &[u8], directory: bool) -> Result<File> {
    let name = CString::new(name).map_err(|_| ())?;
    let flags = libc::O_RDONLY
        | libc::O_CLOEXEC
        | libc::O_NOFOLLOW
        | libc::O_NONBLOCK
        | if directory { libc::O_DIRECTORY } else { 0 };
    // Successful descriptors are immediately transferred to exactly one File.
    let fd = unsafe { libc::openat(parent, name.as_ptr(), flags) };
    if fd < 0 {
        return Err(());
    }
    Ok(unsafe { File::from_raw_fd(fd) })
}
fn directory(path: &Path) -> Result<File> {
    if !path.is_absolute() {
        return Err(());
    }
    let mut current = openat(libc::AT_FDCWD, b"/", true)?;
    for component in path.components() {
        match component {
            Component::RootDir => (),
            Component::Normal(name) => {
                current = openat(current.as_raw_fd(), name.as_bytes(), true)?;
            }
            _ => return Err(()),
        }
    }
    private(&current.metadata().map_err(|_| ())?, true)?;
    Ok(current)
}
fn private(meta: &Metadata, directory: bool) -> Result<()> {
    if meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o7777 != if directory { 0o700 } else { 0o600 }
        || if directory {
            !meta.is_dir()
        } else {
            !meta.is_file() || meta.nlink() != 1
        }
    {
        return Err(());
    }
    Ok(())
}
fn identity(meta: &Metadata) -> (u64, u64, u32, u32) {
    (meta.dev(), meta.ino(), meta.uid(), meta.mode())
}
fn version(meta: &Metadata) -> (u64, i64, i64, i64, i64) {
    (
        meta.len(),
        meta.mtime(),
        meta.mtime_nsec(),
        meta.ctime(),
        meta.ctime_nsec(),
    )
}
pub fn read(root: &Path, name: &str) -> Result<Vec<u8>> {
    if name.is_empty()
        || name == "."
        || name == ".."
        || !name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
    {
        return Err(());
    }
    let dir = directory(root)?;
    let dir_before = dir.metadata().map_err(|_| ())?;
    let file = openat(dir.as_raw_fd(), name.as_bytes(), false)?;
    let before = file.metadata().map_err(|_| ())?;
    private(&before, false)?;
    if before.len() > 8192 {
        return Err(());
    }
    let mut bytes = Vec::new();
    (&file).take(8193).read_to_end(&mut bytes).map_err(|_| ())?;
    let after = file.metadata().map_err(|_| ())?;
    private(&after, false)?;
    let reopened = openat(dir.as_raw_fd(), name.as_bytes(), false)?;
    let reopened_meta = reopened.metadata().map_err(|_| ())?;
    private(&reopened_meta, false)?;
    if bytes.len() > 8192
        || version(&before) != version(&after)
        || identity(&before) != identity(&after)
        || identity(&before) != identity(&reopened_meta)
        || version(&before) != version(&reopened_meta)
        || identity(&dir_before) != identity(&directory(root)?.metadata().map_err(|_| ())?)
    {
        return Err(());
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::{symlink, PermissionsExt};
    #[test]
    fn private_descriptor_admission_rejects_aliases_modes_and_oversize() {
        let root = std::env::temp_dir().join(format!("gui-record-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
        let file = root.join("record.json");
        std::fs::write(&file, b"private").unwrap();
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert_eq!(read(&root, "record.json").unwrap(), b"private");
        assert!(read(&root, "../record.json").is_err());
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert!(read(&root, "record.json").is_err());
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600)).unwrap();
        std::fs::hard_link(&file, root.join("hard")).unwrap();
        assert!(read(&root, "record.json").is_err());
        std::fs::remove_file(root.join("hard")).unwrap();
        symlink(&file, root.join("link")).unwrap();
        assert!(read(&root, "link").is_err());
        symlink(&root, root.join("dir-link")).unwrap();
        assert!(read(&root.join("dir-link"), "record.json").is_err());
        std::fs::write(&file, vec![0; 8193]).unwrap();
        assert!(read(&root, "record.json").is_err());
        std::fs::write(&file, b"private").unwrap();
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o755)).unwrap();
        assert!(read(&root, "record.json").is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
