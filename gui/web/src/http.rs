use crate::{backend::Backend, policy};
use http_body_util::{BodyExt, Full, Limited};
use hyper::{
    body::{Bytes, Incoming},
    Method, Request, Response, StatusCode,
};
use std::{convert::Infallible, net::SocketAddr, path::PathBuf, sync::Arc};
use tokio::sync::watch;

pub struct Service {
    pub address: SocketAddr,
    pub dist: Option<PathBuf>,
    pub backend: Backend,
    pub stop: watch::Sender<bool>,
}
fn response(status: StatusCode, body: impl Into<Bytes>, mime: &str) -> Response<Full<Bytes>> {
    Response::builder()
        .status(status)
        .header("content-type", mime)
        .header("cache-control", "no-store")
        .header("x-content-type-options", "nosniff")
        .header("content-security-policy", "frame-ancestors 'none'")
        .body(Full::new(body.into()))
        .expect("constant response headers")
}
fn failure(status: StatusCode, code: &str) -> Response<Full<Bytes>> {
    response(
        status,
        serde_json::json!({"error":code}).to_string(),
        "application/json",
    )
}
impl Service {
    pub async fn handle(
        self: Arc<Self>,
        request: Request<Incoming>,
    ) -> Result<Response<Full<Bytes>>, Infallible> {
        let reply = if !policy::allowed(&request, self.address) {
            failure(StatusCode::FORBIDDEN, "forbidden")
        } else if request.method() == Method::GET {
            self.asset(request.uri().path()).await
        } else if request.method() == Method::POST && request.uri().path() == "/api/loushang" {
            self.api(request).await
        } else {
            failure(StatusCode::NOT_FOUND, "not_found")
        };
        Ok(reply)
    }
    async fn api(&self, request: Request<Incoming>) -> Response<Full<Bytes>> {
        if request
            .headers()
            .get("x-loushang-client")
            .and_then(|v| v.to_str().ok())
            != Some("1")
        {
            return failure(StatusCode::FORBIDDEN, "forbidden");
        }
        let Ok(body) = Limited::new(request.into_body(), 1_000_000).collect().await else {
            return failure(StatusCode::PAYLOAD_TOO_LARGE, "request_too_large");
        };
        let Ok(value) =
            serde_json::from_slice::<serde_json::Map<String, serde_json::Value>>(&body.to_bytes())
        else {
            return failure(StatusCode::BAD_REQUEST, "invalid_request");
        };
        if value.get("operation").and_then(|v| v.as_str()) == Some("shutdown-adapter") {
            let _ = self.stop.send(true);
            return response(StatusCode::OK, "{\"result\":{}}", "application/json");
        }
        match self.backend.call(value.into()).await {
            Ok(reply) => response(
                if reply.get("error").is_some() {
                    StatusCode::SERVICE_UNAVAILABLE
                } else {
                    StatusCode::OK
                },
                reply.to_string(),
                "application/json",
            ),
            Err(_) => failure(StatusCode::SERVICE_UNAVAILABLE, "host_request_failed"),
        }
    }
    async fn asset(&self, path: &str) -> Response<Full<Bytes>> {
        let Some(root) = &self.dist else {
            return failure(StatusCode::NOT_FOUND, "web_assets_unavailable");
        };
        let file = root.join(path.trim_start_matches('/'));
        let file = if file.is_dir() {
            file.join("index.html")
        } else {
            file
        };
        let Ok(file) = tokio::fs::canonicalize(file).await else {
            return failure(StatusCode::NOT_FOUND, "not_found");
        };
        if !file.starts_with(root) {
            return failure(StatusCode::FORBIDDEN, "forbidden");
        }
        match tokio::fs::read(&file).await {
            Ok(bytes) => response(
                StatusCode::OK,
                bytes,
                mime(file.extension().and_then(|x| x.to_str()).unwrap_or("")),
            ),
            Err(_) => failure(StatusCode::NOT_FOUND, "not_found"),
        }
    }
}
fn mime(extension: &str) -> &'static str {
    const TYPES: &[(&str, &str)] = &[
        ("html", "text/html; charset=utf-8"),
        ("js", "text/javascript"),
        ("mjs", "text/javascript"),
        ("css", "text/css"),
        ("json", "application/json"),
        ("svg", "image/svg+xml"),
        ("png", "image/png"),
        ("ico", "image/x-icon"),
        ("woff2", "font/woff2"),
        ("woff", "font/woff"),
    ];
    TYPES
        .iter()
        .find(|(suffix, _)| *suffix == extension)
        .map_or("application/octet-stream", |(_, mime)| mime)
}
