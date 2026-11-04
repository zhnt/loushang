//! Submit one deterministic turn through the production desktop control path.
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
    let outcome = (|| {
        if args.len() != 7 {
            return Err(());
        }
        let timeout: u64 = args[2].to_str().ok_or(())?.parse().map_err(|_| ())?;
        if !(1..=5000).contains(&timeout) {
            return Err(());
        }
        let root = std::path::PathBuf::from(&args[1]);
        let mux_name = args[3].to_str().ok_or(())?.to_owned();
        let session_id = args[4].to_str().ok_or(())?.to_owned();
        let submission_id = args[5].to_str().ok_or(())?.to_owned();
        let text = args[6].to_str().ok_or(())?.to_owned();
        read_worker::ReadWorker::spawn(move |stop| {
                let finish = stop.clone();
                let (commands, command_receiver) = std::sync::mpsc::channel();
                let pending: std::cell::RefCell<
                    Option<std::sync::mpsc::Receiver<Result<app_client::ControlResult, ()>>>,
                > = std::cell::RefCell::new(None);
                let mut submitted = false;
                app_client::AppClient::default()
                    .run_stream(
                        app_client::ConnectionOptions {
                            root: &root,
                            timeout: std::time::Duration::from_millis(timeout),
                            cancel: None,
                            attach: true,
                            mux_name: &mux_name,
                            stop: Some(stop),
                            control_commands: Some(&command_receiver),
                        },
                        1,
                        &mut |_| {
                            let receive = pending.borrow_mut().take().ok_or(())?;
                            let result = receive
                                .recv_timeout(std::time::Duration::from_secs(6))
                                .map_err(|_| ())??;
                            let (accepted, reason) = match result {
                                app_client::ControlResult::Accepted => (true, None),
                                app_client::ControlResult::Missing => {
                                    (false, Some("missing".to_owned()))
                                }
                                app_client::ControlResult::Rejected(reason) => {
                                    (false, Some(reason))
                                }
                            };
                            println!(
                                "{}",
                                serde_json::json!({"type":"control","accepted":accepted,"reason":reason})
                            );
                            std::io::stdout().flush().map_err(|_| ())?;
                            if accepted { Ok(()) } else { Err(()) }
                        },
                        &mut |round| {
                            let terminal =
                                round.members.iter().flat_map(|member| &member.events).any(
                                    |event| {
                                        matches!(
                                            event["source"]["kind"].as_str(),
                                            Some("turn_completed") | Some("turn_interrupted")
                                        )
                                    },
                                );
                            println!("{}", serde_json::json!({"type":"round","payload":round}));
                            std::io::stdout().flush().map_err(|_| ())?;
                            if terminal {
                                finish.request();
                            }
                            Ok(())
                        },
                        &mut |authority| {
                            let Some(_) = authority else {
                                return Ok(());
                            };
                            if submitted {
                                return Err(());
                            }
                            submitted = true;
                            let (reply, receive) = std::sync::mpsc::sync_channel(1);
                            commands
                                .send(app_client::ControlCommand::Submit {
                                    session_id: session_id.clone(),
                                    submission_id: submission_id.clone(),
                                    text: text.clone(),
                                    reply,
                                })
                                .map_err(|_| ())?;
                            pending.replace(Some(receive));
                            Ok(())
                        },
                        &mut || Ok(true),
                    )
                    .map(|_| ())
            })
            .map_err(|_| ())?
            .wait()
            .map_err(|_| ())
    })();
    if outcome.is_err() {
        eprintln!("control probe failed");
        std::process::exit(1);
    }
}

#[cfg(not(windows))]
fn main() {
    std::process::exit(2);
}
