# Independent Linux program acceptance

Product baseline `lane/gui` at `d84d7a19d`. Task branch
`feature/gui-independent-programs`. Tested on Ubuntu x86_64, with native GTK
under X11, a real terminal PTY, and Chromium.

## Build and relocation

The Tauri release build produced `harness-gui` and the production Web `dist`.
The task used the current worktree frontend and Rust source with the shared
Cargo build cache. `uv build --wheel` produced the application wheel. The
staging script independently assembled a bundled CPython 3.11.15 and hashed
production dependencies for both `loushang-gui` and `loushang-host`. The GUI
launcher binds its own interpreter for the existing Python client adapter.
The Host launcher delegates managed lifecycle and Web serving to existing
entrypoints. PyInstaller 6.22.3 froze the TUI AppClient entry into a single
executable that attaches to an existing local Mux.

The four outputs were copied to separate subdirectories under
`/tmp/loushang-programs-xIfLBX/run`. The acceptance process ran from a new
temporary workspace with private state roots, a restricted `PATH`, and no
inherited provider credentials. GUI and Host had separate state roots and
independent Python installations. The browser used the separately relocated
Web `dist`, served over a loopback HTTP listener.

## Observed behavior

- With the selected HTTP endpoint unavailable and no Host started, the native
  GUI rendered with New Session disabled. AT-SPI opened Account menu and
  Settings successfully. There was no managed Host namespace in GUI state.
- The independent Host entry started a real managed AppHost. The TUI attached
  to its Mux over the private local record, rendered the actual terminal
  interface, and exited successfully after `/detach` entered over the PTY.
- A new native GUI opened and attached to the same Host through its saved HTTP
  connection. An AT-SPI click on New Session added one real Session.
- Chromium loaded the production Web bundle and clicked New Session. The real
  snapshot confirmed the same service instance and one additional Session.
- After the clients exited, the managed Host still returned authenticated
  status `running`. Explicit stop settled cleanly.

The raw acceptance receipt and Web screenshot are under
`/tmp/loushang-programs-xIfLBX/acceptance-qt2iur0n`. The existing GUI suite
passed 118 tests. Browser layout initially passed 26 of 27 tests. The short
window case's simulated `connections/list` returned the shape of an
environment response, opening an error dialog. Correcting that test response
made the affected case pass. No production layout change was needed.

## Scope review

The implementing agent accepts the staging and verification boundary against
`d84d7a19d` plus this task's program-entry and test changes. AppHost lifecycle
and authority remain with existing managed owners. The GUI entry has no Host
start prerequisite, and the TUI only attaches. This run covers local-record TUI
and HTTP GUI/Web on loopback. Remote TUI, real model calls, machine reboot, a
systemd foreground service, and installer delivery are outside this acceptance.
The GUI currently stages the full Python wheel for its helper, so this is a
functional separation check, not a minimal dependency closure.
