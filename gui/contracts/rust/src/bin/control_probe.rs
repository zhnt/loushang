//! Submit one deterministic turn through the production desktop control path.
#[allow(dead_code, unused_imports)]
#[path = "../../../../src-tauri/src/app_client/mod.rs"]
mod app_client;
#[path = "../probe_completion.rs"]
mod probe_completion;
#[path = "../../../../src-tauri/src/read_stop.rs"]
mod read_stop;
#[allow(dead_code)]
#[path = "../../../../src-tauri/src/read_worker.rs"]
mod read_worker;

fn main() {
    use std::io::Write;

    let args: Vec<_> = std::env::args_os().collect();
    let outcome = (|| {
        if args.len() != 7 && args.len() != 8 {
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
        let action = args
            .get(7)
            .and_then(|v| v.to_str())
            .unwrap_or("submit")
            .to_owned();
        if !["submit", "submit-detach", "find", "interrupt"].contains(&action.as_str()) {
            return Err(());
        }
        let completion_text = text.clone();
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
                        prepare_default_session: false,
                            root: &root,
                            timeout: std::time::Duration::from_millis(timeout),
                            cancel: None,
                            attach: true,
                            mux_name: &mux_name,
                            stop: Some(stop),
                            control_commands: Some(&command_receiver),
                        },
                        1,
                        &mut |snapshot| {
                            println!("{}", serde_json::json!({"type":"initial","payload":snapshot}));
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
                            let terminal = (action != "submit" && round.sessions.iter().any(|value| {
                                value["executions"]["active"].is_null()
                                    && matches!(value["executions"]["latestTerminal"]["status"].as_str(),
                                        Some("succeeded" | "interrupted" | "failed"))
                            })) || (action == "submit" && probe_completion::completed(&round.sessions, &completion_text));
                            println!("{}", serde_json::json!({"type":"round","payload":round}));
                            std::io::stdout().flush().map_err(|_| ())?;
                            if terminal || (action == "submit-detach" && round.sessions.iter().any(|value| value["executions"]["active"]["status"] == "running")) {
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
                            let command = match action.as_str() {
                                "find" => app_client::ControlCommand::FindSubmission {
                                    session_id: session_id.clone(), submission_id: submission_id.clone(), reply },
                                "interrupt" => app_client::ControlCommand::Interrupt {
                                    session_id: session_id.clone(), execution_id: text.clone(), reply },
                                _ => app_client::ControlCommand::Submit {
                                    session_id: session_id.clone(), submission_id: submission_id.clone(), text: text.clone(), reply },
                            };
                            commands.send(command).map_err(|_| ())?;
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
