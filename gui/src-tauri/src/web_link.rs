pub(crate) fn safe_web_url(value: &str) -> bool {
    parse_web_url(value).is_some()
}

pub(crate) fn parse_web_url(value: &str) -> Option<tauri::Url> {
    if value.len() > 4096 || value.chars().any(|c| c.is_control() || c == '\\') {
        return None;
    }
    let (_, authority) = value.split_once("://")?;
    if authority.split('/').next()?.contains('@') {
        return None;
    }
    tauri::Url::parse(value).ok().filter(is_web_destination)
}

fn is_web_destination(url: &tauri::Url) -> bool {
    matches!(url.scheme(), "http" | "https")
        && url.host_str().is_some()
        && url.username().is_empty()
        && url.password().is_none()
        && url.query().is_none()
        && url.fragment().is_none()
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
}
