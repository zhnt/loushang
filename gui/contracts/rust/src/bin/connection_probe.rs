//! Windows lifecycle evidence consuming the same native adapter as Tauri.
#[cfg(windows)]
#[allow(dead_code, unused_imports)]
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
        if args.len() != 4 && !(args.len() == 5 && (args[4] == "--attach" || args[4] == "--watch"))
        {
            return Err(());
        }
        let timeout: u64 = args[2].to_str().ok_or(())?.parse().map_err(|_| ())?;
        let cancel: i64 = args[3].to_str().ok_or(())?.parse().map_err(|_| ())?;
        if !(1..=5000).contains(&timeout) || !(-1..=5000).contains(&cancel) {
            return Err(());
        }
        let watch = args.len() == 5 && args[4] == "--watch";
        if watch && cancel <= 0 {
            return Err(());
        }
        let root = std::path::PathBuf::from(&args[1]);
        let attach = args.len() == 5;
        read_worker::ReadWorker::spawn(move |stop| {
            app_client::AppClient::default().run(
                app_client::ConnectionOptions {
                    root: &root,
                    timeout: std::time::Duration::from_millis(timeout),
                    cancel: (cancel >= 0).then(|| std::time::Duration::from_millis(cancel as u64)),
                    attach,
                    mux_name: "gui-fixture",
                    stop: watch.then_some(stop),
                    control_commands: None,
                },
                &mut |_| Ok(()),
            )
        })
        .map_err(|_| ())?
        .wait()
        .map_err(|_| ())
    })();
    match outcome {
        Ok(instance) => {
            if args.len() == 5 && args[4] == "--watch" {
                println!("watch stopped; detached; connection closed; instance={instance}");
            } else if args.len() == 5 {
                println!("attachment snapshots verified; detached; connection closed; instance={instance}");
            } else {
                println!("hello verified; connection closed; instance={instance}");
            }
        }
        Err(()) => {
            eprintln!("connection probe failed");
            std::process::exit(1);
        }
    }
}

#[cfg(not(windows))]
fn main() {
    eprintln!("Windows connection probe unavailable");
    std::process::exit(1);
}
