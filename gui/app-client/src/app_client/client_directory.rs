//! Read-only desktop grants. The Host sends relative names and never gets a local path.
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};

type Result<T> = std::result::Result<T, ()>;
const FILE_LIMIT: u64 = 1024 * 1024;
const PAGE: usize = 7 * 1024;
const LIST_LIMIT: usize = 100;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct Request {
    pub id: String,
    operation: Operation,
    path: String,
    offset: usize,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Operation {
    List,
    Read,
}

pub(crate) struct Directory {
    root: PathBuf,
    identity: platform::Identity,
}

impl Directory {
    pub fn open(root: PathBuf) -> Result<Self> {
        let identity = platform::identity(&root)?;
        Ok(Self { root, identity })
    }

    pub fn respond(&self, request: &Request) -> Result<Value> {
        let path = relative(&request.path)?;
        if request.id.len() != 32 || !request.id.bytes().all(|c| c.is_ascii_hexdigit()) {
            return Err(());
        }
        match request.operation {
            Operation::List if request.offset == 0 => {
                let (entries, truncated) = platform::list(self, &path)?;
                Ok(json!({ "entries": entries, "truncated": truncated }))
            }
            Operation::Read if !path.as_os_str().is_empty() => {
                let file = platform::file(self, &path)?;
                let mut data = Vec::new();
                file.take(FILE_LIMIT + 1)
                    .read_to_end(&mut data)
                    .map_err(|_| ())?;
                if data.len() as u64 > FILE_LIMIT || data.contains(&0) {
                    return Err(());
                }
                let utf8 = std::str::from_utf8(&data).map_err(|_| ())?;
                if !utf8.is_char_boundary(request.offset) {
                    return Err(());
                }
                let mut end = request.offset.saturating_add(PAGE).min(utf8.len());
                while !utf8.is_char_boundary(end) {
                    end -= 1;
                }
                Ok(json!({
                    "text": &utf8[request.offset..end],
                    "nextOffset": (end < utf8.len()).then_some(end),
                }))
            }
            _ => Err(()),
        }
    }
}

fn safe_component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && !value.ends_with(['.', ' '])
        && !value.contains(['/', '\\', ':', '\0'])
        && !value.chars().any(char::is_control)
}

fn relative(value: &str) -> Result<PathBuf> {
    if value == "." {
        return Ok(PathBuf::new());
    }
    if value.len() > 4096 || !value.split('/').all(safe_component) {
        return Err(());
    }
    Ok(value.split('/').collect())
}

fn checked_names(path: &Path) -> Result<(Vec<String>, bool)> {
    let mut names = Vec::new();
    let mut truncated = false;
    for (index, entry) in fs::read_dir(path).map_err(|_| ())?.enumerate() {
        if index >= LIST_LIMIT {
            truncated = true;
            break;
        }
        let entry = entry.map_err(|_| ())?;
        let kind = entry.file_type().map_err(|_| ())?;
        if (kind.is_dir() || kind.is_file()) && !kind.is_symlink() {
            if let Ok(name) = entry.file_name().into_string() {
                if safe_component(&name) {
                    names.push(name);
                }
            }
        }
    }
    names.sort();
    Ok((names, truncated))
}

#[cfg(target_os = "linux")]
mod platform {
    use super::*;
    use crate::app_client::record_native::{open_absolute_directory, openat};
    use std::os::{
        fd::AsRawFd,
        unix::{ffi::OsStrExt, fs::MetadataExt},
    };

    pub type Identity = (u64, u64);

    fn file_identity(file: &File) -> Result<Identity> {
        let meta = file.metadata().map_err(|_| ())?;
        Ok((meta.dev(), meta.ino()))
    }

    pub fn identity(path: &Path) -> Result<Identity> {
        file_identity(&open_absolute_directory(path)?)
    }

    fn open(directory: &Directory, path: &Path, is_dir: bool) -> Result<File> {
        let mut current = open_absolute_directory(&directory.root)?;
        if file_identity(&current)? != directory.identity {
            return Err(());
        }
        let mut names = path.iter().peekable();
        while let Some(name) = names.next() {
            current = openat(
                current.as_raw_fd(),
                name.as_bytes(),
                is_dir || names.peek().is_some(),
            )?;
        }
        if !is_dir {
            let meta = current.metadata().map_err(|_| ())?;
            if !meta.is_file() || meta.nlink() != 1 {
                return Err(());
            }
        }
        Ok(current)
    }

    pub fn file(directory: &Directory, path: &Path) -> Result<File> {
        open(directory, path, false)
    }

    pub fn list(directory: &Directory, path: &Path) -> Result<(Vec<String>, bool)> {
        let anchored = open(directory, path, true)?;
        checked_names(&PathBuf::from(format!(
            "/proc/self/fd/{}",
            anchored.as_raw_fd()
        )))
    }
}

#[cfg(windows)]
mod platform {
    use super::*;
    use std::{
        fs::OpenOptions,
        mem::zeroed,
        os::windows::{fs::OpenOptionsExt, io::AsRawHandle},
        path::{Component, Prefix},
    };
    use windows_sys::Win32::{
        Foundation::GENERIC_READ,
        Storage::FileSystem::{
            GetFileInformationByHandle, BY_HANDLE_FILE_INFORMATION, FILE_ATTRIBUTE_DIRECTORY,
            FILE_ATTRIBUTE_REPARSE_POINT, FILE_FLAG_BACKUP_SEMANTICS, FILE_FLAG_OPEN_REPARSE_POINT,
            FILE_READ_ATTRIBUTES, FILE_SHARE_READ,
        },
    };

    pub type Identity = (u32, u32, u32);

    fn open(path: &Path, directory: bool) -> Result<(File, Identity)> {
        let file = OpenOptions::new()
            .access_mode(if directory {
                FILE_READ_ATTRIBUTES
            } else {
                GENERIC_READ
            })
            .share_mode(FILE_SHARE_READ)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS)
            .open(path)
            .map_err(|_| ())?;
        let mut info: BY_HANDLE_FILE_INFORMATION = unsafe { zeroed() };
        let read = unsafe { GetFileInformationByHandle(file.as_raw_handle(), &mut info) };
        if read == 0
            || info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
            || (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY != 0) != directory
            || (!directory && info.nNumberOfLinks != 1)
        {
            return Err(());
        }
        Ok((
            file,
            (
                info.dwVolumeSerialNumber,
                info.nFileIndexHigh,
                info.nFileIndexLow,
            ),
        ))
    }

    fn pin(path: &Path) -> Result<(Vec<File>, Identity)> {
        let mut components = path.components();
        let prefix = match components.next() {
            Some(Component::Prefix(prefix))
                if matches!(prefix.kind(), Prefix::Disk(_) | Prefix::VerbatimDisk(_)) =>
            {
                prefix
            }
            _ => return Err(()),
        };
        if components.next() != Some(Component::RootDir) {
            return Err(());
        }
        let mut name = PathBuf::from(prefix.as_os_str());
        name.push(r"\");
        let (root, mut identity) = open(&name, true)?;
        let mut guards = vec![root];
        for part in components {
            let Component::Normal(part) = part else {
                return Err(());
            };
            name.push(part);
            let (handle, observed) = open(&name, true)?;
            guards.push(handle);
            identity = observed;
        }
        Ok((guards, identity))
    }

    pub fn identity(path: &Path) -> Result<Identity> {
        Ok(pin(path)?.1)
    }

    pub fn file(directory: &Directory, path: &Path) -> Result<File> {
        let target = directory.root.join(path);
        let (_root, identity) = pin(&directory.root)?;
        if identity != directory.identity {
            return Err(());
        }
        let (_parents, _) = pin(target.parent().ok_or(())?)?;
        open(&target, false).map(|(file, _)| file)
    }

    pub fn list(directory: &Directory, path: &Path) -> Result<(Vec<String>, bool)> {
        let target = directory.root.join(path);
        let (_root, identity) = pin(&directory.root)?;
        if identity != directory.identity {
            return Err(());
        }
        let (_parents, _) = pin(&target)?;
        checked_names(&target)
    }
}

#[cfg(not(any(target_os = "linux", windows)))]
mod platform {
    use super::*;
    pub type Identity = ();
    pub fn identity(_: &Path) -> Result<Identity> {
        Err(())
    }
    pub fn file(_: &Directory, _: &Path) -> Result<File> {
        Err(())
    }
    pub fn list(_: &Directory, _: &Path) -> Result<(Vec<String>, bool)> {
        Err(())
    }
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    #[test]
    fn grants_read_only_the_selected_root_and_reject_a_replacement() {
        let root =
            std::env::temp_dir().join(format!("loushang-client-directory-{}", std::process::id()));
        fs::create_dir(&root).unwrap();
        let folder = root.join("chosen");
        fs::create_dir(&folder).unwrap();
        fs::write(folder.join("inside.txt"), "permit").unwrap();
        fs::write(root.join("outside.txt"), "private").unwrap();
        symlink(root.join("outside.txt"), folder.join("escape")).unwrap();
        let grant = Directory::open(folder.clone()).unwrap();
        let mut request = Request {
            id: "a".repeat(32),
            operation: Operation::Read,
            path: "inside.txt".into(),
            offset: 0,
        };
        assert_eq!(grant.respond(&request).unwrap()["text"], "permit");
        for denied in ["../outside.txt", "escape", "/etc/passwd", "a\\b", "a:c"] {
            request.path = denied.into();
            assert!(grant.respond(&request).is_err());
        }
        fs::rename(&folder, root.join("old")).unwrap();
        fs::create_dir(&folder).unwrap();
        request.path = "inside.txt".into();
        assert!(grant.respond(&request).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
