//! Redacted initial-snapshot evidence consuming the desktop AppClient adapter.
#[cfg(windows)]
#[path = "../../../../src-tauri/src/app_client/mod.rs"]
mod app_client;
#[cfg(windows)]
#[path = "../../../../src-tauri/src/read_stop.rs"]
mod read_stop;
#[cfg(windows)]
#[allow(dead_code)]
#[path = "../../../../src-tauri/src/read_worker.rs"]
mod read_worker;

#[cfg(windows)]
fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    let outcome = (|| {
        if args.len() != 4 {
            return Err(());
        }
        let timeout: u64 = args[2].to_str().ok_or(())?.parse().map_err(|_| ())?;
        if !(1..=5000).contains(&timeout) {
            return Err(());
        }
        let mux_name = args[3].to_str().ok_or(())?.to_owned();
        let root = std::path::PathBuf::from(&args[1]);
        let (publish, receive) = std::sync::mpsc::channel();
        read_worker::ReadWorker::spawn(move |_| {
            app_client::AppClient::default().run(
                app_client::ConnectionOptions {
                    root: &root,
                    timeout: std::time::Duration::from_millis(timeout),
                    cancel: None,
                    attach: true,
                    mux_name: &mux_name,
                    stop: None,
                },
                &mut |snapshot| publish.send(snapshot).map_err(|_| ()),
            )
        })
        .map_err(|_| ())?
        .wait()
        .map_err(|_| ())?;
        let snapshot = receive.try_recv().map_err(|_| ())?;
        serde_json::to_string(&snapshot).map_err(|_| ())
    })();
    match outcome {
        Ok(snapshot) => println!("{snapshot}"),
        Err(()) => {
            eprintln!("snapshot probe failed");
            std::process::exit(1);
        }
    }
}

#[cfg(not(windows))]
fn main() {
    eprintln!("Windows snapshot probe unavailable");
    std::process::exit(1);
}
