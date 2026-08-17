# Harness Workspace Path And Mutation Boundary

## Status

Status: accepted for `lane/harness`.

This document defines product-neutral workspace path resolution, canonical path
identity, optional user-input compatibility helpers, and per-path mutation
coordination as `loushang.harness.workspace` responsibilities. Coding keeps its
tool input syntax and default correction policy.

## Path Engine Decision

`loushang.harness.workspace.paths` owns:

- `PathNormalizer` and `PathVariantProvider` contracts;
- `expand_user_path` for current-user `~` expansion;
- `resolve_path_from_cwd` for caller-supplied relative path resolution;
- `resolve_workspace_path` as the configurable resolution engine;
- `canonicalize_workspace_path` for stable absolute path identity;
- `normalize_unicode_spaces` as an opt-in input normalizer;
- `user_input_path_variants` as an opt-in provider for macOS screenshot spacing,
  Unicode NFD, curly quote, and combined variants.

The engine does not enable product syntax or correction policy by itself.
Callers select normalizers and variant providers. The normalized candidate is
tried first; optional variants are checked only when that candidate does not
exist.

Tilde expansion and caller-supplied `cwd` resolution are mechanisms. They do
not grant filesystem access or choose an allowed workspace root. Product policy
must validate the resolved path before a protected operation executes.

## Product Path Policy

Coding's product tool pack chooses its accepted input syntax and any default
normalizer or variant provider. The old `coding.tools.path_utils` adapter is
removed; generic callers import the Harness path engine directly.

## Mutation Queue Decision

`loushang.harness.workspace.mutation_queue` owns:

- `with_file_mutation_queue`;
- `run_with_file_mutation_queue`;
- the canonical-path lock registry and cleanup mechanics.

The queue uses `canonicalize_workspace_path` and
`loushang.harness.workspace.operations.resolve_operation`. It serializes work
for one canonical absolute path while allowing different paths to progress
independently. It does not decide which operations require serialization or
whether a mutation is allowed.

## Facade Removal

`loushang.coding.tools` does not re-export path or mutation helpers. There are
no Coding camelCase aliases; call sites use the concrete Harness API.

## Dependency Direction

The target direction is:

```text
coding tool pack and path policy
  -> loushang.harness.workspace.paths
  -> loushang.harness.workspace.mutation_queue
  -> loushang.harness.workspace.operations
```

Harness path and mutation modules must not import coding, method, work, TUI,
AI, provider, or product packages. No path or mutation symbols are added to
top-level `loushang.harness.__all__`.

## Non-Goals

This migration does not:

- define workspace roots, sandbox permissions, approval, or mutation policy;
- choose concrete product tool membership;
- make the `@` prefix a harness default;
- make Unicode or platform correction helpers mandatory;
- move Pi-style aliases into harness or Coding;
- change coding path resolution order, queue concurrency, or cleanup behavior.

## Validation

The migration must prove:

- current-user expansion and caller-supplied `cwd` resolution;
- configurable normalizer and variant-provider ordering;
- stable absolute canonical identity and relative-path rejection;
- direct Harness callers preserve configured path behavior;
- same-path serialization, different-path concurrency, and failure cleanup;
- direct Harness queue imports preserve function and registry identity;
- write/edit monkeypatch behavior remains unchanged;
- harness import boundaries and top-level export discipline still pass.
