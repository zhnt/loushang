# HarnessGUI

This directory contains the Product-neutral native HarnessGUI shell accepted by
[GUI-B0 issue #582](https://github.com/zhnt/loushang/issues/582). React and
TypeScript own presentation and UI-local state; Tauri/Rust owns desktop
integration and will later adapt the accepted App Contract. The GUI does not
own Product, Harness, AppService, or AppHost runtimes.

The current B0 slice is deliberately offline. It does not start a Python
backend, request a model, implement Mock AppClient playback, or connect to G16.
Those capabilities remain in B1, C1, and B2 as described in the
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
pnpm --dir gui run check
pnpm --dir gui run build
```

`dev:web` starts only the browser shell. `dev` starts the native Tauri window.
`build` creates a native executable without producing installers.

During rapid GUI development, `check` is a lightweight presentation check.
On this B0 baseline it runs TypeScript type checking; the B1 delivery adds its
offline tests. `check:full` retains the toolchain doctor, web build and Rust
checks for native/toolchain changes. Packaging and browser playback are
on-demand acceptance work, not prerequisites for every presentation edit.
The GUI workflow uses Node/pnpm only. GUI-only changes do not select TUI,
Harness or provider suites; shared CI changes retain their existing gates.
