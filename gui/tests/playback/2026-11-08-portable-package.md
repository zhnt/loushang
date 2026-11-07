# Linux portable package acceptance

Date: 2026-11-08 (build started 2026-11-07).
Product baseline: `lane/gui` at `6de34b7a7`.
Task: `feature/gui-standalone-package`.

## Artifact and scope

Built `dist/portable/loushang-linux-x86_64.tar.gz`, approximately 53 MB compressed,
185 MB extracted. The adjacent `.sha256` file verifies the archive.
`manifest.json` records the product commit and hashes of the GUI, launcher,
Python wheel and dependency lock. The bundle includes the native GUI, CPython
3.11.15, installed Loushang wheel, locked Python dependencies, launcher,
license files and usage instructions. It includes no user settings, credentials
or conversation state. No end-user dependency download occurs at startup.

The build host is Ubuntu 26.10 x86_64, glibc 2.44. The GUI still dynamically uses
the host's GTK/WebKit desktop libraries. This is a portable candidate, not an
AppImage, distribution installer, signed release or compatibility claim for
older Linux releases. Optional external tools and plugin worker runtimes are
not bundled. Windows/macOS packaging is outside this run.

The launcher is package integration code; it delegates all actual service and
session behavior to the existing Coding AppHost CLI. It creates/reuses a private
workspace-specific state directory outside the application package. Closing GUI
detaches without stopping shared AppHost; `--stop` explicitly stops it. Replacing
the package does not require removing session state. It does not change shared
GUI platform logic or install any new CI gate.

## Build and relocation

Built the native release from a fresh dedicated worktree with `npm ci` and
`npm --prefix gui run build`. Built the portable candidate with
`uv run python scripts/gui/build_linux_portable.py --output dist/portable`.
Python dependencies are exported from `uv.lock` and installed with hash checks.
The copied interpreter's site-packages are cleared before installing the locked
runtime and application wheel; the source interpreter is never modified.

Extracted the actual archive into
`/tmp/loushang portable acceptance/loushang-linux-x86_64`, outside the checkout
and containing spaces in its path. Used `PATH=/usr/bin:/bin`,
`PYTHONPATH=/nonexistent` and Python isolated mode. Verified imported Loushang
and `sys.prefix` resolve inside the extracted package. Native `ldd` reports no
missing libraries on this host. This is not a pristine-VM verification: system
desktop libraries and existing provider credentials remain available.

`check_portable_package.py` passed against the extracted package: real startup,
repeated start reuses the connection record, stop, restart, and retained mux
identity. It uses temporary private state and does not invoke a provider.

## Actual packaged UI

Invoked the extracted `loushang` launcher from `/tmp`, with workspace
`/tmp/loushang-package-ui/workspace` and state root
`/tmp/loushang-package-ui/state`, using the restricted PATH above and
`GDK_BACKEND=x11`. The launcher automatically started its bundled AppHost and GUI.
The GUI connected and prepared the default session without separately starting
the development CLI.

Through actual AT-SPI/window keyboard operations, entered
`只回复 GUI-PACKAGED-OK，不要调用工具。` and clicked Send. The real provider replied
`GUI-PACKAGED-OK` and the UI displayed `执行已成功`. No mock, direct backend message
submission or injected transcript was used. Initial clipboard automation did
not immediately update the entry; the final input was verified before sending.

Closed the GUI using its window button, then verified packaged `--status` still
reported the one-member `desktop` mux. Used packaged `--stop` for test cleanup.
Existing developer workspaces and sessions were not changed or reset.

Local ignored evidence: `gui/test-results/portable-package/success.png`, build
and lifecycle logs, and accessibility snapshots. Private test state is retained
for follow-up. This verifies a short text request, not all tool/plugin flows.

## Review and checks

The implementing agent reviewed the package boundary within the authorized
standalone-package objective: application state stays external; authentication
remains in the Python runtime; the WebView receives no credentials; GUI exit
does not stop a shared host. No public protocol or stored schema was changed.
Static Ruff checks and targeted real package lifecycle acceptance passed.
Change-aware checks with `--base lane/gui` passed: TypeScript/frontend tests and
9 documentation checks. An initial plain `make check-changed` used the default
main baseline, included earlier Coding lane changes, and stopped because this
packaging environment does not contain pytest. That broader invocation is not
reported as passing; the corrected lane-based plan selects only GUI and docs.
