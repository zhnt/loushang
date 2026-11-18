pub(crate) fn safe_web_url(value: &str) -> bool {
    parse_web_url(value).is_some()
}

pub(crate) fn parse_web_url(value: &str) -> Option<tauri::Url> {
    parse_external_url(value).filter(|url| url.query().is_none() && url.fragment().is_none())
}

fn parse_external_url(value: &str) -> Option<tauri::Url> {
    if value.len() > 4096 || value.chars().any(|c| c.is_control() || c == '\\') {
        return None;
    }
    let (_, authority) = value.split_once("://")?;
    if authority.split(['/', '?', '#']).next()?.contains('@') {
        return None;
    }
    tauri::Url::parse(value).ok().filter(is_web_destination)
}

fn is_web_destination(url: &tauri::Url) -> bool {
    matches!(url.scheme(), "http" | "https")
        && url.host_str().is_some()
        && url.username().is_empty()
        && url.password().is_none()
}

#[tauri::command]
pub(crate) async fn open_web_link(url: String) -> Result<(), &'static str> {
    let url = parse_external_url(&url).ok_or("invalid_link")?;
    tauri::async_runtime::spawn_blocking(move || launch_web_url(&url))
        .await
        .map_err(|_| "open_failed")?
}

#[cfg(target_os = "linux")]
fn launch_web_url(url: &tauri::Url) -> Result<(), &'static str> {
    use gtk::gio;
    gio::AppInfo::launch_default_for_uri(url.as_str(), None::<&gio::AppLaunchContext>)
        .map_err(|_| "open_failed")
}

#[cfg(target_os = "windows")]
fn launch_web_url(url: &tauri::Url) -> Result<(), &'static str> {
    crate::client_settings::open_in_desktop(std::path::Path::new(url.as_str()))
}

#[cfg(target_os = "macos")]
fn launch_web_url(url: &tauri::Url) -> Result<(), &'static str> {
    if std::process::Command::new("open")
        .arg(url.as_str())
        .status()
        .is_ok_and(|status| status.success())
    {
        Ok(())
    } else {
        Err("open_failed")
    }
}

#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
fn launch_web_url(_url: &tauri::Url) -> Result<(), &'static str> {
    Err("operation_unavailable")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn browser_links_are_web_only_and_never_carry_credentials() {
        for url in ["https://host.example/app", "http://127.0.0.1:8080/"] {
            assert!(safe_web_url(url));
        }
        for url in [
            "file:///tmp/a",
            "javascript:alert(1)",
            "https://user:secret@host/",
            "https://@host/",
            "http:host.example",
            "https://host/?token=secret",
            "https://host/#secret",
            "--help",
        ] {
            assert!(!safe_web_url(url));
        }
    }

    #[test]
    fn reply_links_accept_web_queries_and_fragments_but_reject_credentials_and_other_schemes() {
        assert!(parse_external_url("https://example.org/?q=ai#results").is_some());
        assert!(parse_external_url("https://example.org?q=user@example.org").is_some());
        for value in [
            "https://user:password@example.org/",
            "file:///tmp/a",
            "javascript:alert(1)",
        ] {
            assert!(parse_external_url(value).is_none());
        }
    }
}
