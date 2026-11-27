# macOS Intel full-package delivery

Scope: macOS 12+ full-package delivery and local AppHost lifetime. The native
acceptance below records the previous launchd-based build. The Managed Service
cutover has source and migration tests. A native macOS package run is pending.

The full installer places `loushang-gui.app` in `/Applications`. The native GUI,
frozen `loushang` TUI, Rust Web listener, Mux launcher and foreground Host entry
live in `Contents/MacOS`. Web assets and the backend-only Python runtime live
in `Contents/Resources`. `/usr/local/bin` provides the five command names.
The GUI bridge remains Rust/TypeScript; there is no Python connection helper.

`loushang-mux service` uses the shared Managed Service journal and
AppClient authentication. Hosting starts the child in its own POSIX session,
captures its boot and start identity and observes its exit using kqueue.
The AppHost lives independently of GUI, TUI and Web clients.

An existing installation must unregister its previous launchd job before
Managed Service can spawn. The cutover keeps the legacy application,
workspace and Session store paths and retains Mux and Session IDs. It
imports existing Mux receipts under the application lease and startup
fence before the child publishes its connection record. This is a one-way
transfer of Mux authority. See the [upgrade instructions](../../../scripts/gui/macos-package.md).

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

## Previous launchd-based native acceptance record

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
