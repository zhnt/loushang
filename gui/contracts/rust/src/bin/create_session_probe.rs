//! Create one Session through the production desktop control path, then reattach.
#[allow(dead_code, unused_imports)]
#[path = "../../../../src-tauri/src/app_client/mod.rs"]
mod app_client;
#[path = "../../../../src-tauri/src/read_stop.rs"]
mod read_stop;
#[allow(dead_code)]
#[path = "../../../../src-tauri/src/read_worker.rs"]
mod read_worker;

fn main() {
    use std::cell::{Cell, RefCell};

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
        let source_session_id = args[4].to_str().ok_or(())?.to_owned();
        let continuity_id = args[5].to_str().ok_or(())?.to_owned();
        let title = args[6].to_str().ok_or(())?.to_owned();
        let (commands, command_receiver) = std::sync::mpsc::channel();
        let pending = RefCell::new(None);
        let submitted = Cell::new(false);
        let first = app_client::AppClient::default().run_stream(
            app_client::ConnectionOptions {
                root: &root,
                timeout: std::time::Duration::from_millis(timeout),
                cancel: None,
                attach: true,
                mux_name: &mux_name,
                stop: None,
                control_commands: Some(&command_receiver),
            },
            1,
            &mut |_| Ok(()),
            &mut |_| Err(()),
            &mut |authority| {
                if authority.is_none() || submitted.replace(true) {
                    return Ok(());
                }
                let (reply, receive) = std::sync::mpsc::sync_channel(1);
                commands
                    .send(app_client::ControlCommand::CreateSession {
                        source_session_id: source_session_id.clone(),
                        continuity_id: continuity_id.clone(),
                        title: title.clone(),
                        reply,
                    })
                    .map_err(|_| ())?;
                pending.replace(Some(receive));
                Ok(())
            },
            &mut || Ok(true),
        );
        if first.is_ok() {
            return Err(());
        }
        let created = match pending
            .borrow_mut()
            .take()
            .ok_or(())?
            .recv_timeout(std::time::Duration::from_secs(6))
            .map_err(|_| ())??
        {
            app_client::CreateSessionResult::Accepted(session_id) => session_id,
            app_client::CreateSessionResult::Rejected(_) => return Err(()),
        };
        let mut observed = false;
        app_client::AppClient::default().run(
            app_client::ConnectionOptions {
                root: &root,
                timeout: std::time::Duration::from_millis(timeout),
                cancel: None,
                attach: true,
                mux_name: &mux_name,
                stop: None,
                control_commands: None,
            },
            &mut |snapshot| {
                observed = snapshot
                    .sessions
                    .iter()
                    .any(|session| session["source"]["source"]["identity"]["sessionId"] == created);
                Ok(())
            },
        )?;
        if !observed {
            return Err(());
        }
        println!(
            "{}",
            serde_json::json!({"type":"created","sessionId":created})
        );
        Ok(())
    })();
    if outcome.is_err() {
        eprintln!("create Session probe failed");
        std::process::exit(1);
    }
}
