# Native GUI session recovery acceptance

The repair starts from `lane/gui` at `c817c590f`, the baseline in the fresh native
UI report. Linux desktop acceptance ran on 2026-11-07 using the X11 backend.

## Root causes and implementation

- Before activation, a restored Coding Session uses a deferred control. It
  continued to hide the activated Session's model operations after activation.
  The GUI also fetched model data only on selection or connection changes. The
  control now forwards model operations after activation, and the GUI rereads
  `session/models` after a turn settles. The existing Rust request and result
  shape carry the confirmed model unchanged. Coding keeps the runtime model in
  the bounded response even when the selectable catalog omits it. The model
  field says “Model information unavailable” when the response cannot confirm
  a model. Reasoning effort has its own indicator.
- The UI selected the first member in a fresh snapshot because the previous
  selection lived only in memory. It now stores the selected member's Session
  ID under the AppHost's durable mux-space ID. It restores the ID only when
  the current snapshot contains that member and falls back to an available
  Session otherwise. AppHost restores the mux-space ID from continuity storage
  while rotating the service-instance ID.
- A deferred runtime reused the detached read-only projection's notice. Its
  history now says “Sending a message resumes the session runtime.” Truly
  read-only bindings still show their read-only notice and retain their existing
  control restrictions. The GUI renders transcript status records as notices
  rather than assistant messages.

## Real desktop run

The dedicated task worktree installed locked npm dependencies and compiled
`npm --prefix gui run build` from an empty Rust target directory. The release
build finished in 2m 31s with binary SHA-256
`f04eaaff98070ad9391b6c46094590470ecd6f29d0fb61382f5821d9f4b869e7`.

The standalone Coding CLI served the `workspace` endpoint using explicit
workspace, connection, AppHost application and transcript roots under
`/tmp/loushang-native-session-accept-q47vhg85`. The GUI used an isolated
WebView profile in the same root. The host used the normal saved model and
authentication configuration. The CLI created the empty `acceptance` mux
before launch. Window actions used AT-SPI and actual X11 keyboard input.

1. The GUI connected to the empty mux and created its default Session. **New
   Session** created the second Session. Clicked each row to verify that the
   selection changed and returned to the second Session.
2. Typed and sent the first token prompt through the composer. The real response
   contained `GUI-NATIVE-FIRST-731` and the window showed **Execution succeeded**.
3. Closed the GUI with its window button and reopened it against the still
   running AppHost. The second Session remained selected and showed the first
   turn.
4. Kept the GUI open, stopped the AppHost through the CLI, and restarted it
   with the same arguments and state. The service ID changed from
   `97981fceeb69ca4a4463f448e9446702` to `705104ab2d981b771ca2f7c8babd76e7`.
   The GUI reconnected with both members and kept the selected Session
   `0e762aaaf5fe6142d62c75451d3fbb311967f1bf230e730f35718e3788fc24c4`.
   Its earlier turn and a distinct resume notice were visible. The
   accessibility tree confirmed that the notice had no assistant-message
   ancestor. Model information was unavailable before runtime activation.
5. Typed and sent a second token prompt in the restored Session. The real
   response contained `GUI-NATIVE-RESTORED-731`, **Execution succeeded** returned,
   and both turns remained visible. The resume notice cleared.
6. Inspected the actual window screenshots after each success. Both showed
   `openai · gpt-6.1-sol · Reasoning` with a separate effort indicator. Both
   assistant records in the isolated durable transcript reported provider
   `openai`, endpoint `coding-responses` and model `gpt-6.1-sol`.
   The reply content was used only to identify each successful turn.

The GUI and AppHost were closed through their normal controls. Evidence in
the task worktree under `gui/test-results/native-session-recovery/` includes
`01-live-success.png`, `02-gui-reopened.png`, `03-host-stopped.png`,
`04-restored-before-send.png`, `05-restored-success.png`, accessibility
snapshots, and `result.json`. This directory is ignored by Git.

## Local checks

- GUI typecheck and 92 tests passed. Translation resources are current.
- Playwright layout and interaction checks passed all 23 tests.
- Hosted Session and catalog checks passed 33 tests with one skip.
- Offline AppServer, AppService, and AppHost regression passed 2344 tests with
  11 skips. AppHost and AppService lint and type checks passed. Existing
  AppHost G8, G9, and Linux G10 evidence checks passed, including the
  installed Linux canary.
- Ruff and mypy passed for the changed Coding sources. The documentation and
  architecture checks also passed.
- The first `make check-changed` run stopped in Coding because the shared
  editable install pointed at the control checkout. The existing Coding
  offline route passed all four shards after installing locked dependencies
  in the task worktree, with 4196 passes and 22 skips. Logs from both runs
  are in the ignored evidence directory under `checks/`.

## Verification scope

Native acceptance covered successful text requests and recovery of a
persisted local Coding mux on Linux. Regression tests cover an absent saved
member, isolation across muxes, model refresh after execution, a confirmed
model outside the selectable catalog, and read-only notices. The native run
did not cover Windows or macOS, failure-message behavior, provider fallback,
model switching during a resumed turn, tool approval, or interruption.

Internal implementation review by Codex covered the GUI presentation and
Coding hosted binding changes in this revision. The reviewed design keeps
AppHost as the model and runtime authority, reuses the accepted AppServer
model and transcript contracts, and adds only a local UI selection preference.
The successful native run and targeted regressions support that decision.
