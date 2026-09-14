//! Native fixture-file admission experiment. No endpoint discovery or connection.
#[cfg(windows)]
#[path = "../record_native.rs"]
mod native;
#[cfg(windows)]
#[allow(dead_code)]
#[path = "../record_value.rs"]
mod record_value;

#[cfg(windows)]
fn main() {
    use sha2::{Digest, Sha256};
    let arguments: Vec<_> = std::env::args_os().collect();
    let result = if arguments.len() == 5 && arguments[1] == "--decode-record" {
        (|| {
            let endpoint = arguments[3].to_str().ok_or(())?;
            let profile = arguments[4].to_str().ok_or(())?;
            let name = record_value::Record::filename(endpoint)?;
            let bytes = native::read(std::path::Path::new(&arguments[2]), &name)?;
            let record = record_value::Record::decode(&bytes)?;
            Ok(record.selected(endpoint, profile)?.to_string())
        })()
    } else if arguments.len() == 2 {
        native::read(std::path::Path::new(&arguments[1]), "fixture-record")
            .map(|bytes| format!("{} {:x}", bytes.len(), Sha256::digest(&bytes)))
    } else {
        Err(())
    };
    match result {
        Ok(output) => println!("{output}"),
        Err(()) => {
            eprintln!("record admission failed");
            std::process::exit(1);
        }
    }
}
#[cfg(not(windows))]
fn main() {
    eprintln!("Windows record admission unavailable");
    std::process::exit(1);
}
