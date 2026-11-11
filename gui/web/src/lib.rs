mod backend;
pub mod config;
mod http;
pub mod policy;
mod startup;
use hyper::{server::conn::http1, service::service_fn};
use hyper_util::rt::TokioIo;
pub use startup::ensure;
use std::{path::PathBuf, sync::Arc, time::Duration};
use tokio::{
    net::TcpListener,
    sync::{watch, Semaphore},
    task::JoinSet,
};
pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Result<T> = std::result::Result<T, Error>;

pub async fn serve(root: PathBuf, dist: Option<PathBuf>, external: &[String]) -> Result<()> {
    let (state, _lease) = owner(&root)?;
    let config = config::Config::read(&root)?;
    let listener = TcpListener::bind(config.address()).await?;
    let address = listener.local_addr()?;
    let assets = assets(dist.or(config.dist))?;
    let (stop, stopped) = watch::channel(false);
    let service = Arc::new(http::Service {
        address,
        dist: assets,
        backend: backend::Backend::spawn(external)?,
        stop,
    });
    publish(&state, address)?;
    accept(listener, stopped, service.clone()).await?;
    service.backend.close().await;
    Ok(())
}

async fn accept(
    listener: TcpListener,
    mut stopped: watch::Receiver<bool>,
    service: Arc<http::Service>,
) -> Result<()> {
    let mut workers = JoinSet::new();
    let slots = Arc::new(Semaphore::new(32));
    loop {
        tokio::select! {
            _ = stopped.changed() => break,
            _ = tokio::signal::ctrl_c() => break,
            Some(_) = workers.join_next(), if !workers.is_empty() => {},
            accepted = listener.accept() => {
                let (stream, _) = accepted?;
                let Ok(permit) = slots.clone().try_acquire_owned() else { continue; };
                let service = service.clone();
                workers.spawn(async move {
                    let _permit = permit;
                    let connection = http1::Builder::new().keep_alive(false)
                        .serve_connection(TokioIo::new(stream), service_fn(move |request| service.clone().handle(request)));
                    let _ = tokio::time::timeout(Duration::from_secs(80), connection).await;
                });
            }
        }
    }
    while workers.join_next().await.is_some() {}
    Ok(())
}

fn assets(selected: Option<PathBuf>) -> Result<Option<PathBuf>> {
    let packaged = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(|parent| parent.join("../web")));
    let path = selected
        .or_else(|| packaged.filter(|path| path.is_dir()))
        .or_else(|| {
            let source = config::source_root().join("gui/dist");
            source.is_dir().then_some(source)
        });
    Ok(path.map(std::fs::canonicalize).transpose()?)
}
fn publish(state: &std::path::Path, address: std::net::SocketAddr) -> Result<()> {
    let endpoint = serde_json::json!({"url":format!("http://{address}"), "pid":std::process::id(), "implementation":"gui-rust/v1"});
    std::fs::write(state.join("endpoint.tmp"), endpoint.to_string())?;
    std::fs::rename(state.join("endpoint.tmp"), state.join("endpoint.json"))?;
    println!("Loushang: http://{address}");
    Ok(())
}

fn owner(root: &std::path::Path) -> Result<(PathBuf, rusqlite::Connection)> {
    let state = config::state(root)?;
    let lease = rusqlite::Connection::open(state.join("owner.sqlite3"))?;
    lease.execute_batch("BEGIN IMMEDIATE")?;
    Ok((state, lease))
}
