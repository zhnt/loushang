# HarnessGUI Contributor Notes

## Branch and integration workflow

Use `lane/gui` as the shared integration branch for the current GUI improvement
work. The long-lived `.worktrees/gui` lane normally checks out `lane/gui`.
Create GUI feature branches from the latest `lane/gui` and name them
`feature/gui-<topic>` (for example, `feature/gui-app-icons`). For sequential
work, the GUI lane may temporarily check out a feature branch; use separate
task worktrees for parallel features. Check dirty state and preserve existing
changes before switching branches.

Run the checks appropriate to each feature before merging it into `lane/gui`.
Collect a coherent delivery batch there, then perform combined native build,
layout and desktop acceptance appropriate to the changed surfaces before
opening a PR from `lane/gui` to `main`. Do not send individual GUI features
directly to `main` during this workflow. Keep a record of validation results
and unresolved limitations in the delivery PR; automated web tests do not
establish native desktop acceptance.

Regularly merge the latest `main` into `lane/gui`; do not rebase or force-push
the shared integration branch. This workflow does not add or expand mandatory
PR gates. GUI changes that cross shared contracts or subsystem boundaries
still follow their existing review and validation requirements.

## Ownership and validation

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

Use the package scripts documented in `README.md`. Keep Node, npm, Rust, Cargo,
and npm lock files synchronized, and verify changes with `npm run check` from
this directory. During rapid B1 development this command runs only TypeScript
type checking and offline unit/playback tests. Run `npm run check:full` when
changing Rust, native capabilities, or native toolchain configuration. Browser
layout playback and standalone packaging are on-demand acceptance checks, not
mandatory checks on every presentation edit. Do not run TUI or Harness suites
for GUI-only changes; shared contracts and shared CI changes retain their gates.
