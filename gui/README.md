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
