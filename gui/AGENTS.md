# HarnessGUI Contributor Notes

Keep this directory Product-neutral. React/TypeScript owns presentation,
UI-local state, and client-facing ports. Rust owns the Tauri bridge, native
desktop integration, and later App Contract adapters. Neither side owns or
reimplements Product, Harness, AppService, or AppHost runtime semantics.

Do not read Git repositories directly from the GUI. Workspace, worktree,
branch, change, and Diff values must arrive through accepted HarnessClient
facets. Do not expose authentication material to the WebView.

The B0 shell remains offline. Mock AppClient and playback belong to B1;
cross-language value contracts belong to C1; the real G16 connection belongs to
B2. Add only the capability required by the current accepted slice.

Use the package scripts documented in `README.md`. Keep Node, pnpm, Rust, Cargo,
and pnpm lock files synchronized, and verify changes with `pnpm run check` from
this directory.
