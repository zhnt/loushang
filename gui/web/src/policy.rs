use hyper::Request;
use std::net::SocketAddr;

pub fn allowed<T>(request: &Request<T>, address: SocketAddr) -> bool {
    let Some(host) = request.headers().get("host").and_then(|v| v.to_str().ok()) else {
        return false;
    };
    let Ok(target) = url::Url::parse(&format!("http://{host}")) else {
        return false;
    };
    if !valid_target(&target, address) {
        return false;
    }
    match request.headers().get("origin") {
        None => true,
        Some(origin) => origin
            .to_str()
            .is_ok_and(|value| value == format!("http://{host}")),
    }
}
fn valid_target(target: &url::Url, address: SocketAddr) -> bool {
    matches!(target.host_str(), Some("127.0.0.1" | "localhost" | "[::1]"))
        && target.port_or_known_default() == Some(address.port())
        && target.username().is_empty()
        && target.password().is_none()
        && target.path() == "/"
        && target.query().is_none()
        && target.fragment().is_none()
}

#[cfg(test)]
mod tests {
    use super::*;
    fn request(host: &str, origin: Option<&str>) -> Request<()> {
        let mut builder = Request::builder().header("host", host);
        if let Some(origin) = origin {
            builder = builder.header("origin", origin);
        }
        builder.body(()).unwrap()
    }
    #[test]
    fn local_page_and_same_origin_api_need_no_credentials() {
        let address = "127.0.0.1:1422".parse().unwrap();
        assert!(allowed(&request("127.0.0.1:1422", None), address));
        assert!(allowed(
            &request("localhost:1422", Some("http://localhost:1422")),
            address
        ));
    }
    #[test]
    fn rejects_foreign_origins_and_rebinding_hosts() {
        let address = "127.0.0.1:1422".parse().unwrap();
        for (host, origin) in [
            ("[broken", None),
            ("evil.test:1422", None),
            ("127.0.0.1:1422", Some("http://evil.test")),
            ("127.0.0.1:1423", None),
            ("user@127.0.0.1:1422", None),
            ("user:pass@127.0.0.1:1422", None),
            ("127.0.0.1:1422/private", None),
            ("127.0.0.1:1422/?query", None),
            ("127.0.0.1:1422/#fragment", None),
        ] {
            assert!(!allowed(&request(host, origin), address));
        }
        assert!(!allowed(&Request::new(()), address));
    }
}
