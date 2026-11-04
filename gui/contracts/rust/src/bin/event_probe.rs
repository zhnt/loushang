//! Observe one validated live event round through the desktop AppClient adapter.
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
    use std::io::Write;

    let args: Vec<_> = std::env::args_os().collect();
    let outcome =
        (|| {
            if args.len() != 4 {
                return Err(());
            }
            let timeout: u64 = args[2].to_str().ok_or(())?.parse().map_err(|_| ())?;
            if !(1..=5000).contains(&timeout) {
                return Err(());
            }
            let mux_name = args[3].to_str().ok_or(())?.to_owned();
            let root = std::path::PathBuf::from(&args[1]);
            read_worker::ReadWorker::spawn(move |stop| {
                let finish = stop.clone();
                app_client::AppClient::default()
                    .run_stream(
                        app_client::ConnectionOptions {
                            root: &root,
                            timeout: std::time::Duration::from_millis(timeout),
                            cancel: None,
                            attach: true,
                            mux_name: &mux_name,
                            stop: Some(stop),
                            control_commands: None,
                        },
                        1,
                        &mut |snapshot| {
                            println!(
                                "{}",
                                serde_json::json!({"type":"initial","payload":snapshot})
                            );
                            std::io::stdout().flush().map_err(|_| ())
                        },
                        &mut |round| {
                            let complete =
                                round.members.iter().flat_map(|member| &member.events).any(
                                    |event| {
                                        event["source"]["kind"].as_str() == Some("turn_completed")
                                    },
                                );
                            println!("{}", serde_json::json!({"type":"round","payload":round}));
                            std::io::stdout().flush().map_err(|_| ())?;
                            if complete {
                                finish.request();
                            }
                            Ok(())
                        },
                        &mut |_| Ok(()),
                        &mut || Ok(true),
                    )
                    .map(|_| ())
            })
            .map_err(|_| ())?
            .wait()
            .map_err(|_| ())
        })();
    if outcome.is_err() {
        eprintln!("event probe failed");
        std::process::exit(1);
    }
}

#[cfg(not(windows))]
fn main() {
    eprintln!("Windows event probe unavailable");
    std::process::exit(1);
}
