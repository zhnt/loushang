//! Pipe-only interoperability entrypoint using public fixture credentials.
#[path = "../../../../src-tauri/src/app_client/transport_auth.rs"]
mod transport_auth;
use std::io;
fn run() -> Result<(), ()> {
    let record = transport_auth::record_value::Record::decode(include_bytes!(
        "../../../fixtures/local-record.json"
    ))?;
    record.selected("workspace", "local-detachable-execution/v1")?;
    let frames = transport_auth::Frames::new(io::stdin().lock(), io::stdout().lock());
    let mut channel = transport_auth::Channel::authenticate(frames, &record)?;
    for _ in 0..2 {
        let payload = channel.receive()?;
        channel.send(&payload)?;
    }
    Ok(())
}
fn main() {
    if run().is_err() {
        eprintln!("authentication probe failed");
        std::process::exit(1);
    }
}
