use std::{
    env, io,
    process::{self, Command},
};

fn launch() -> io::Result<i32> {
    let executable = env::current_exe()?;
    let directory = executable
        .parent()
        .expect("executable has a parent directory");
    let status = Command::new(directory.join("runtime").join("python.exe"))
        .args(["-I", "-m", "loushang.coding.cli.mux"])
        .args(env::args_os().skip(1))
        .status()?;
    Ok(status.code().unwrap_or(1))
}

fn main() {
    match launch() {
        Ok(code) => process::exit(code),
        Err(error) => {
            eprintln!("Could not start loushang-mux: {error}");
            process::exit(1);
        }
    }
}
