//! Matches AppServer's POSIX owner-only, no-follow admission contract.
//! rustix owns OS calls; the client reads only through validated descriptors.
use rustix::fs::{open, openat, Mode, OFlags};
use rustix::process::geteuid;
use std::fs::{File, Metadata};
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

type Result<T> = std::result::Result<T, ()>;
const LIMIT: u64 = 8192;

fn identity(info: &Metadata, directory: bool) -> Result<(u64, u64)> {
    if (if directory {
        !info.is_dir()
    } else {
        !info.is_file()
    }) || info.uid() != geteuid().as_raw()
        || info.mode() & 0o077 != 0
        || (!directory && info.nlink() != 1)
    {
        return Err(());
    }
    Ok((info.dev(), info.ino()))
}

fn open_root(root: &Path) -> Result<File> {
    open(
        root,
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map(File::from)
    .map_err(|_| ())
}

fn open_record(directory: &File, name: &str) -> Result<File> {
    openat(
        directory,
        name,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
        Mode::empty(),
    )
    .map(File::from)
    .map_err(|_| ())
}

pub(super) fn read(root: &Path, name: &str) -> Result<Vec<u8>> {
    let directory = open_root(root)?;
    let root_id = identity(&directory.metadata().map_err(|_| ())?, true)?;
    let file = open_record(&directory, name)?;
    let before = file.metadata().map_err(|_| ())?;
    let file_id = identity(&before, false)?;
    if before.len() > LIMIT {
        return Err(());
    }
    let mut bytes = Vec::new();
    (&file)
        .take(LIMIT + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| ())?;
    let after = file.metadata().map_err(|_| ())?;
    if bytes.len() as u64 > LIMIT
        || before.len() != after.len()
        || (before.mtime(), before.mtime_nsec()) != (after.mtime(), after.mtime_nsec())
        || (before.ctime(), before.ctime_nsec()) != (after.ctime(), after.ctime_nsec())
        || identity(&after, false)? != file_id
        || identity(
            &open_record(&directory, name)?.metadata().map_err(|_| ())?,
            false,
        )? != file_id
        || identity(&directory.metadata().map_err(|_| ())?, true)? != root_id
        || identity(&open_root(root)?.metadata().map_err(|_| ())?, true)? != root_id
    {
        return Err(());
    }
    Ok(bytes)
}
