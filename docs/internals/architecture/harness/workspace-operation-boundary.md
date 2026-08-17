# Harness Workspace Operation Boundary

## Status

Status: accepted for `lane/harness`.

This document defines product-neutral filesystem operation protocols and the
local filesystem backend as `loushang.harness.workspace` responsibilities.
Products keep tool cancellation behavior, workspace policy, and product tool
selection; concrete tool behavior is Harness-owned.

## Decision

`loushang.harness.workspace.operations` owns:

- `OperationResult` and `resolve_operation` for sync-or-async backend results;
- `ReadOperations`;
- `WriteOperations`;
- `EditOperations`;
- `LsOperations`;
- `FindOperations`;
- `GrepOperations`;
- the combined `ToolOperations` protocol;
- `LocalToolOperations` and `LOCAL_TOOL_OPERATIONS`.

The focused harness module is the public owner for these neutral contracts.

The local backend is an unscoped filesystem mechanism. It reads, writes,
creates directories, lists directories, and walks files for paths supplied by
its caller. It does not select an allowed root, resolve a product-relative
path, request approval, or decide whether an operation is safe.

## Product-Owned Behavior

Coding keeps tool descriptions, its default pack, coding path input policy,
approval and risk policy, AI image/content projection, and user-facing result
text. `loushang.coding.tools.operations` is removed; all consumers import the
Harness operation owner directly.

## Dependency Direction

The target direction is:

```text
coding tool pack and product policy
  -> loushang.harness.workspace.operations
```

The harness module must not import coding, method, work, TUI, AI, provider, or
product packages. No operation symbols are added to top-level
`loushang.harness.__all__`.

## Non-Goals

This migration does not:

- choose default product tools;
- reintroduce Pi-style compatibility adapters;
- move tool cancellation or signal semantics;
- move file mutation queueing or path canonicalization;
- define workspace roots, sandbox policy, approval policy, or default tools;
- change sync/async backend behavior or filesystem encoding behavior.

Path canonicalization and mutation queueing were non-goals of this operation
owner move, not permanent coding ownership decisions. Their subsequent owner
move is defined by the
[Workspace Path And Mutation Boundary](workspace-path-mutation-boundary.md).

## Validation

The migration must prove:

- sync and async operation results resolve through the harness owner;
- local filesystem reads, writes, directory operations, and walks are unchanged;
- direct Harness imports preserve class and singleton identity;
- custom operation backends remain compatible;
- `LocalToolOperations` monkeypatch behavior is unchanged;
- product internal consumers use the harness owner;
- harness import boundaries and top-level export discipline still pass.
