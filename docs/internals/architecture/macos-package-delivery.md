# macOS Intel full-package delivery

Status: implementation candidate; native acceptance is recorded by the manual
Actions artifact. Scope: macOS 12+ Intel packaging and launchd integration.

The full installer places `loushang-gui.app` in `/Applications`. The native GUI,
frozen `loushang` TUI, Rust Web listener, Mux launcher and foreground Host entry
live in `Contents/MacOS`. Web assets and the backend-only Python runtime live
in `Contents/Resources`. `/usr/local/bin` provides the five command names.
The GUI bridge remains Rust/TypeScript; there is no Python connection helper.

`loushang-mux service` delegates macOS process ownership to launchd's per-user
domain. A label derived from the configured product home isolates installations
and test homes. Start/stop/restart serialize under a private local control lock;
an expected instance rejects stale shutdown requests. The service is not
registered for automatic login startup. Exiting the GUI leaves the Host alive.
Provider credentials are never written into the launchd property list.

The foreground Host reuses the existing workspace catalog, AppHost, AppService,
AppServer, continuity store and session factory. launchd is the native process
owner, so this adapter does not introduce another native-process registry.
The existing application continuity lease excludes simultaneous owners of the
same application root. Internal named-Mux permits use stable operation IDs and
per-instance random authority; remote callers cannot mint permits. Admission
and shutdown fencing use the existing AppService commit/settlement boundary.
The macOS catalog follows the existing portable Session writer path.

The private workspace storage adapter uses macOS `renameatx_np(RENAME_EXCL)`
for atomic no-replace moves. Linux keeps `renameat2(RENAME_NOREPLACE)`.

Builds use `macos-15-intel`, `x86_64-apple-darwin` and
`MACOSX_DEPLOYMENT_TARGET=12.0`. Wheel selection uses the same deployment target.
The packager checks the Intel slice, Mach-O minimum version and absolute dynamic
dependencies of every shipped native file. It rejects external Homebrew/build
paths and native minimum versions above 12.0. Package requirements and the app's
`LSMinimumSystemVersion` also specify 12.0. The package is an unsigned test
installer; its app has local ad-hoc signatures, without Developer ID notarization.

The manual workflow installs the actual `.pkg`, verifies command entry points
outside the checkout, starts the native GUI, confirms Host persistence after
GUI exit, and checks Web assets, workspace navigation, model listing, a real
Host session snapshot, restart and stale-instance rejection. No provider
credentials or live model requests are used. This verifies the runner's OS;
macOS 12 Intel acceptance remains a separate required claim before declaring
that runtime tested.

Internal review: the implementation agent reviewed the Coding launch adapter,
AppService managed-Mux admission contract, continuity ownership, private
workspace storage, GUI resource lookup and manual-only CI boundaries. The
candidate does not change wire schemas or add PR blocking jobs. Native runner
findings must be resolved before accepting this delivery candidate.
