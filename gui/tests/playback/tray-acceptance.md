# Native tray management acceptance

Scope: native menu presentation, window lifecycle, and delegation to existing
Host management. No runtime lifecycle or credential owner is moved into Rust.

## Automated checks

- Tray projections distinguish selected connection, connection health, and
  execution service state; unknown/busy services do not enable lifecycle effects.
- Menu revisions reject stale clicks. Stop preserves the confirmed instance ID.
- Directory tests route operations to explicit Host IDs, including a stop
  confirmation created before the selected Host changes.
- HTTP(S) browser links reject credentials, query strings, fragments, and
  non-Web protocols. Opening Web never injects a server token.
- Close/Ctrl+W and Quit/Ctrl+Q have separate handlers.

## Linux desktop observation (2026-11-09)

A built native application was launched with isolated XDG configuration/data
and `LOUSHANG_HOME`. D-Bus inspection verified the real AppIndicator menu,
user name, current Host state, and nested Host actions. Sending WM_DELETE_WINDOW
removed the test window from the window-manager client list while the tray
remained registered. Show window restored the same window. Open Web invoked
an isolated system URL handler with the configured HTTP address. Tray Quit
ended the test process with status 0. No managed execution Host was started.

This check exposed AppIndicator retaining a submenu's previous title after
`set_text`; the implementation replaces the Host child submenu while retaining
the root menu. Windows and macOS native interactions remain unverified here.

## Shared Host configuration integration

The directory adapter consumes `connections/list`, `connections/select`, and
`host/request` from the Web/Host task. It keeps user credentials in the native
helper. Per-Host probes never select a different connection or start a managed
execution service. Current live connection health comes from the mounted GUI's
accepted snapshots; other entries describe management endpoint reachability.

Implementing agent acceptance: native presentation and delegation boundary
reviewed within the authorized GUI task. No new PR gate is introduced.
