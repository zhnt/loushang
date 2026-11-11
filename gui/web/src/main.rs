use loushang_web::{config, Result};
#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("Loushang Web: {error}");
        std::process::exit(1);
    }
}
async fn run() -> Result<()> {
    let (dist, external, ensure) = arguments(std::env::args().skip(1))?;
    let root = config::root()?;
    if ensure {
        println!("{}", loushang_web::ensure(root).await?);
        Ok(())
    } else {
        loushang_web::serve(root, dist, &external).await
    }
}
fn arguments(
    mut args: impl Iterator<Item = String>,
) -> Result<(Option<std::path::PathBuf>, Vec<String>, bool)> {
    let mut dist = None;
    let mut external = Vec::new();
    let mut ensure = false;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--ensure" => ensure = true,
            "--dist" => dist = Some(args.next().ok_or("--dist requires a path")?.into()),
            "--external-host" => {
                external.push(arg);
                for _ in 0..3 {
                    external
                        .push(args.next().ok_or(
                            "--external-host requires workspace, connection root and mux",
                        )?);
                }
            }
            _ => return Err(format!("unknown option: {arg}").into()),
        }
    }
    Ok((dist, external, ensure))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cli_preserves_asset_path_and_external_host_arguments() {
        let (dist, external, ensure) = arguments(
            [
                "--dist",
                "/assets",
                "--external-host",
                "/work",
                "/records",
                "mux",
            ]
            .map(String::from)
            .into_iter(),
        )
        .unwrap();
        assert_eq!(dist.unwrap(), std::path::PathBuf::from("/assets"));
        assert_eq!(
            external,
            vec!["--external-host", "/work", "/records", "mux"]
        );
        assert!(!ensure);
        assert!(
            arguments(["--ensure"].map(String::from).into_iter())
                .unwrap()
                .2
        );
        for args in [
            vec!["--unknown"],
            vec!["--dist"],
            vec!["--external-host", "/work"],
        ] {
            assert!(arguments(args.into_iter().map(String::from)).is_err());
        }
    }
}
