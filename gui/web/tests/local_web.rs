use serde_json::{json, Value};
use std::{
    path::Path,
    process::{Child, Command, Stdio},
    time::Duration,
};
struct Process(Child);
impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
async fn start(root: &Path) -> (Process, String) {
    let mut child = Process(
        Command::new(env!("CARGO_BIN_EXE_loushang-web"))
            .env("LOUSHANG_HOME", root)
            .env("LOUSHANG_GUI_PYTHON", root.join("missing-python"))
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap(),
    );
    let endpoint = root.join("state/web/endpoint.json");
    for _ in 0..100 {
        assert!(
            child.0.try_wait().unwrap().is_none(),
            "Web process exited before listening"
        );
        if let Ok(bytes) = std::fs::read(&endpoint) {
            let value: Value = serde_json::from_slice(&bytes).unwrap();
            if value["pid"] == child.0.id() {
                return (child, value["url"].as_str().unwrap().into());
            }
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    panic!("Web process did not publish endpoint");
}
#[tokio::test]
async fn browser_reads_assets_and_persists_host_state_without_login() {
    let root = tempfile::tempdir().unwrap();
    let assets = root.path().join("web");
    std::fs::create_dir(&assets).unwrap();
    std::fs::write(assets.join("index.html"), "<main>Local Loushang</main>").unwrap();
    std::fs::write(assets.join("app.js"), "export const ready=true;").unwrap();
    std::fs::write(root.path().join("private.txt"), "private").unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink(root.path().join("private.txt"), assets.join("escape.txt")).unwrap();
    std::fs::write(
        root.path().join("host.json"),
        json!({"web":{"port":0,"dist":assets}}).to_string(),
    )
    .unwrap();
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(10))
        .build()
        .unwrap();
    for attempt in 0..2 {
        let (mut process, url) = start(root.path()).await;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(root.path().join("state"))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o077,
                0
            );
        }
        let reused = tokio::process::Command::new(env!("CARGO_BIN_EXE_loushang-web"))
            .arg("--ensure")
            .env("LOUSHANG_HOME", root.path())
            .output()
            .await
            .unwrap();
        assert!(
            reused.status.success(),
            "{}",
            String::from_utf8_lossy(&reused.stderr)
        );
        assert_eq!(String::from_utf8(reused.stdout).unwrap().trim(), url);
        let page = client.get(&url).send().await.unwrap();
        assert_eq!(page.status(), 200);
        assert!(page.headers().get("set-cookie").is_none());
        assert_eq!(page.text().await.unwrap(), "<main>Local Loushang</main>");
        let js = client.get(format!("{url}/app.js")).send().await.unwrap();
        assert_eq!(js.headers()["content-type"], "text/javascript");
        assert_eq!(
            client
                .get(&url)
                .header("Host", "attacker.invalid")
                .send()
                .await
                .unwrap()
                .status(),
            403
        );
        #[cfg(unix)]
        assert_eq!(
            client
                .get(format!("{url}/escape.txt"))
                .send()
                .await
                .unwrap()
                .status(),
            403
        );
        let api = format!("{url}/api/loushang");
        assert_eq!(
            client
                .post(&api)
                .json(&json!({}))
                .send()
                .await
                .unwrap()
                .status(),
            403
        );
        assert_eq!(
            client
                .post(&api)
                .header("X-Loushang-Client", "1")
                .header("Origin", "http://evil.test")
                .json(&json!({}))
                .send()
                .await
                .unwrap()
                .status(),
            403
        );
        assert_eq!(
            client
                .post(&api)
                .header("X-Loushang-Client", "1")
                .json(&json!([]))
                .send()
                .await
                .unwrap()
                .status(),
            400
        );
        assert_eq!(
            client
                .post(&api)
                .header("X-Loushang-Client", "1")
                .body(vec![b'x'; 1_000_001])
                .send()
                .await
                .unwrap()
                .status(),
            413
        );
        let request = if attempt == 0 {
            json!({"operation":"preferences","scope":"mux:web","action":"pin","session":"one"})
        } else {
            json!({"operation":"preferences","scope":"mux:web"})
        };
        let value: Value = client
            .post(&api)
            .header("X-Loushang-Client", "1")
            .json(&request)
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        assert_eq!(value["result"]["pinned"], json!(["one"]));
        assert!(root
            .path()
            .join("data/client-preferences.sqlite3")
            .is_file());
        assert!(!root.path().join("auth").exists());
        let stopped = client
            .post(&api)
            .header("X-Loushang-Client", "1")
            .json(&json!({"operation":"shutdown-adapter"}))
            .send()
            .await
            .unwrap();
        assert_eq!(stopped.status(), 200);
        for _ in 0..100 {
            if process.0.try_wait().unwrap().is_some() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        assert!(process.0.try_wait().unwrap().unwrap().success());
    }
}

#[tokio::test]
async fn ensure_starts_one_listener_for_concurrent_clients() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("host.json"), r#"{"web":{"port":0}}"#).unwrap();
    let launch = || {
        let mut command = tokio::process::Command::new(env!("CARGO_BIN_EXE_loushang-web"));
        command.arg("--ensure").env("LOUSHANG_HOME", root.path());
        command.output()
    };
    let (first, second) = tokio::join!(launch(), launch());
    let first = first.unwrap();
    let second = second.unwrap();
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let url = String::from_utf8(first.stdout).unwrap().trim().to_owned();
    #[cfg(target_os = "linux")]
    {
        let endpoint: Value = serde_json::from_slice(
            &std::fs::read(root.path().join("state/web/endpoint.json")).unwrap(),
        )
        .unwrap();
        let pid = endpoint["pid"].as_u64().unwrap();
        let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
        let fields: Vec<_> = stat
            .rsplit_once(')')
            .unwrap()
            .1
            .split_whitespace()
            .collect();
        assert_eq!(
            fields[2].parse::<u64>().unwrap(),
            pid,
            "Web must outlive its launcher's process group"
        );
    }
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(10))
        .build()
        .unwrap();
    let shutdown = client
        .post(format!("{url}/api/loushang"))
        .header("X-Loushang-Client", "1")
        .json(&json!({"operation":"shutdown-adapter"}))
        .send()
        .await
        .unwrap();
    assert_eq!(shutdown.status(), 200);
    assert!(
        second.status.success(),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );
    assert_eq!(String::from_utf8(second.stdout).unwrap().trim(), url);
}
