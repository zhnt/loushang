# GUI smoke readiness — 2026-11-06

Delivery objective: measure how far `lane/gui` is from a working GUI, using an
isolated task worktree. Baseline: `5208ee256`; task branch:
`feature/gui-smoke-readiness`. No product implementation or CI gates changed.

## Environment and observed checks

Ubuntu 26.10, x86_64, Node 24.22.2, npm 11.19.1, project-selected Rust/Cargo
1.98.1. GTK 3.24.52 and WebKitGTK 2.52.6 are installed. The shell's default
Rust is newer; the GUI commands correctly select the pinned toolchain.

Commands below run from the task worktree root. Child-process checks were run
outside the managed sandbox: the first sandboxed doctor attempt returned
`spawnSync ... EPERM`; the unrestricted retry passed. This was an execution
environment restriction, not a GUI defect.

| Check | Observed result |
| --- | --- |
| `npm --prefix gui ci --no-audit --no-fund` | Passed; 194 packages installed from the lockfile. npm reported an unapproved optional SWC postinstall; subsequent checks passed without approving it. |
| `npm --prefix gui run doctor` | Passed with the pinned versions and Linux host. |
| `npm --prefix gui run check:full` | Passed: TypeScript, production Web build, 14 test files / 87 tests, Rust formatting, Clippy with warnings denied, and Cargo check, both default and fixture-bridge configurations. This command does not execute Rust unit tests. |
| `npm --prefix gui run check:i18n` | Passed: generated types, lint, status and resource completeness. |
| `npm --prefix gui run check:contract` | Passed: 69 accepted and 107 rejected Python → Rust → TypeScript vectors. Offline sampled compatibility, not AppHost integration. |
| `npm --prefix gui run test:layout:install` | Passed; Playwright used its Ubuntu 26.04 fallback on this Ubuntu 26.10 host. |
| `npm --prefix gui run test:layout` | Passed: all 23 tests in 37.6 seconds. Covers layout, language persistence, sidebar and simulated desktop menus/history. |
| `npm --prefix gui run build` | Passed in 2m 19s; produced `gui/src-tauri/target/release/harness-gui`. |
| `timeout --signal=TERM 20s gui/src-tauri/target/release/harness-gui` | Process remained alive for 20 seconds with empty stdout/stderr, then timeout terminated it (124). This is process-start evidence only, not rendered-window or normal-close acceptance. |
| Change-aware documentation validation | Plan against `lane/gui` selected GUI and docs; GUI checks already passed above. All 9 documentation invariants and changed-document links passed. |

Browser screenshots and traces are under `gui/test-results/layout/`; the HTML
report is `gui/playwright-report/index.html`. These generated files are ignored.
Command logs are retained locally under `gui/test-results/smoke-readiness/`.
The reported-overlap work-panel screenshot was also visually inspected: the
composer and right-hand task panel are visible and separate at that test size.
Browser density tests are not native OS scaling acceptance.
The native launch used the existing desktop environment without backend overrides.
An X11 window query did not identify a matching window; this host also exposes
Wayland, so that query cannot establish whether the window rendered. Native visual
and input acceptance remains unverified. Timeout termination does not test the
application's cooperative window-close lifecycle.

## Distance to a working product

1. **Offline presentation:** Web build, fixtures and browser interaction checks
   pass. This is a functioning presentation shell, not evidence of real coding
   work. The sample workspace, changes and tasks are explicitly fixture data.
2. **Linux live conversation: blocked by a missing platform implementation.**
   `src-tauri/src/lib.rs` compiles `app_client`, `live_bridge` and live invoke
   commands only under `cfg(windows)`. The live desktop acceptance launcher
   explicitly rejects non-Windows hosts. `App.tsx` catches an unavailable native
   live probe and selects the mock client. Building successfully on Linux cannot
   establish real backend connectivity.
3. **Windows bounded live conversation: historical evidence exists, current
   baseline still needs a fresh Windows run.** The existing
   [Windows acceptance record](windows-live-apphost-acceptance.md) reports real
   AppHost attachment, a deterministic no-network reply, reconnect and cooperative
   exit. This run did not repeat those observations. Re-run
   `accept:live-native` on Windows, then exercise Send, Interrupt, New Session and
   model selection through the actual window. Do not treat synthetic replies as
   provider acceptance.
4. **Real coding workspace: substantive contract work remains.**
   `src/client/nativeLiveClient.ts` projects `workspace`, `changes`, `artifacts`,
   `tasks` and `agents` as unavailable and emits an empty workspace list. The
   existing acceptance record also lists approvals and attachments as pending.
   These are integration capabilities to implement, not test failures fixed by
   more layout polishing.
5. **Usable desktop delivery:** native window interaction, Chinese input,
   clipboard, maximize/restore, and OS scaling need platform-specific evidence
   for the current baseline. Existing historical acceptance must be kept distinct
   from this Linux smoke run. Normal launch defaults to fixtures; controlled live
   launch requires an existing admitted AppHost record and mux selection.

Recommended order: choose the first supported live desktop platform; establish
its real AppHost launch/submit/stream/interrupt/reconnect/exit loop; then connect
workspace and change review, followed by approval/tool interaction and the
remaining task/agent surfaces. A numeric completion percentage or time estimate
would hide these different delivery boundaries.

No provider was contacted, no credential was read, and the explicit
`accept:live-provider` command was not run.
