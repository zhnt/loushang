use loushang_web::{config, Result};
#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("Loushang Web: {error}");
        std::process::exit(1);
    }
}
async fn run() -> Result<()> {
    let (dist, ensure) = arguments(std::env::args().skip(1))?;
    let root = config::root()?;
    if ensure {
        println!("{}", loushang_web::ensure(root).await?);
        Ok(())
    } else {
        loushang_web::serve(root, dist).await
    }
}
fn arguments(mut args: impl Iterator<Item = String>) -> Result<(Option<std::path::PathBuf>, bool)> {
    let mut dist = None;
    let mut ensure = false;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--ensure" => ensure = true,
            "--dist" => dist = Some(args.next().ok_or("--dist requires a path")?.into()),
            _ => return Err(format!("unknown option: {arg}").into()),
        }
    }
    Ok((dist, ensure))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cli_accepts_assets_and_rejects_workspace_first_launch() {
        let (dist, ensure) =
            arguments(["--dist", "/assets"].map(String::from).into_iter()).unwrap();
        assert_eq!(dist.unwrap(), std::path::PathBuf::from("/assets"));
        assert!(!ensure);
        assert!(
            arguments(["--ensure"].map(String::from).into_iter())
                .unwrap()
                .1
        );
        for args in [
            vec!["--unknown"],
            vec!["--dist"],
            vec!["--external-host", "/work", "/records", "mux"],
        ] {
            assert!(arguments(args.into_iter().map(String::from)).is_err());
        }
    }
}
