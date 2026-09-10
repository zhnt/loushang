# HarnessGUI Contributor Notes

Keep this directory Product-neutral. React/TypeScript owns presentation,
UI-local state, and client-facing ports. Rust owns the Tauri bridge, native
desktop integration, and later App Contract adapters. Neither side owns or
reimplements Product, Harness, AppService, or AppHost runtime semantics.

Do not read Git repositories directly from the GUI. Workspace, worktree,
branch, change, and Diff values must arrive through accepted HarnessClient
facets. Do not expose authentication material to the WebView.

The B1 shell remains offline and its sample data must stay visibly labelled as a
fixture. Cross-language value contracts belong to C1; the real G16 connection
belongs to B2. Keep deterministic fixture controls out of the AppService and add
only the capability required by the current accepted slice.

Use the package scripts documented in `README.md`. Keep Node, pnpm, Rust, Cargo,
and pnpm lock files synchronized, and verify changes with `pnpm run check` from
this directory.
