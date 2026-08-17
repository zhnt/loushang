# Workspace And Terminal Platform Capabilities Boundary

## Decision

Repository metadata discovery and terminal clipboard access are shared
capabilities, not Coding product behavior. Their canonical owners are:

- `loushang.harness.workspace.git` for Git worktree discovery and branch reads;
- `loushang.tui.clipboard` for copying text through host clipboard commands;
- `loushang.tui.clipboard_image` for reading and normalizing clipboard images.

`loushang.coding.platform` no longer owns or re-exports these capabilities.
The retired modules `loushang.coding.platform.git`,
`loushang.coding.platform.clipboard`, and
`loushang.coding.platform.clipboard_image` must remain absent. Internal callers
import their canonical owners directly; no compatibility facade is retained.

## Dependency Direction

The ownership split preserves independent foundation packages:

```text
Coding ───────> Harness workspace Git
   └──────────> Native TUI clipboard capabilities

Harness       Native TUI
   (no TUI)      (no Harness or Coding)
```

Harness Git support uses only filesystem and process primitives. Native TUI
clipboard support uses only host-platform primitives. Harness and TUI therefore
remain peers; neither foundation imports the other. HarnessTUI may continue to
depend on both Harness and TUI without reversing either dependency.

## Product Boundary

Coding still owns product-specific platform policy and projections, including:

- changelog and Loushang version behavior;
- stdout takeover and restoration;
- footer snapshot composition and caching;
- the decision to expose `/copy` and the command's user-facing result.

Those adapters consume the canonical shared capabilities. They do not acquire
ownership by wrapping or re-exporting them.

## Compatibility Policy

This is an internal canonical-path cutover. Reintroducing aliases under
`loushang.coding.platform`, including lazy package exports, would restore a
second owner and is prohibited. Tests enforce both retired-path absence and
direct imports from the canonical modules.
