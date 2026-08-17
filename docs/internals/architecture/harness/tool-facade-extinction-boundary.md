# Harness Tool Facade Extinction Boundary

## Status

Implemented on `lane/harness`.

## Decision

`loushang.coding.tools` is removed. It was a compatibility facade over
Harness-owned workspace tools and caused product consumers to keep importing
the wrong owner.

Reusable tool contracts, schema inference, decorated-tool normalization,
wrapping, workspace tool implementations, external-tool resolution, path
helpers, truncation, mutation coordination, presentation helpers, and runtime
helpers are imported from their concrete `loushang.harness.tools` or
`loushang.harness.workspace` owner. The old Coding package and its Pi-style
camelCase aliases are intentionally unavailable.

## Product Boundary

`loushang.coding.tool_pack` is the only Coding module in this area. It owns:

- Coding's selected default seven-tool membership and activation order;
- Coding-specific tool descriptions and prompt snippets;
- declaration of the Coding `WorkspaceToolProfile`; and
- injection of Coding policy, approval, diagnostics, and execution services.

`loushang.harness.tools.workspace.registry.WorkspaceToolRegistry` owns the
generic decorated-tool normalization, context-aware materialization, and
contribution resolution. Its `register_profile()` method composes the existing
factory, pack, resolver, and registry rather than introducing another tool
runtime. It is not a Coding type.

## Dependency Direction

```text
coding.tool_pack
  -> harness.tools.workspace
  -> harness.tools.core / harness.workspace
```

Harness must not import Coding. Coding production modules must not import
`loushang.coding.tools`; that package must not be recreated as a compatibility
shim.

## Validation

- Generic workspace tools execute without importing Coding.
- Coding registers its default pack through `WorkspaceToolRegistry`.
- `import loushang.coding.tools` raises `ModuleNotFoundError`.
- Import-boundary tests reject both production imports of the old facade and
  future restoration of its package directory.
