use serde::Serialize;
use sha2::{Digest, Sha256};

#[derive(Serialize)]
pub(crate) struct OfflineAccount {
    name: String,
    id: Option<String>,
}

#[tauri::command]
pub(crate) fn offline_account() -> Option<OfflineAccount> {
    let name = [if cfg!(windows) { "USERNAME" } else { "USER" }, "LOGNAME"]
        .iter()
        .filter_map(|key| std::env::var(key).ok())
        .find(|value| !value.trim().is_empty())?;
    let hostname = tauri_plugin_os::hostname();
    let id = (!hostname.trim().is_empty()).then(|| {
        // Domain separation and an unambiguous pair. This is a local
        // presentation identifier and carries no authentication authority.
        let mut hash = Sha256::new();
        hash.update(b"loushang:offline-account:v1\0");
        hash.update(hostname.as_bytes());
        hash.update(b"\0");
        hash.update(name.as_bytes());
        format!("local-{:x}", hash.finalize())
    });
    Some(OfflineAccount { name, id })
}
