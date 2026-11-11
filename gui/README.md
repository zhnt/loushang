# HarnessGUI

This directory contains the Product-neutral native HarnessGUI shell accepted by
[GUI-B0 issue #582](https://github.com/zhnt/loushang/issues/582). React and
TypeScript own presentation and UI-local state; Tauri/Rust owns desktop
integration and adapts the accepted App Contract slice. The GUI does not
own Product, Harness, AppService, or AppHost runtimes.

Both browser and desktop launches use real AppHost data. A disconnected Host
shows a disconnected shell and Host settings; there is no Mock fallback or
product fixture mode. Deterministic clients live under `tests/support/` only.
The browser adapter reuses authenticated AppClient/ExecutionClient contracts;
React uses the same validated snapshot projection as the native bridge.

## Shared local storage and browser access

`npm --prefix gui run dev` starts Vite in desktop mode and opens the Tauri
window. Rust reads the saved connections and talks to the selected HTTP endpoint.
For the local target, Rust ensures the Web adapter is running; the adapter needs
the installed Python project and uses the existing managed Host entrypoint.
Selecting the local target does not start the Coding AppHost until requested.

`npm --prefix gui run dev:web` starts the browser development surface with its
Rust Web service (`gui/web`). Vite proxies requests to its HTTP endpoint.
The GUI Rust code owns the listener and static assets; Coding only handles Host
requests through a private stdio adapter. One Rust Web process is shared per user directory.
Open Settings → Host to start or connect the local AppHost. The Host can be
running with an empty Workspace list. After connecting, enter an absolute path
on the Host and choose **Register and open**, or select a registered Workspace.
Each Workspace retains its own Sessions. Switching Workspaces or quitting the GUI
does not stop their executions. Use **Stop Host** for a graceful service stop.

On Linux, `lmux server start` starts the same managed Host without a Workspace.
Its deployment identity is scoped to the local user and Coding product. The
Host owns canonical Workspace paths; the client may remember the last selection,
but the preference grants no access. Each Workspace has its own transcript
store and each Session receives its own working directory and Runtime.
The AppService and Execution Registry are shared across Workspaces. Active
execution recovery is limited to the same running Host instance.
Both surfaces show the same shell and initial panel layout (native window controls
remain desktop-only). The development API accepts only same-origin loopback
requests with the client header. Stopping Vite closes its proxy; the Rust Web service and managed Hosts continue
running so other clients remain connected. The browser development proxy needs
the installed Python project dependencies. `LOUSHANG_GUI_PYTHON` selects its
interpreter.

Storage below `LOUSHANG_HOME` (default `~/.loushang`) follows existing ownership:

| Path | Owner and meaning |
| --- | --- |
| `models/*.json` | Existing user model registry; unchanged |
| `auth/<provider>-auth.json` | Existing model OAuth credentials; unchanged |
| `coding/settings.json` | Existing Coding settings; unchanged |
| `connections.json` | Client connection targets and last local workspace |
| `host.json` | Standalone Web listener configuration |
| `state/web/` | Shared adapter discovery, ownership locks and logs |
| `data/client-preferences.sqlite3` | Host-side pins, recent visits and selected-session recovery, scoped by mux |
| `data/`, `state/`, `lmux/` | Existing business, internal and managed-service storage |

Language, appearance and Markdown theme remain independent localStorage
preferences. Navigation changes use atomic operations so concurrent windows do
not overwrite each other's pins. Other windows observe changes on the next
one-second refresh; each open window keeps its own current selection and drafts.
Account authentication is not implemented yet. A future Host-managed login can
serve GUI, TUI and browser sessions without exposing credential files to JavaScript.

### Local Web access

Build the Web assets, then run the server without a desktop:

```sh
npm --prefix gui run build:web
cargo run --locked --manifest-path gui/web/Cargo.toml -- --dist gui/dist
```

The default listener is `127.0.0.1:1422`, accessible only from this machine.
Open it directly; no login or token is required. The browser reads and writes
shared configuration through the Host API. Files are stored in the Host machine's
`~/.loushang`. Provider
credentials and private AppHost records never enter the browser. Closing the
server releases its connections without stopping managed Hosts.

Optional `host.json`:

```json
{"web":{"bind":"127.0.0.1","port":1422,"dist":"/absolute/path/to/gui/dist"}}
```

The current delivery covers local Web access. Remote deployment and account
login are deferred; see the [open design questions](../docs/internals/architecture/gui-web-config-open-questions.md).

## Application branding

Change two fields in [Tauri configuration](src-tauri/tauri.conf.json) to build
a renamed GUI. Both default to `loushang-gui`.

- `productName` sets the desktop window title, tray labels, React shell text,
  and browser tab title. It can contain spaces.
- `mainBinaryName` sets the release executable name. Use a portable filename
  such as `my-studio`, without an extension. Tauri adds `.exe` on Windows.

Run `npm --prefix gui run build` for the desktop and `npm --prefix gui run
build:web` for a separate Web distribution. Development builds run the Cargo
target `harness-gui`. Cargo, npm and the application identifier are defined
independently of branding. Installing distinct branded editions side by side
requires separate application identities and data paths.

The built-in Loushang artwork replaces the Tauri starter icons for native
packaging and window defaults. Browser previews use the same artwork as a
favicon. Source assets, regeneration instructions and the future user override
boundary are documented in [branding assets](assets/branding/README.md).
System tray and notification behavior are not implemented by this asset change.

## Toolchain

- Node.js 24.22.2
- npm 11.19.1
- Rust 1.98.1 with rustfmt and Clippy
- Tauri 2 and React 19, resolved by the committed lock files

Platform system dependencies still follow the Tauri prerequisites. On Windows,
use the MSVC Rust host together with Visual Studio 2022 C++ Build Tools and a
Windows SDK.

## Commands

Node.js includes npm. If the bundled npm differs from the pinned version, run
`npm install --global npm@11.19.1`. Run all commands from the repository root:

```text
npm --prefix gui run doctor
npm --prefix gui run bootstrap
npm --prefix gui run dev:web
npm --prefix gui run dev
npm --prefix gui run test
npm --prefix gui run check
npm --prefix gui run build
```

`dev:web` starts the browser shell and real Host adapter. `dev` starts the native Tauri window.
The native desktop tray groups the user name, Show window / Open Web, current
Host connection status, Host management, and Quit. Show window restores and
focuses the existing window. Closing the window hides it to the tray;
minimizing retains normal OS behavior. Quit (including File > Quit / Ctrl+Q)
uses the normal connection cleanup path. On Linux, use the tray menu (the
desktop must provide an AppIndicator-compatible host). If tray initialization
fails, normal window closing remains available. The browser has no system tray.
Host connection colors and service lifecycle are separate: green means
connected, yellow connecting, red disconnected, and grey unknown. A checkmark
identifies the selected Host. The Open Web action is disabled without a usable
address and never appends credentials. Menu text follows the interface language.
Manage Hosts opens the saved Host list. Each Host opens a submenu with its
service status and controls. A separator precedes Quit.
Connected Hosts show their name and green dot without redundant status text;
connecting and disconnected states retain their explanatory labels.
See [tray acceptance](tests/playback/tray-acceptance.md) for validation scope.
`test` runs reducer and React playback checks. During rapid B1 development,
`check` runs only TypeScript type checking and these offline tests, without
requiring Rust or building assets. Use `check:full` for Rust/native/toolchain
changes; it retains the toolchain doctor, web build, tests and Rust checks.
Layout playback and native packaging remain on-demand acceptance commands.
`build` creates the native executable with the frontend embedded. On Linux,
run the standalone program using the default Cargo output path:

```sh
npm --prefix gui run build
gui/src-tauri/target/release/loushang-gui
```

Use `build:web` for a separate `gui/dist` to serve in browsers. The Rust
fixture-bridge feature is retained only for protocol tests.

## Controlled live launch

The AppHost/desktop launcher may start the built executable with both native
arguments below. Omitting both opens local Host management in the native app
(browser development uses the real Host adapter). Partial, duplicate or
unknown arguments disable live availability rather than falling back with
ambiguous authority.

```text
gui/src-tauri/target/release/loushang-gui.exe --loushang-app-record-root C:\path\to\admitted\connection --loushang-mux-name GUI-work
```

Linux also supports the same explicit connection arguments:

```sh
gui/src-tauri/target/debug/harness-gui \
  --loushang-app-record-root /absolute/path/to/admitted/connection \
  --loushang-mux-name main
```

For a debug build, start `npm run dev:web -- --mode desktop` in `gui/` first. Its configured
WebView URL is `http://localhost:1420`. A standalone packaged build uses the
embedded frontend. With explicit connection arguments, the Host and Mux must
already exist through the managed management entry. Reconnect attaches the
original Mux and reads its existing members.

Without explicit connection arguments, the native window reads `connections.json`
and opens even when the selected endpoint is unavailable. With the local Host's
Web endpoint running, select an existing absolute Workspace directory, then choose
**Start and connect** or connect to its running Host. Startup uses the existing
managed coordinator and admitted Mux creation; an empty Mux receives the existing
default Session initialization. Closing the GUI only disconnects the client.
Stop and restart require confirmation because they interrupt active executions;
restart preserves Session history but does not resume an interrupted execution.
An unconfirmed instance is never automatically replaced.

Local and remote management requests go to the selected Host API. The browser
and desktop write the same v1 connection settings using the shared SQLite lock.
Managed storage retains its existing private-directory and trusted-ancestor
requirements. Explicit local record arguments continue to use the native
AppClient on supported platforms.

Linux record admission uses no-follow directory/file descriptors, current-user
ownership, private 0700/0600 modes, single-link regular files, bounded reads and
identity/version revalidation. Windows retains its existing handle/DACL checks.
The connection selects the validated record's semantic Execution profile,
including `local-detachable-discovery-execution-managed/v2`; capability order,
managed closure prerequisites, authentication digest and exact hello are checked.
Legacy valid record decoding remains available, but a live GUI requires Execution.
Unknown submit receipts are queried without replay only on the same service
instance; a replacement Host is reported as an unknown outcome.

Linux evidence and the remaining graphical acceptance limits are recorded in
[stage 1D delivery](../docs/internals/architecture/appservice/execution-service-delivery.md#managed-gui-adaptation--stage-1d).

The record root and Mux selection are parsed and retained by Rust; the WebView
cannot provide or read them. Native admission still validates the private record
directory and file before authentication. The published payload contains no
attachment ID, controller generation or authentication key. Live snapshots are
prepared with a default Session when the selected Mux is empty. The native
adapter uses the authenticated record's admitted `cwd` scope (or its home scope
when no workspace scope is published), asks AppHost to open a stable per-Mux
continuity identity, and reattaches before publishing the snapshot. Existing
members are retained; reconnecting does not append another default Session.
New Session can also use this admitted context without an existing selection.
See [default Session acceptance](tests/playback/default-session-acceptance.md).

Live snapshots are
visibly labelled as AppHost-controlled. Send and Interrupt use controller facts
kept only in Rust; fixture playback, Workspace, ChangeSet, Tasks and Subagents
remain unavailable until their own accepted live contracts are implemented. Closing the window cooperatively detaches and joins
the reader without stopping the shared AppHost. Each connection attempt has a
new epoch. A failed transport or invalid round marks live facts
disconnected/resync-required; the native adapter rereads the private record,
authenticates and attaches again, and the WebView resumes only after a complete
fresh snapshot and membership barrier. A submit with an uncertain response is
looked up by its stable submission ID after reconnect and is never replayed
automatically. The draft is cleared only after acceptance is known; commands are
blocked until the resulting authoritative event or snapshot advances the Session.

Windows and POSIX desktops share the native connection, authentication, Session
and reconnect implementation. Only private-file admission is platform-specific,
behind one native record port; POSIX uses rustix and the existing AppServer
owner-only/no-follow rules. Linux has local integration evidence; macOS and
Windows still require native verification of this revision. See
[cross-platform bridge evidence](tests/playback/cross-platform-bridge.md).

For an opt-in desktop acceptance run, first build the release executable and
then launch an isolated real AppHost plus two real mux/session projections:

```text
npm --prefix gui run build
npm --prefix gui run accept:live-native
```

The second command opens a visible HarnessGUI window and keeps the shared
AppHost alive until that window is closed. It also rotates the real local
listener and connection record, and waits for the GUI to reconnect and accept a
fresh authoritative snapshot. Inspect the final connected labels, real Session
projection, Send/Interrupt behavior and normal/maximized layout,
then close the window. The launcher verifies the reconnect, that the GUI
released its mux controller, that the AppHost is still accepting, and that an
independent peer Session is still snapshot-readable. Non-secret lifecycle evidence is written under
`gui/test-results/live-apphost-desktop/`; this opt-in helper is not part of the
rapid GUI gate and does not invoke a model.

To exercise the same isolated AppHost with the saved Coding default model and
its existing credential, run the explicit provider acceptance instead:

```text
npm --prefix gui run accept:live-provider
```

This command resolves the model through the normal layered AI ModelRegistry and
Coding settings; the GUI does not parse `models.json` or receive credentials.
It currently uses no tools, sends one short acceptance prompt, may incur provider
usage, and then leaves the window open for manual conversation. Non-secret
evidence is written under `gui/test-results/live-provider-desktop/`. It is never
part of `check`, CI or another default gate.

The first observed live desktop run is recorded in
[Windows live AppHost acceptance](tests/playback/windows-live-apphost-acceptance.md).
It records the initial projection, ongoing event integration,
disconnect/resynchronization and cooperative desktop-exit lifecycle. The
automated integration check additionally submits through the production desktop
control bridge. Windows display scaling remains outside this slice.

For a standalone desktop executable, use `npm --prefix gui run build`
from the repository root. Do not substitute a plain `cargo build`: that bypasses
the Tauri frontend build and production protocol configuration and can produce a
window that expects a running localhost development server.

## Ubuntu complete deb test package

Build the current GUI, then package it with CPython, AppHost/AppService, the
installed Loushang wheel, locked Python dependencies and local Web assets:

```text
npm --prefix gui ci
npm --prefix gui run build
uv run python scripts/gui/build_linux_deb.py
uv run python scripts/gui/check_deb_package.py dist/deb/loushang_<version>_amd64.deb
```

Install the generated file with `sudo apt install /absolute/path/to/package.deb`.
The application menu and `/usr/bin/loushang` use the bundled runtime under
`/opt/loushang`. Local startup uses the same managed Host entrypoint as the tray;
GUI close/quit leaves that Host running. A saved remote connection remains
selected. `loushang --workspace /absolute/path --status` and `--stop` manage the
local Host. Stop running Hosts before replacing or removing this test package.
Settings and Session data remain outside the installed program directory.

This Ubuntu 26.10 amd64 candidate declares native system-library dependencies.
It does not require a system Python/uv/Node installation. It does not register
a systemd unit or start services during installation. Provider credentials and
optional external tools/Plugin worker runtimes are not included. The opt-in
checker extracts the actual deb and verifies relocated imports, real Host
startup, reuse, stop and restart without provider calls or system installation.

## Linux portable package candidate

To bundle the real GUI with its own CPython, AppHost and locked Python runtime
dependencies (Linux x86_64 build host):

```text
npm --prefix gui ci
npm --prefix gui run build
uv run python scripts/gui/build_linux_portable.py
```

Extract `dist/desktop/loushang-linux-x86_64.tar.gz` outside the checkout and
double-click the native `loushang` executable. To choose a workspace explicitly, run
`./loushang --workspace /path/to/workspace` inside the extracted directory.
No Python/uv/Node/Rust installation is needed at runtime. Compatible Linux
GTK/WebKit system libraries are still required. See the included `README.txt`
for the tested distribution, state locations and explicit `--stop` command.
Closing a GUI window detaches it and leaves its shared AppHost running.
Credentials and optional external worker/tool runtimes are not bundled.

For opt-in real packaged lifecycle checks, run
`uv run python scripts/gui/check_portable_package.py /path/to/extracted/package`.
This does not call a model or add a CI gate. Native UI/provider acceptance must
also be performed against the extracted package; a source-tree run is insufficient.

## Browser layout playback

For the optional Python → Rust → TypeScript C1 execution contract slices,
see [contract probe](contracts/README.md) and run `npm --prefix gui run check:contract`.
It is separate from default checks and does not connect the GUI to AppHost.

From the repository root:

```text
npm --prefix gui run test:layout:install
npm --prefix gui run test:layout
npm --prefix gui exec -- playwright show-report gui/playwright-report
```

The layout suite starts its own loopback-only Vite server on port 1421 and
refuses to reuse an existing server. It runs headless Chromium against offline
fixtures, with remote requests blocked. Nine scenarios cover 700–1730 CSS-pixel
widths, a dragged 420 px sidebar, a hidden sidebar, and device pixel ratios 1.25
and 1.5. Every scenario exercises environment, closed, work-panel and restored
environment states. Assertions use real element bounds and action hit-testing;
screenshots are evidence, not a pixel-difference baseline.

The HTML report is in `gui/playwright-report/index.html`; screenshots, measured
bounds and failure traces are in `gui/test-results/layout`. Generated evidence is
ignored by Git; keep or share them when doing layout acceptance. Run this
suite separately from `check` (which does not install a browser). Pixel density
is not Windows OS scaling; native titlebar/drag/resize acceptance remains manual.

## B1 acceptance status

Environment summaries reserve a 330 px right column; work panels reserve 380 px.
Closing both returns the reading column to the full Session area. The transcript,
playback controls and composer share measured gutters, including the native
scrollbar width. If the remaining width after the sidebar cannot provide a 360 px
conversation beside the right column, the right content moves below the
conversation instead of overlaying it. This responsive policy is a HarnessGUI
decision, not a claim about Codex's internal layout implementation.

The desktop frame uses one custom title/menu row with native minimize,
maximize/restore and close commands, plus a Tauri drag region. Native decorations
are disabled. Web access omits the entire desktop title/menu row and uses the
full viewport height. The sidebar toggle lives in the sidebar brand row; when
collapsed, a 48 px rail keeps the reopen button at the top and the fixture user
avatar at the bottom. Ctrl+B
also toggles it. Back/forward in the desktop row navigate this instance's
Session selection history, retaining per-Session drafts and view state. A new
selection after going back drops the forward history; missing Sessions are
skipped and changing the client/service context resets the history.

Desktop File/Edit/View/Help menus provide capability-gated new Session,
composer focus, window close, copy selection/select all, sidebar/environment
visibility, keyboard help and an About dialog. Clipboard failures are reported
without changing the selected text. Menu buttons support keyboard navigation,
Escape and outside-click dismissal. File/Edit/View/Help entries are grouped
with separators, shortcut hints and aligned checkmarks. Unimplemented actions
(including new windows, project/folder opening, settings, edit history,
terminal, tabs, zoom and external help) stay visibly disabled. Existing new
Session, close/quit, work-panel toggle and history actions also support their
advertised desktop shortcuts; shortcuts are not installed in the web shell.
Native dragging, maximize and close use
the existing Tauri window permissions. Web users keep browser-provided editing
and window controls and the in-page Session/sidebar/panel controls.
The sidebar separator supports pointer dragging,
Left/Right arrow adjustment (200–420 px) and double-click reset to 280 px.
Collapsed sidebars retain their width within the current GUI instance.
The environment summary is a separate floating surface with links to Changes
and Subagents. The Session header spans both the conversation and right-panel
columns, so opening a panel or collapsing the sidebar does not pull its controls
away from the window's right edge. Only the body reserves right-panel width;
narrow layouts stack that panel below the conversation. The right panel hosts
Tasks/Subagents/Review; the bottom-panel
button is explicitly unavailable. Native drag, resize, maximize/restore, keyboard
focus and scaled layout still require Windows acceptance.

This slice is not yet fully accepted. Automated coverage includes Workspace and
draft isolation, Task/Activity progression, Task/AgentRun navigation, Quick Look
and Review, and prompt submission, streaming, interruption and a subsequent Run.
Disconnected or resync-required projections reject incremental events until a
fresh snapshot is installed; Send, Interrupt and fixture playback are disabled
while drafts remain editable. A `Resynchronize fixture` control appears on
disconnect, an event gap or snapshot failure, including initial-load failure.
The same fail-closed reducer behavior is now connected to the live adapter. The
fixture keeps an explicit manual recovery control; the native live path requests
a new connection epoch and authoritative snapshot automatically.

Accepted live snapshots now project transcript records, bounded assistant draft,
Session running/failed/interrupted status and the current execution identity,
revision, source observation, interrupt flag and truncation state. Execution
details are expandable in the central transcript. A final authoritative snapshot
replaces the draft rather than appending a duplicate message. Snapshot advances
for an inactive Session set its unread marker; selecting that Session clears it.
Disconnected and resync-required Sessions retain the last evidence but display it
as stale and stop the running animation. `ExecutionProjection` is deliberately
separate from `RunProjection`: the current execution contract does not contain
Task, Activity or AgentRun facts, so their live capabilities remain unavailable
instead of being inferred from transcript text.

Dock tab, open/closed state, Task selection, AgentRun selection and transcript
scroll offset are retained
per Session context during navigation and same-context snapshot replacement.
Changing application identity resets these view preferences. Incoming Task
progress no longer replaces the Task the user is inspecting. Workspace, Task,
AgentRun and ChangeSet views downgrade when their fixture capability is missing,
unavailable or uses an unsupported version, including after snapshot replacement.
These exact fixture versions are not a production capability negotiation scheme.

Mock AppClient snapshots now contain the latest replayed cursor, messages and Run
projections, including when no UI is subscribed. Snapshot and event consumers
receive isolated copies. Tests cover recovery after a deliberately missed event,
then continued playback without a cursor gap. The scroll tests verify DOM offset
restoration, not native layout, text-anchor stability after resizing, or automatic
follow-to-bottom behavior.

During initial loading and recovery, incoming events are buffered (up to 2048).
After snapshot installation, the cursor checks discard covered events and apply
new contiguous events; remaining gaps keep the UI frozen. A buffer overflow or
snapshot failure requires retry. Duplicate refresh requests are suppressed and
late snapshots from a replaced/unmounted client are ignored. Playback tests
cover snapshots both including and preceding buffered events, failed-load retry,
recovery with draft preservation and late results from an old client.

Remaining acceptance work:

- Verify the native layout at normal/maximized sizes and Windows 125%/150%
  scaling, including composer visibility with the Work Dock open.
- Run the lightweight GUI workflow remotely after opening a PR.

`gui/**` and `scripts/gui/**` now select the dedicated `gui` check, alongside
documentation checks. Ordinary README changes remain documentation-only. The
local gate and the Ubuntu GUI workflow invoke `npm --prefix gui run check` only.
They do not install browsers, run Rust checks or build a native executable.
GUI-only workflow edits select GUI plus CI routing/syntax checks, not TUI or
Harness checks. Changes to shared gate infrastructure still intentionally
select all checks; adding GUI files to a mixed change never suppresses checks
for its other owners.

Do not treat passing DOM playback tests as native visual acceptance or as C1/B2
real-service validation.

## Interface languages

The GUI ships `en-US` and `zh-CN` resources locally. Open the account menu at the
bottom of the sidebar and choose **Settings → General → Interface language**.
The desktop File menu and Ctrl+, also open Settings. The selector supports
Follow system, 简体中文 and English. `loushang.gui.language` stores only
that device-local preference; existing workspaces, session content and settings
are not migrated. Native startup reads the OS locale through the official Tauri
OS plugin with only `os:allow-locale`; web preview uses `navigator.languages`.
System preference is resolved at startup and when selected, not continuously.
Explicit English variants map to en-US; simplified Chinese variants map to
zh-CN; explicit Traditional Chinese is not silently mapped to Simplified.
Unknown locales fall back to English. UI language does not set AI reply language.

Use `useTranslation` with semantic string keys. JSON files under `src/i18n/locales`
are the source of truth, organized into shell/session/workspace/panels/common.
Use complete messages and named interpolation values; plural messages use
`count`. Do not translate user content, model output, paths, identifiers or raw
diagnostic details. Keep product error headings and instructions translatable.
Save UI notice keys and necessary parameters, not already translated strings.
Do not add translation dependencies to connection or submission effects.

```text
npm run i18n:extract
npm run i18n:types
npm run i18n:status
npm run check:i18n
npm run test:coverage
```

Review extraction changes before accepting them. `i18n:types` uses the official
CLI to generate literal resource types; `src/i18n/types.d.ts` adds strict key
checking. String-key API is the project convention. Type tests prove invalid
keys and incorrect interpolation names fail. With the installed versions,
omitting the options argument entirely is not reliably rejected by TypeScript;
the CLI call-site checker also has a custom-namespace limitation. The small
`check-resources.mjs` supplement checks literal calls with omitted options,
including plural bases, and rejects blank/missing translations and missing
locale-specific plural forms. Official CLI lint checks placeholder consistency.
It is not a general dynamic-expression analyzer; use explicit typed mappings.

Do not consider English fallback proof of translation completeness. Review
source wording changes and corresponding translations together in Git Diff.
Brand names, language autonyms and fixture account names have narrowly scoped
lint exceptions. New required PR checks are not added by these local commands.
`check:i18n` remains an explicit local validation command.

Terminology: Session = 会话; Workspace = 工作区; Task = 任务;
Run = 运行; Agent = 智能体; Subagent = 子智能体; Review = 审阅.
The current File/Edit/View/Help row is React-rendered, not a Rust native menu.
The native tray receives a presentation projection using the same translation
resources. Rust uses temporary bilingual startup labels until that projection
arrives; it does not maintain a duplicate translation dictionary.

See [i18n delivery evidence](tests/playback/i18n-acceptance.md) for the observed
validation scope and native limitations.

### Rust Web listener development

`gui/web` is a headless GUI Rust crate, independent of the Tauri window loop.
`loushang-web --ensure` starts or reuses the local service. The desktop uses the
same startup code; `LOUSHANG_GUI_WEB` can select an explicit binary for development.
The default remains loopback port 1422 without login. The old Python Web listener
has been removed; stop an already-running old adapter before starting this version.
Existing `connections.json`, `host.json`, navigation data and Host sessions remain.

For focused checks, run `cargo test --locked --manifest-path gui/web/Cargo.toml`
(with the installed project interpreter in `LOUSHANG_GUI_PYTHON`) and
`cargo clippy --locked --manifest-path gui/web/Cargo.toml --all-targets -- -D warnings`.
The standalone GUI package includes `bin/loushang-web` and `web/` assets; invoke
`loushang-gui web`. A Host-only package no longer owns a Web listener.
