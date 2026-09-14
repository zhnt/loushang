# HarnessGUI

This directory contains the Product-neutral native HarnessGUI shell accepted by
[GUI-B0 issue #582](https://github.com/zhnt/loushang/issues/582). React and
TypeScript own presentation and UI-local state; Tauri/Rust owns desktop
integration and will later adapt the accepted App Contract. The GUI does not
own Product, Harness, AppService, or AppHost runtimes.

The current B1 slice is deliberately offline. It provides a Product-neutral UI
port and a deterministic Mock AppClient with three Workspace kinds, grouped
Sessions, isolated per-Session drafts, active Run and Task progress, expandable
Activity details, distinct root/subagent AgentRuns, and read-only ChangeSet
review through a central Quick Look and the Work Dock. Every sample value is
labelled as fixture data. It does not read a repository, start a Python backend,
request a model, or connect to G16. Cross-language and real-service work remain
in C1 and B2 as described in the
[engineering plan](../docs/internals/architecture/drafts/gui-engineering-bootstrap-plan.md).

## Toolchain

- Node.js 24.19.0
- pnpm 11.19.0
- Rust 1.98.1 with rustfmt and Clippy
- Tauri 2 and React 19, resolved by the committed lock files

Platform system dependencies still follow the Tauri prerequisites. On Windows,
use the MSVC Rust host together with Visual Studio 2022 C++ Build Tools and a
Windows SDK.

## Commands

Run all commands from the repository root:

```text
pnpm --dir gui run doctor
pnpm --dir gui run bootstrap
pnpm --dir gui run dev:web
pnpm --dir gui run dev
pnpm --dir gui run dev:fixture-native
pnpm --dir gui run test
pnpm --dir gui run check
pnpm --dir gui run build
```

`dev:web` starts only the browser shell. `dev` starts the native Tauri window.
`test` runs reducer and React playback checks. `build` creates a native
executable without producing installers. `dev:fixture-native` and
`build:fixture-native` enable the B1-only Rust invoke/event canary; the command
is absent from the default native build.

For a standalone offline executable, use `pnpm --dir gui run build:fixture-native`
from the repository root. Do not substitute a plain `cargo build`: that bypasses
the Tauri frontend build and production protocol configuration and can produce a
window that expects a running localhost development server.

## Browser layout playback

From the repository root:

```text
pnpm --dir gui run test:layout:install
pnpm --dir gui run test:layout
pnpm --dir gui exec playwright show-report
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
ignored by Git and uploaded by the Windows GUI workflow for 14 days. Run this
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
are disabled; web-only previews disable window controls. Back/forward and menu
labels are still fixture placeholders, not implemented navigation or menus.
The sidebar toggle supports Ctrl+B; its separator supports pointer dragging,
Left/Right arrow adjustment (200–420 px) and double-click reset to 280 px.
Collapsed sidebars retain their width within the current GUI instance.
The environment summary is a separate floating surface with links to Changes
and Subagents. The right panel hosts Tasks/Subagents/Review; the bottom-panel
button is explicitly unavailable. Native drag, resize, maximize/restore, keyboard
focus and scaled layout still require Windows acceptance.

This slice is not yet fully accepted. Automated coverage includes Workspace and
draft isolation, Task/Activity progression, Task/AgentRun navigation, Quick Look
and Review, and prompt submission, streaming, interruption and a subsequent Run.
Disconnected or resync-required projections reject incremental events until a
fresh snapshot is installed; Send, Interrupt and fixture playback are disabled
while drafts remain editable. A `Resynchronize fixture` control appears on
disconnect, an event gap or snapshot failure, including initial-load failure.
Recovery is offline fixture behavior, not a reconnect workflow against a real
service.

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
- Run the new Windows GUI workflow remotely after opening a PR.

`gui/**` and `scripts/gui/**` now select the dedicated `gui` check, alongside
documentation checks. Ordinary README changes remain documentation-only. The
local gate invokes `pnpm --dir gui run check`; the Windows Actions workflow also
builds the standalone fixture executable. Changes to shared gate infrastructure
still intentionally select all checks.

Do not treat passing DOM playback tests as native visual acceptance or as C1/B2
real-service validation.
