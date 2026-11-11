# Native tray management acceptance

## Layout follow-up (2026-11-09)

Host menus now expand only one level under a section heading. Some AppIndicator
hosts render nested submenus inline; removing the outer expandable menu avoids
stacked submenu panels. The dynamic section includes the separator and Quit
footer, appended in order rather than inserted at a fixed root index. Connected
status text is omitted while transitional/error status text remains visible.

A rebuilt Linux application passed D-Bus menu inspection before and after a
saved Host switch: the heading has no submenu, Host actions have no nested
children, and the last two root items are a separator and Quit. Minimize,
close-to-tray, restore, Open Web, and Quit passed in the same isolated run.
This verifies the native menu structure; desktop-shell pixel layout was not
captured in this follow-up.

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
Minimize kept the window in the taskbar; Show window restored it from the
iconified state. The observed X11 environment required remapping the existing
GTK window when restoring from minimization; that fallback is Linux-only.

This check exposed AppIndicator retaining a submenu's previous title after
`set_text`; the implementation replaces the Host child submenu while retaining
the root menu. Windows and macOS native interactions remain unverified here.
The corrected English submenu title and all window actions passed the repeat
native check after this change.

After integrating the shared Web adapter, a second native run used a dynamic
loopback port and a saved remote-kind alias of that isolated adapter. The real
menu discovered the saved entry, Enable updated both the current Host row and
the persisted default connection, and Open Web invoked the selected address.
The window lifecycle checks passed again. This verifies the real configuration
and native menu path; it is not an external-machine/network acceptance test.
The isolated adapter received shutdown after the test; no execution Host was
started. Final combined `check:full`: 116 tests, web build, formatting, Clippy,
and Rust checks passed in normal and fixture-bridge configurations.

## Shared Host configuration integration

The directory adapter consumes `connections/list`, `connections/select`, and
`host/request` from the Web/Host task. It keeps user credentials in the native
helper. Per-Host probes never select a different connection or start a managed
execution service. Current live connection health comes from the mounted GUI's
accepted snapshots; other entries describe management endpoint reachability.

Implementing agent acceptance: native presentation and delegation boundary
reviewed within the authorized GUI task. No new PR gate is introduced.
