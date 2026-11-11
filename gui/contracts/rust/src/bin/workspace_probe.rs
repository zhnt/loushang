//! Exercise the shared Workspace API against a configured AppHost.
use loushang_app_client::{AppClient, WorkspaceRequest, WorkspaceResult};
use std::{path::Path, time::Duration};

fn run(arguments: &[String]) -> Result<(), ()> {
    let (config, operation) = match arguments {
        [config, action] if action == "list" => (config, WorkspaceRequest::List),
        [config, action, path] if action == "register" => {
            (config, WorkspaceRequest::Register(path))
        }
        [config, action, path] if action == "open" => (config, WorkspaceRequest::Open(path)),
        _ => return Err(()),
    };
    match AppClient::default().workspace(Path::new(config), Duration::from_secs(5), operation)? {
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
