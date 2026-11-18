# macOS Intel full-package delivery

Status: accepted for Intel packaging and native macOS 15 runner operation;
actual macOS 12 installation acceptance remains pending. Scope: macOS 12+
Intel packaging and launchd integration.

The full installer places `loushang-gui.app` in `/Applications`. The native GUI,
frozen `loushang` TUI, Rust Web listener, Mux launcher and foreground Host entry
live in `Contents/MacOS`. Web assets and the backend-only Python runtime live
in `Contents/Resources`. `/usr/local/bin` provides the five command names.
The GUI bridge remains Rust/TypeScript; there is no Python connection helper.

`loushang-mux service` delegates macOS process ownership to launchd's per-user
domain with the explicit Background session type. A label derived from the configured product home isolates installations
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
delivery does not change wire schemas or add PR blocking jobs. Native runner
findings were resolved before accepting the implementation within this scope.

## Native acceptance record

The implementation agent accepted the reviewed implementation after the full
installer from source commit `e9f93e919286d6d31056c07f4a65d3cd1d75a1a6` passed
[Actions run 44276006846](https://github.com/zhnt/loushang/actions/runs/44276006846)
on macOS 15.7.9 Intel. Evidence is in the `loushang-macos12-intel` artifact.

The actual `.pkg` installed successfully. Installed TUI/Host command entry
points, bundled Python imports, native GUI startup, Host persistence after GUI
exit, Web assets with source assets hidden, workspace navigation, model listing,
session snapshots, identity preservation across Host restart, and stale-instance
stop rejection all passed. Package contents also passed Intel/minimum-version
auditing and deep signature verification. Temporary diagnostic jobs are removed
from the final workflow; final acceptance used the freshly built installer.

This record does not assert a live provider conversation, visual layout
acceptance, macOS 12 runtime acceptance, Developer ID signing or notarization.
