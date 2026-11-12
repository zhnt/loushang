//! Exercise the shared Workspace API against a configured AppHost.
use loushang_app_client::{AppClient, AppTarget, WorkspaceRequest, WorkspaceResult};
use std::{path::Path, time::Duration};

fn run(arguments: &[String]) -> Result<(), ()> {
    let (forwarded_port, arguments) = match arguments {
        [flag, port, rest @ ..] if flag == "--tunnel-port" => {
            (Some(port.parse().map_err(|_| ())?), rest)
        }
        _ => (None, arguments),
    };
    let (config, operation) = match arguments {
        [config, action] if action == "list" => (config, WorkspaceRequest::List),
        [config, action, path] if action == "register" => {
            (config, WorkspaceRequest::Register(path))
        }
        [config, action, path] if action == "open" => (config, WorkspaceRequest::Open(path)),
        _ => return Err(()),
    };
    let root = Path::new(config);
    let target = match forwarded_port {
        Some(forwarded_port) => AppTarget::Tunnel {
            credential_root: root,
            forwarded_port,
        },
        None => AppTarget::Local(root),
    };
    let client = AppClient::default();
    let result = client
        .workspace(target, Duration::from_secs(5), operation)
        .map_err(|_| eprintln!("workspace connection failed: {}", client.failure_code()))?;
    match result {
        WorkspaceResult::Accepted(directory) => {
            println!("{}", serde_json::to_string(&directory).map_err(|_| ())?);
            Ok(())
        }
        WorkspaceResult::Rejected(code) => {
            eprintln!("workspace rejected: {code}");
            Err(())
        }
    }
}

fn main() {
    if run(&std::env::args().skip(1).collect::<Vec<_>>()).is_err() {
        eprintln!("workspace probe failed");
        std::process::exit(1);
    }
}
