# Standalone Rust desktop client

Source base `lane/gui` at `d84d7a19d`. The reviewed implementation is the
working diff on `feature/gui-rust-client`. Native verification used Linux x86-64.

## Work log

1. Created an isolated task worktree to preserve the integration lane and the
   earlier packaging experiment. Ran the old executable with an unusable
   `PATH` and Python path. Its connection list failed and a Host error dialog
   prevented opening Settings.
2. Replaced the desktop Python bridge with Rust connection settings and HTTP
   routing. The desktop uses the existing v1 connection directory and Host API.
   Selection uses the existing SQLite writer lock and atomic replacement to
   preserve concurrent browser updates and other configuration fields.
3. Split desktop Vite mode from browser development so that building and
   running the desktop require no interpreter. Preserved the native explicit
   AppClient attachment path for existing callers.
4. Built the Tauri release and copied just its executable into an isolated GUI
   directory as `loushang-gui`. Ran with an unusable `PATH`, an unusable Python
   helper path and a separate settings directory. The native window opened
   Settings while the local Host was unavailable. Started a separate Host and
   used the real tray to select its saved HTTP endpoint in the same window.
   GUI session creation passed. The TUI attached and detached, and a browser
   loaded the production `dist` and created a session on the same Host. The
   Host was still running after the clients exited. Stopped the test Host.
5. Ran `npm --prefix gui run check:full` (118 frontend tests plus Rust checks),
   `cargo test --lib` (34 tests), and two focused Playwright cases. Scoped
   `ub-mode` complexity checks found each changed Rust function at or below 9.
   The existing `LocalHostGate` component remains complex (80 in this scan).
   The 0.8 structural duplication scan returned no candidates. A scoped mutation
   weakened the URL query guard and the Rust regression test caught it.

## Scope review

Codex, the implementing agent, reviewed and accepts the GUI client boundary in
the above working diff. The desktop selects a connection and sends requests.
The Host continues to own sessions and process lifecycle. The shared settings
schema and HTTP operations are reused, and the real-process test exercised
configuration selection and session creation. The local gateway is started
separately from the desktop. The existing full `.deb` launcher relies on the
previous GUI to start its HTTP adapter, so it needs launcher integration before
using this standalone GUI in a new full package. The verification covers a local
desktop and an HTTP Host on loopback. Windows builds, network deployments, and
system service integration remain outside this verification.
