//! Native Linux package entry so file managers execute it rather than edit it.
use std::env;
use std::os::unix::process::CommandExt;
use std::process::{self, Command};

fn launch() -> Result<(), Box<dyn std::error::Error>> {
    let executable = env::current_exe()?;
    let package = executable.parent().ok_or("missing package directory")?;
    // Preserve argument boundaries, including spaces/non-UTF-8 paths. Resolve
    // resources from the executable, never the file manager's working directory.
    let error = Command::new(package.join("bin/harness-gui"))
        .env("LOUSHANG_MUX", package.join("loushang-mux"))
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .args(env::args_os().skip(1))
        .exec();
    Err(error.into())
}

fn main() {
    if let Err(error) = launch() {
        eprintln!("Loushang could not start: {error}");
        process::exit(1);
    }
}
