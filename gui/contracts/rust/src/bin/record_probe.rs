//! Native fixture-file admission experiment. No endpoint discovery or connection.
#[cfg(windows)]
mod native {
    use std::collections::BTreeSet;
    use std::ffi::c_void;
    use std::fs::{File, OpenOptions};
    use std::io::Read;
    use std::mem::{size_of, zeroed};
    use std::os::windows::fs::{MetadataExt, OpenOptionsExt};
    use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
    use std::path::{Component, Path, Prefix};
    use std::ptr::{null_mut, read_unaligned};
    use windows_sys::Win32::Foundation::{LocalFree, GENERIC_READ, HANDLE};
    use windows_sys::Win32::Security::Authorization::{
        ConvertSidToStringSidW, GetSecurityInfo, SE_FILE_OBJECT,
    };
    use windows_sys::Win32::Security::*;
    use windows_sys::Win32::Storage::FileSystem::*;
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

    type Result<T> = std::result::Result<T, ()>;
    const LIMIT: u64 = 8192;
    // GetSecurityInfo / ConvertSidToStringSidW allocate with LocalAlloc.
    struct Allocation(*mut c_void);
    impl Drop for Allocation {
        fn drop(&mut self) {
            unsafe {
                LocalFree(self.0);
            }
        }
    }
    fn sid_string(sid: PSID) -> Result<String> {
        if sid.is_null() {
            return Err(());
        }
        let mut text = null_mut();
        // SID comes from a validated token/security descriptor or bounded ACE.
        if unsafe { ConvertSidToStringSidW(sid, &mut text) } == 0 {
            return Err(());
        }
        let _allocation = Allocation(text.cast());
        for length in 0..256 {
            if unsafe { *text.add(length) } == 0 {
                return String::from_utf16(unsafe { std::slice::from_raw_parts(text, length) })
                    .map_err(|_| ());
            }
        }
        Err(())
    }
    fn current_sid() -> Result<String> {
        let mut raw = null_mut();
        if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut raw) } == 0 {
            return Err(());
        }
        // Exactly one owner after successful OpenProcessToken.
        let token = unsafe { OwnedHandle::from_raw_handle(raw) };
        let mut length = 0;
        unsafe {
            GetTokenInformation(token.as_raw_handle(), TokenUser, null_mut(), 0, &mut length);
        }
        if length < size_of::<TOKEN_USER>() as u32 || length > 4096 {
            return Err(());
        }
        // usize storage supplies alignment needed by TOKEN_USER.
        let mut buffer = vec![0usize; (length as usize).div_ceil(size_of::<usize>())];
        if unsafe {
            GetTokenInformation(
                token.as_raw_handle(),
                TokenUser,
                buffer.as_mut_ptr().cast(),
                length,
                &mut length,
            )
        } == 0
        {
            return Err(());
        }
        let user = unsafe { &*buffer.as_ptr().cast::<TOKEN_USER>() };
        sid_string(user.User.Sid)
    }
    fn security(handle: HANDLE, user: &str) -> Result<()> {
        let (mut owner, mut descriptor) = (null_mut(), null_mut());
        let mut dacl = null_mut();
        if unsafe {
            GetSecurityInfo(
                handle,
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &mut owner,
                null_mut(),
                &mut dacl,
                null_mut(),
                &mut descriptor,
            )
        } != 0
        {
            return Err(());
        }
        let _allocation = Allocation(descriptor);
        let (mut control, mut revision, mut present, mut defaulted) = (0, 0, 0, 0);
        if unsafe { GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) } == 0
            || unsafe {
                GetSecurityDescriptorDacl(descriptor, &mut present, &mut dacl, &mut defaulted)
            } == 0
            || sid_string(owner)? != user
            || present == 0
            || dacl.is_null()
            || defaulted != 0
            || control & SE_DACL_PROTECTED == 0
        {
            return Err(());
        }
        let expected = BTreeSet::from([user.to_owned(), "S-1-5-18".to_owned()]);
        let mut info: ACL_SIZE_INFORMATION = unsafe { zeroed() };
        if unsafe {
            GetAclInformation(
                dacl,
                (&mut info as *mut ACL_SIZE_INFORMATION).cast(),
                size_of::<ACL_SIZE_INFORMATION>() as u32,
                AclSizeInformation,
            )
        } == 0
            || info.AceCount as usize != expected.len()
        {
            return Err(());
        }
        let mut admitted = BTreeSet::new();
        for index in 0..info.AceCount {
            let mut pointer = null_mut();
            if unsafe { GetAce(dacl, index, &mut pointer) } == 0 || pointer.is_null() {
                return Err(());
            }
            // Kernel-returned ACL memory remains owned by descriptor above.
            let header = unsafe { read_unaligned(pointer.cast::<ACE_HEADER>()) };
            // ACCESS_ALLOWED_ACE_TYPE is 0 in the existing Windows contract.
            if header.AceType != 0 || header.AceFlags != 0 || header.AceSize < 16 {
                return Err(());
            }
            let bytes = pointer.cast::<u8>();
            let mask = unsafe { read_unaligned(bytes.add(4).cast::<u32>()) };
            let sid = unsafe { bytes.add(8) };
            let sid_size = 8 + 4 * unsafe { *sid.add(1) } as usize;
            if mask != FILE_ALL_ACCESS
                || sid_size > header.AceSize as usize - 8
                || unsafe { IsValidSid(sid.cast()) } == 0
            {
                return Err(());
            }
            admitted.insert(sid_string(sid.cast())?);
        }
        if admitted != expected {
            return Err(());
        }
        Ok(())
    }
    #[derive(PartialEq, Eq)]
    struct Identity(u64, [u8; 16]);
    fn identity(file: &File, directory: bool, user: &str) -> Result<Identity> {
        let handle = file.as_raw_handle();
        let mut info: BY_HANDLE_FILE_INFORMATION = unsafe { zeroed() };
        if unsafe { GetFileInformationByHandle(handle, &mut info) } == 0
            || info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
            || (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY != 0) != directory
            || (!directory && info.nNumberOfLinks != 1)
        {
            return Err(());
        }
        security(handle, user)?;
        let mut id: FILE_ID_INFO = unsafe { zeroed() };
        if unsafe {
            GetFileInformationByHandleEx(
                handle,
                FileIdInfo,
                (&mut id as *mut FILE_ID_INFO).cast(),
                size_of::<FILE_ID_INFO>() as u32,
            )
        } == 0
        {
            return Err(());
        }
        Ok(Identity(id.VolumeSerialNumber, id.FileId.Identifier))
    }
    fn open(path: &Path, directory: bool) -> Result<File> {
        let access = READ_CONTROL
            | if directory {
                FILE_READ_ATTRIBUTES
            } else {
                GENERIC_READ
            };
        let flags = FILE_FLAG_OPEN_REPARSE_POINT
            | if directory {
                FILE_FLAG_BACKUP_SEMANTICS
            } else {
                FILE_ATTRIBUTE_NORMAL
            };
        OpenOptions::new()
            .access_mode(access)
            .share_mode(
                FILE_SHARE_READ | FILE_SHARE_WRITE | if directory { 0 } else { FILE_SHARE_DELETE },
            )
            .custom_flags(flags)
            .open(path)
            .map_err(|_| ())
    }
    pub fn read(root: &Path, name: &str) -> Result<Vec<u8>> {
        let local_drive = matches!(root.components().next(), Some(Component::Prefix(prefix)) if matches!(prefix.kind(), Prefix::Disk(_) | Prefix::VerbatimDisk(_)));
        if !local_drive
            || !root.is_absolute()
            || root
                .components()
                .any(|part| matches!(part, Component::ParentDir))
            || name.is_empty()
            || !name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
            || name == "."
            || name == ".."
        {
            return Err(());
        }
        let user = current_sid()?;
        let directory = open(root, true)?;
        let root_id = identity(&directory, true, &user)?;
        let path = root.join(name);
        let file = open(&path, false)?;
        let file_id = identity(&file, false, &user)?;
        // Admission happens before any read; read through the admitted handle.
        let before = file.metadata().map_err(|_| ())?;
        if before.file_size() > LIMIT {
            return Err(());
        }
        let mut bytes = Vec::new();
        (&file)
            .take(LIMIT + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| ())?;
        let after = file.metadata().map_err(|_| ())?;
        if bytes.len() as u64 > LIMIT
            || before.file_size() != after.file_size()
            || before.last_write_time() != after.last_write_time()
            || identity(&file, false, &user)? != file_id
            || identity(&open(&path, false)?, false, &user)? != file_id
            || identity(&directory, true, &user)? != root_id
            || identity(&open(root, true)?, true, &user)? != root_id
        {
            return Err(());
        }
        Ok(bytes)
    }
}

#[cfg(windows)]
fn main() {
    use sha2::{Digest, Sha256};
    let arguments: Vec<_> = std::env::args_os().collect();
    let result = if arguments.len() == 2 {
        native::read(std::path::Path::new(&arguments[1]), "fixture-record")
    } else {
        Err(())
    };
    match result {
        Ok(bytes) => println!("{} {:x}", bytes.len(), Sha256::digest(&bytes)),
        Err(()) => {
            eprintln!("record admission failed");
            std::process::exit(1);
        }
    }
}
#[cfg(not(windows))]
fn main() {
    eprintln!("Windows record admission unavailable");
    std::process::exit(1);
}
